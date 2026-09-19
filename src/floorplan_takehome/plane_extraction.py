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
    _, _, vt = np.linalg.svd(points - centroid)
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


def wall_polygon(walls: list[Plane]) -> list[np.ndarray]:
    """Return closed polygon corners, or [] if walls don't have enough
    orientation diversity to form one (all near-parallel, or too few walls)."""
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
