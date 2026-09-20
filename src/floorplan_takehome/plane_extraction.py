"""Fit wall planes to a point cloud and derive a dimensioned 2D polygon."""

from dataclasses import dataclass

import numpy as np
import open3d as o3d


@dataclass
class Plane:
    normal: np.ndarray  # (a, b, c), unit length
    d: float  # a*x + b*y + c*z + d = 0
    points: np.ndarray  # inlier points, (n, 3)

    @property
    def is_wall(self) -> bool:
        return abs(self.normal[1]) < 0.35

    @property
    def is_horizontal(self) -> bool:
        return abs(self.normal[1]) > 0.9

    @property
    def is_tilted(self) -> bool:
        """Neither wall nor floor/ceiling. On ARCore captures these are almost always
        smooth-depth fill from a textureless surface, not real geometry."""
        return not self.is_wall and not self.is_horizontal


def segment_planes(
    cloud: o3d.geometry.PointCloud,
    distance_threshold: float = 0.06,
    max_planes: int = 8,
    min_inliers: int = 25,
) -> list[Plane]:
    remaining = cloud
    planes = []
    while len(remaining.points) >= min_inliers and len(planes) < max_planes:
        model, inlier_idx = remaining.segment_plane(
            distance_threshold=distance_threshold, ransac_n=3, num_iterations=1000
        )
        if len(inlier_idx) < min_inliers:
            break
        a, b, c, d = model
        normal = np.array([a, b, c])
        norm = np.linalg.norm(normal)
        normal, d = normal / norm, d / norm

        points = np.asarray(remaining.points)[inlier_idx]
        planes.append(Plane(normal=normal, d=d, points=points))
        remaining = remaining.select_by_index(inlier_idx, invert=True)

    return planes


def _refit(points: np.ndarray) -> Plane:
    centroid = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vt[-1]
    if normal[1] < 0:
        normal = -normal
    d = -normal @ centroid
    return Plane(normal=normal, d=d, points=points)


def _xz_line(plane: Plane) -> tuple[float, float, float]:
    """The wall's line in the top-down (x, z) projection: a*x + c*z + d = 0."""
    scale = np.linalg.norm([plane.normal[0], plane.normal[2]])
    a, c = plane.normal[0] / scale, plane.normal[2] / scale
    return a, c, plane.d / scale


def merge_walls(
    walls: list[Plane], angle_cos_threshold: float = 0.92, d_threshold: float = 0.5
) -> list[Plane]:
    remaining = list(walls)
    merged = []
    while remaining:
        base = remaining.pop(0)
        a1, c1, d1 = _xz_line(base)
        group = [base]
        rest = []
        for other in remaining:
            a2, c2, d2 = _xz_line(other)
            dot = a1 * a2 + c1 * c2
            same_orientation = abs(dot) > angle_cos_threshold
            sign = np.sign(dot) or 1
            same_offset = abs(d1 - sign * d2) < d_threshold
            if same_orientation and same_offset:
                group.append(other)
            else:
                rest.append(other)
        remaining = rest
        combined_points = np.concatenate([g.points for g in group], axis=0)
        merged.append(_refit(combined_points))
    return merged


def manhattan_filter(walls: list[Plane], max_dev_deg: float = 20.0) -> list[Plane]:
    """Keep walls aligned with the dominant pair of perpendicular directions and snap them to it.

    Rooms have perpendicular walls. A plane 45 degrees off the room axes is a fit
    through the noise band at a corner, not a wall.
    """
    if len(walls) < 2:
        return list(walls)
    angles = []
    weights = []
    for w in walls:
        a, c, _ = _xz_line(w)
        angles.append(np.arctan2(c, a))
        weights.append(len(w.points))
    # circular mean on the 90 degree period, weighted by point count
    phase = np.average(np.exp(4j * np.array(angles)), weights=np.array(weights))
    axis = np.angle(phase) / 4

    kept = []
    for w, ang in zip(walls, angles):
        dev = (ang - axis + np.pi / 4) % (np.pi / 2) - np.pi / 4
        if abs(np.degrees(dev)) > max_dev_deg:
            continue
        snapped = ang - dev
        a, c = np.cos(snapped), np.sin(snapped)
        normal = np.array([a, 0.0, c])
        d = -float(np.mean(w.points[:, [0, 2]] @ np.array([a, c])))
        kept.append(Plane(normal=normal, d=d, points=w.points))
    return kept


def outer_walls(walls: list[Plane]) -> list[Plane]:
    """Keep the two outermost planes per room axis. Parallel planes between them are furniture."""
    groups: dict[int, list[tuple[float, Plane]]] = {0: [], 1: []}
    for w in walls:
        a, c, d = _xz_line(w)
        axis = 0 if abs(a) >= abs(c) else 1
        sign = np.sign(a if axis == 0 else c) or 1.0
        groups[axis].append((sign * -d, w))  # signed offset along the axis direction
    kept = []
    for members in groups.values():
        members.sort(key=lambda m: m[0])
        if len(members) <= 2:
            kept.extend(w for _, w in members)
        else:
            kept.extend([members[0][1], members[-1][1]])
    return kept


def _order_by_angle(walls: list[Plane]) -> list[Plane]:
    all_points = np.concatenate([w.points for w in walls], axis=0)
    center = all_points[:, [0, 2]].mean(axis=0)

    def angle(wall: Plane) -> float:
        centroid = wall.points[:, [0, 2]].mean(axis=0) - center
        return np.arctan2(centroid[1], centroid[0])

    return sorted(walls, key=angle)


def _line_intersection(p: Plane, q: Plane, min_angle_sin: float = 0.15) -> np.ndarray | None:
    a1, c1, d1 = _xz_line(p)
    a2, c2, d2 = _xz_line(q)

    det = a1 * c2 - a2 * c1
    if abs(det) < min_angle_sin:
        return None
    x = (-d1 * c2 + d2 * c1) / det
    z = (-a1 * d2 + a2 * d1) / det
    return np.array([x, z])


def wall_polygon(walls: list[Plane], margin_m: float = 1.0) -> list[np.ndarray]:
    """Return closed polygon corners, or [] if walls don't have enough
    orientation diversity to form one (all near-parallel, or too few walls),
    or if a corner lands outside the observed points plus a margin, which
    means the walls seen do not enclose a room."""
    if len(walls) < 3:
        return []

    ordered = _order_by_angle(walls)
    corners = []
    n = len(ordered)
    for i in range(n):
        corner = _line_intersection(ordered[i], ordered[(i + 1) % n])
        if corner is None:
            return []
        corners.append(corner)

    all_xz = np.concatenate([w.points[:, [0, 2]] for w in walls], axis=0)
    lo, hi = all_xz.min(axis=0) - margin_m, all_xz.max(axis=0) + margin_m
    if any((c < lo).any() or (c > hi).any() for c in corners):
        return []
    return corners


def polygon_perimeter(corners: list[np.ndarray]) -> float:
    total = 0.0
    n = len(corners)
    for i in range(n):
        total += float(np.linalg.norm(corners[(i + 1) % n] - corners[i]))
    return total


def polygon_area(corners: list[np.ndarray]) -> float:
    n = len(corners)
    area = 0.0
    for i in range(n):
        x1, z1 = corners[i]
        x2, z2 = corners[(i + 1) % n]
        area += x1 * z2 - x2 * z1
    return abs(area) / 2.0
