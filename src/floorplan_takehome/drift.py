"""Drift accountability for multi-room captures.

VIO yaw drifts slowly. Walls do not: within one building they share two
perpendicular directions. So the dominant wall direction seen in each time window
of the capture is a heading reference. The deviation of each window's wall
direction from the first window's, folded to (-45, 45] degrees, is the yaw drift
at that time. A linear fit over time gives a drift rate; each pose is rotated about
the vertical axis by the negative of the fitted drift at its time.

What this corrects: heading drift, the dominant term in long ARCore/ARKit walks and
the one that bends a stitched footprint. What it does not correct: position drift
(the walk does not return to a known point), so no loop closure claim is made. The
ablation reports the footprint with the correction on and off.
"""

from dataclasses import dataclass

import numpy as np

from floorplan_takehome.rooms import dominant_angle


@dataclass
class DriftEstimate:
    window_frames: list[int]
    deviation_deg: list[float]
    rate_deg_per_min: float
    fit_deg: list[float]
    fps: float

    def correction_deg(self, frame_index: int) -> float:
        return float(np.interp(frame_index, self.window_frames, self.fit_deg))


def _fold90(deg: float) -> float:
    return (deg + 45.0) % 90.0 - 45.0


def estimate_yaw_drift(points_by_window: list[tuple[int, np.ndarray]], floor_y: float, fps: float = 60.0,
                       wall_min_height_m: float = 1.2) -> DriftEstimate | None:
    """points_by_window: [(centre frame index, world points (n, 3) of that window)]."""
    frames, devs = [], []
    ref = None
    for centre, pts in points_by_window:
        tall = pts[pts[:, 1] > floor_y + wall_min_height_m]
        if len(tall) < 500:
            continue
        ang = np.degrees(dominant_angle(tall[:, [0, 2]]))
        if ref is None:
            ref = ang
        frames.append(centre)
        devs.append(_fold90(ang - ref))
    if len(frames) < 3:
        return None
    x = np.array(frames, dtype=float)
    slope, intercept = np.polyfit(x, np.array(devs), 1)
    fit = (slope * x + intercept).tolist()
    return DriftEstimate(
        window_frames=frames,
        deviation_deg=[round(d, 2) for d in devs],
        rate_deg_per_min=round(float(slope * fps * 60), 3),
        fit_deg=[round(f, 2) for f in fit],
        fps=fps,
    )


def rotate_pose_yaw(m: np.ndarray, deg: float) -> np.ndarray:
    """Rotate a camera-to-world pose about the world vertical axis through the camera position."""
    th = np.radians(deg)
    ry = np.array([[np.cos(th), 0, np.sin(th)], [0, 1, 0], [-np.sin(th), 0, np.cos(th)]])
    out = m.copy()
    out[:3, :3] = ry @ m[:3, :3]
    return out


def apply_drift_correction(poses: dict[str, np.ndarray], estimate: DriftEstimate) -> dict[str, np.ndarray]:
    """Orientation-only correction: undo the fitted heading drift at each frame's time."""
    corrected = {}
    for frame, m in poses.items():
        idx = int(frame)
        corrected[frame] = rotate_pose_yaw(m, -estimate.correction_deg(idx))
    return corrected


def footprint_metrics(points: np.ndarray, floor_y: float, cell: float = 0.03, wall_min_height_m: float = 1.2) -> dict:
    """How crisp the stitched footprint is: wall mask area per unit of wall length is
    what drift smears. Lower thickness is better; the free area is what the plan
    would report."""
    import cv2

    tall = points[points[:, 1] > floor_y + wall_min_height_m]
    if len(tall) < 500:
        return {"wall_cells": 0}
    ang = dominant_angle(tall[:, [0, 2]])
    c, s = np.cos(ang), np.sin(ang)
    xz = tall[:, [0, 2]] @ np.array([[c, -s], [s, c]]).T
    origin = xz.min(axis=0) - 0.2
    shape = tuple((((xz.max(axis=0) + 0.2) - origin) / cell).astype(int)[::-1] + 1)
    ij = np.floor((xz - origin) / cell).astype(int)
    grid = np.zeros(shape, dtype=np.uint8)
    grid[ij[:, 1], ij[:, 0]] = 1
    grid = cv2.morphologyEx(grid, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    dist = cv2.distanceTransform(grid, cv2.DIST_L2, 3)
    inside = dist[grid.astype(bool)]
    return {
        "wall_cells": int(grid.sum()),
        "wall_area_m2": round(float(grid.sum()) * cell * cell, 2),
        # mean distance to the mask edge, doubled, is the mean wall thickness
        "mean_wall_thickness_cm": round(float(inside.mean()) * 2 * cell * 100, 1) if len(inside) else None,
    }
