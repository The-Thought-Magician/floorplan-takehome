"""Multi-room floor plan from a y-up point cloud with a known floor.

Approach (no learned model, works on every tier that yields a floor):
1. Rasterise floor points into a free-space mask and wall-band points into a wall
   density mask, both in a frame rotated to the dominant wall direction.
2. Split free space into rooms by eroding past the doorway half-width, labelling
   the pieces, and growing them back inside free space.
3. Per room, trace the boundary, simplify, snap edges to the room axes, and
   intersect consecutive edges into a rectilinear polygon.
4. Rooms that touch after growing back are adjacent, the contact length is the
   doorway width.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np
from scipy import ndimage


@dataclass
class RoomPolygon:
    label: int
    corners_xz: np.ndarray  # (n, 2) metres, world frame
    area_m2: float
    wall_lengths_m: list[float]
    doorways: list[dict] = field(default_factory=list)


def dominant_angle(wall_xz: np.ndarray) -> float:
    """Rotation (radians) that makes the walls axis aligned, from a 90-degree periodic histogram."""
    if len(wall_xz) < 200:
        return 0.0
    sample = wall_xz[np.random.default_rng(0).choice(len(wall_xz), min(len(wall_xz), 20000), replace=False)]
    # orientation of local structure via PCA of neighbourhoods is overkill, a 2D
    # Hough on the density image is enough
    cell = 0.03
    lo = sample.min(axis=0)
    img = np.zeros(((np.ptp(sample, axis=0) / cell).astype(int) + 2)[::-1], dtype=np.uint8)
    ij = ((sample - lo) / cell).astype(int)
    img[ij[:, 1], ij[:, 0]] = 255
    lines = cv2.HoughLinesP(img, 1, np.pi / 180, threshold=40, minLineLength=int(0.6 / cell), maxLineGap=int(0.1 / cell))
    if lines is None:
        return 0.0
    angles, weights = [], []
    for x1, y1, x2, y2 in lines.reshape(-1, 4):
        angles.append(np.arctan2(y2 - y1, x2 - x1))
        weights.append(np.hypot(x2 - x1, y2 - y1))
    phase = np.average(np.exp(4j * np.array(angles)), weights=np.array(weights))
    return -np.angle(phase) / 4


def _rotate(xz: np.ndarray, angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return xz @ np.array([[c, -s], [s, c]]).T


def _rasterise(xz: np.ndarray, origin: np.ndarray, cell: float, shape: tuple[int, int]) -> np.ndarray:
    ij = np.floor((xz - origin) / cell).astype(int)
    ok = (ij[:, 0] >= 0) & (ij[:, 1] >= 0) & (ij[:, 0] < shape[1]) & (ij[:, 1] < shape[0])
    counts = np.zeros(shape, dtype=np.int32)
    np.add.at(counts, (ij[ok, 1], ij[ok, 0]), 1)
    return counts


def _rectilinear_polygon(mask: np.ndarray, cell: float, origin: np.ndarray, notch_m: float = 0.25, min_edge_m: float = 0.30) -> np.ndarray | None:
    """Boundary of a binary mask as an axis-aligned polygon in metres (rotated frame).

    The mask is opened and closed with a square kernel first, which removes notches
    and spurs narrower than notch_m and leaves a rectilinear outline.
    """
    k = int(notch_m / cell) | 1
    kernel = np.ones((k, k), np.uint8)
    m = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_OPEN, kernel)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, kernel)
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    contour = max(contours, key=cv2.contourArea)
    approx = cv2.approxPolyDP(contour, epsilon=0.06 / cell, closed=True)[:, 0, :].astype(float)
    if len(approx) < 4:
        return None
    pts = (approx + 0.5) * cell + origin

    edges = np.roll(pts, -1, axis=0) - pts
    along_x = np.abs(edges[:, 0]) >= np.abs(edges[:, 1])
    # merge consecutive edges with the same orientation
    keep = [i for i in range(len(pts)) if along_x[i] != along_x[i - 1]]
    if len(keep) < 4:
        return None
    pts, along_x = pts[keep], along_x[keep]
    # each edge becomes an axis-aligned line: (along_x, offset). Corners are intersections of
    # consecutive lines, and the length of edge i is the gap between its two neighbours' offsets.
    lines = []
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        lines.append([bool(along_x[i]), (a[1] + b[1]) / 2 if along_x[i] else (a[0] + b[0]) / 2])

    def edge_len(i):
        return abs(lines[(i + 1) % len(lines)][1] - lines[i - 1][1])

    # notch removal: drop the shortest edge by merging its perpendicular neighbours
    while len(lines) > 4:
        lengths = [edge_len(i) for i in range(len(lines))]
        i = int(np.argmin(lengths))
        if lengths[i] >= min_edge_m:
            break
        prev, nxt = (i - 1) % len(lines), (i + 1) % len(lines)
        w_prev, w_next = edge_len(prev), edge_len(nxt)
        merged = (lines[prev][1] * w_prev + lines[nxt][1] * w_next) / max(w_prev + w_next, 1e-9)
        lines[prev][1] = merged
        for j in sorted({i, nxt}, reverse=True):
            del lines[j]
    if len(lines) < 4 or len(lines) % 2:
        return None

    corners = []
    for i in range(len(lines)):
        j = (i + 1) % len(lines)
        if lines[i][0]:
            corners.append([lines[j][1], lines[i][1]])  # edge i fixes z, edge j fixes x
        else:
            corners.append([lines[i][1], lines[j][1]])
    return np.array(corners)


def _polygon_area(c: np.ndarray) -> float:
    x, z = c[:, 0], c[:, 1]
    return float(abs(np.dot(x, np.roll(z, -1)) - np.dot(z, np.roll(x, -1))) / 2)


def segment_rooms(
    points: np.ndarray,
    floor_y: float,
    ceiling_y: float | None,
    cell: float = 0.03,
    door_half_width_m: float = 0.55,
    corridor_half_width_m: float = 0.30,
    min_room_m2: float = 1.0,
    wall_min_height_m: float = 1.5,
) -> tuple[list[RoomPolygon], dict]:
    """Points (n, 3) y-up in metres with a known floor height to per-room polygons."""
    y = points[:, 1]
    top = (ceiling_y - 0.15) if ceiling_y is not None else floor_y + 2.6
    body = points[(y > floor_y - 0.10) & (y < top)]
    if (np.abs(y - floor_y) < 0.10).sum() < 200:
        return [], {"reason": "not enough floor points"}

    # walls are tall, furniture is short: a cell is wall if its points reach wall_min_height
    tall = body[body[:, 1] > floor_y + wall_min_height_m]
    angle = dominant_angle(tall[:, [0, 2]]) if len(tall) >= 200 else 0.0
    body_xz = _rotate(body[:, [0, 2]], angle)
    origin = body_xz.min(axis=0) - 0.5
    shape = tuple((((body_xz.max(axis=0) + 0.5) - origin) / cell).astype(int)[::-1] + 1)

    # a wall cell has points at every height; ceiling plus furniture only fills the top and bottom
    band_edges = floor_y + np.array([0.2, 0.7, 1.2, 1.7, 2.2])
    occupied_bands = np.zeros(shape, dtype=np.int32)
    for lo, hi in zip(band_edges[:-1], band_edges[1:]):
        sel = (body[:, 1] >= lo) & (body[:, 1] < hi)
        occupied_bands += _rasterise(body_xz[sel], origin, cell, shape) > 0
    count = _rasterise(body_xz, origin, cell, shape)
    wall_mask = occupied_bands >= 3
    wall_mask = cv2.morphologyEx(wall_mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)).astype(bool)

    # free space: floor or short obstacles, holes filled (furniture hides the floor beneath it)
    occupied_low = (count > 0) & ~wall_mask
    k = int(0.35 / cell) | 1
    free = cv2.morphologyEx(occupied_low.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((k, k), np.uint8)).astype(bool)
    free = ndimage.binary_fill_holes(free) & ~wall_mask

    # split at doorways: erode past the doorway half width, label the cores as rooms.
    # Narrow spaces (corridors) vanish at that erosion, so a second, gentler erosion
    # adds seeds for free space no room core reached.
    def cores_at(radius_m):
        px = int(radius_m / cell)
        return cv2.erode(free.astype(np.uint8), np.ones((2 * px + 1, 2 * px + 1), np.uint8)).astype(bool)

    labels, n = ndimage.label(cores_at(door_half_width_m))
    sizes = ndimage.sum(labels > 0, labels, range(1, n + 1))
    keep_ids = [i + 1 for i, s in enumerate(sizes) if s * cell * cell >= min_room_m2]
    seeds = np.where(np.isin(labels, keep_ids), labels, 0)

    narrow, n2 = ndimage.label(cores_at(corridor_half_width_m) & (seeds == 0))
    # a narrow component that touches a room core is that room's fringe, not a corridor
    touching = set(np.unique(cv2.dilate((seeds > 0).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) * narrow)) - {0}
    sizes2 = ndimage.sum(narrow > 0, narrow, range(1, n2 + 1))
    next_id = (max(keep_ids) if keep_ids else 0) + 1
    for i, s in enumerate(sizes2):
        if (i + 1) not in touching and s * cell * cell >= min_room_m2:
            seeds[narrow == i + 1] = next_id
            keep_ids.append(next_id)
            next_id += 1

    # region growing: nearest seed within free space
    dist, (ri, ci) = ndimage.distance_transform_edt(seeds == 0, return_indices=True)
    grown = np.where(free, seeds[ri, ci], 0)

    rooms = []
    for room_id in keep_ids:
        mask = grown == room_id
        # a room polygon should follow the wall faces, so grow the mask half a cell into the wall band
        mask = cv2.dilate(mask.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & ~np.isin(grown, [i for i in keep_ids if i != room_id])
        corners_rot = _rectilinear_polygon(mask, cell, origin)
        if corners_rot is None:
            continue
        corners = _rotate(corners_rot, -angle)
        lengths = [float(np.linalg.norm(corners[(i + 1) % len(corners)] - corners[i])) for i in range(len(corners))]
        rooms.append(RoomPolygon(label=room_id, corners_xz=corners, area_m2=_polygon_area(corners), wall_lengths_m=lengths))

    # adjacency: rooms whose grown regions touch, contact length as doorway width
    for a in range(len(rooms)):
        for b in range(a + 1, len(rooms)):
            ma = grown == rooms[a].label
            mb = cv2.dilate((grown == rooms[b].label).astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            contact = int((ma & mb).sum())
            if contact >= int(0.5 / cell):
                width = contact * cell
                rooms[a].doorways.append({"to": rooms[b].label, "width_m": round(width, 2)})
                rooms[b].doorways.append({"to": rooms[a].label, "width_m": round(width, 2)})

    info = {
        "rotation_deg": round(float(np.degrees(angle)), 2),
        "cell_m": cell,
        "grid": shape,
        "rooms_found": len(rooms),
        "free_area_m2": round(float(free.sum()) * cell * cell, 2),
    }
    return rooms, info


def render_rooms(points: np.ndarray, rooms: list[RoomPolygon], out_png, cameras: np.ndarray | None = None, title: str = "") -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 8))
    sub = points[np.random.default_rng(0).choice(len(points), min(len(points), 150000), replace=False)]
    ax.scatter(sub[:, 0], sub[:, 2], s=1, c=sub[:, 1], cmap="viridis", alpha=0.4)
    for room in rooms:
        c = np.vstack([room.corners_xz, room.corners_xz[:1]])
        ax.plot(c[:, 0], c[:, 1], "r-", linewidth=2)
        cx, cz = room.corners_xz.mean(axis=0)
        ax.text(cx, cz, f"R{room.label}\n{room.area_m2:.1f} m2", color="red", ha="center", fontsize=9, weight="bold")
        for i, length in enumerate(room.wall_lengths_m):
            m = (c[i] + c[i + 1]) / 2
            ax.text(m[0], m[1], f"{length * 100:.0f}", color="darkred", fontsize=7, ha="center")
    if cameras is not None and len(cameras):
        ax.plot(cameras[:, 0], cameras[:, 2], "k.-", linewidth=0.8, markersize=2)
    ax.set_aspect("equal")
    ax.set_title(title)
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
