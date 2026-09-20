import numpy as np
import open3d as o3d

from floorplan_takehome.plane_extraction import (
    Plane,
    merge_walls,
    polygon_area,
    polygon_perimeter,
    segment_planes,
    wall_polygon,
)


def _wall_points(x_range, z_range, n=200, y_range=(0.0, 2.5)):
    xs = np.random.uniform(*x_range, n)
    zs = np.random.uniform(*z_range, n)
    ys = np.random.uniform(*y_range, n)
    return np.stack([xs, ys, zs], axis=1)


def _rectangular_room(width=3.0, depth=4.0):
    # walls at x=0, x=width, z=0, z=depth
    return np.concatenate(
        [
            _wall_points((0, 0), (0, depth)),
            _wall_points((width, width), (0, depth)),
            _wall_points((0, width), (0, 0)),
            _wall_points((0, width), (depth, depth)),
        ]
    )


def test_segment_planes_finds_four_walls():
    points = _rectangular_room()
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)

    planes = segment_planes(cloud, distance_threshold=0.01, max_planes=6, min_inliers=50)
    walls = [p for p in planes if p.is_wall]
    assert len(walls) == 4


def test_wall_polygon_recovers_rectangle_dimensions():
    points = _rectangular_room(width=3.0, depth=4.0)
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)

    planes = segment_planes(cloud, distance_threshold=0.01, max_planes=6, min_inliers=50)
    walls = [p for p in planes if p.is_wall]
    corners = wall_polygon(walls)

    assert len(corners) == 4
    assert polygon_area(corners) == pytest_approx(12.0)
    assert polygon_perimeter(corners) == pytest_approx(14.0)


def pytest_approx(value, tol=0.05):
    class _Approx:
        def __eq__(self, other):
            return abs(other - value) < tol

    return _Approx()


def test_merge_walls_collapses_noisy_duplicate_of_same_wall():
    # one real wall near x=2, RANSAC-split into two close, slightly-tilted layers
    layer_a = _wall_points((1.95, 2.05), (0, 4))
    layer_b = _wall_points((2.05, 2.15), (0, 4))
    other_wall = _wall_points((-0.05, 0.05), (0, 4))

    def normal_of(pts):
        return _refit_normal(pts)

    walls = [
        Plane(normal=normal_of(layer_a), d=-normal_of(layer_a) @ layer_a.mean(axis=0), points=layer_a),
        Plane(normal=normal_of(layer_b), d=-normal_of(layer_b) @ layer_b.mean(axis=0), points=layer_b),
        Plane(normal=normal_of(other_wall), d=-normal_of(other_wall) @ other_wall.mean(axis=0), points=other_wall),
    ]

    merged = merge_walls(walls, angle_cos_threshold=0.9, d_threshold=0.3)
    assert len(merged) == 2


def _refit_normal(points):
    centroid = points.mean(axis=0)
    _, _, vt = np.linalg.svd(points - centroid, full_matrices=False)
    normal = vt[-1]
    return normal if normal[1] >= 0 else -normal


def test_wall_polygon_rejects_near_parallel_walls_instead_of_garbage():
    a = Plane(normal=np.array([1.0, 0.0, 0.0]), d=0.0, points=np.zeros((5, 3)))
    b = Plane(normal=np.array([0.99, 0.0, 0.05]), d=-1.6, points=np.zeros((5, 3)))
    c = Plane(normal=np.array([0.98, 0.0, -0.06]), d=-2.7, points=np.zeros((5, 3)))
    assert wall_polygon([a, b, c]) == []


def test_is_wall_classifies_horizontal_plane_as_not_wall():
    floor = Plane(normal=np.array([0.0, 1.0, 0.0]), d=0.0, points=np.zeros((5, 3)))
    wall = Plane(normal=np.array([1.0, 0.0, 0.0]), d=0.0, points=np.zeros((5, 3)))
    assert not floor.is_wall
    assert wall.is_wall


def test_tilted_plane_is_neither_wall_nor_horizontal():
    tilted = Plane(normal=np.array([0.79, 0.55, -0.27]), d=0.0, points=np.zeros((5, 3)))
    floor = Plane(normal=np.array([0.0, 1.0, 0.0]), d=0.0, points=np.zeros((5, 3)))
    assert tilted.is_tilted and not tilted.is_wall and not tilted.is_horizontal
    assert floor.is_horizontal and not floor.is_tilted


def test_wall_polygon_rejects_corners_far_outside_observed_points():
    # three short wall fragments whose lines meet far from any observed point
    a = _wall_points((0, 0), (0, 1))
    b = _wall_points((0, 1), (0, 0))
    c = _wall_points((5, 5.1), (0, 1))  # far, nearly parallel to a
    walls = [
        Plane(normal=_refit_normal(a), d=-_refit_normal(a) @ a.mean(axis=0), points=a),
        Plane(normal=_refit_normal(b), d=-_refit_normal(b) @ b.mean(axis=0), points=b),
        Plane(normal=np.array([0.7, 0.0, 0.714]), d=-3.5, points=c),
    ]
    assert wall_polygon(walls, margin_m=0.5) == []


def test_manhattan_filter_drops_diagonal_plane_and_snaps_the_rest():
    from floorplan_takehome.plane_extraction import manhattan_filter

    def plane(nx, nz, pts):
        n = np.array([nx, 0.0, nz]) / np.linalg.norm([nx, nz])
        return Plane(normal=n, d=-n @ pts.mean(axis=0), points=pts)

    walls = [
        plane(1.0, 0.05, _wall_points((0, 0), (0, 4))),        # slightly rotated x wall
        plane(1.0, -0.04, _wall_points((3, 3), (0, 4))),
        plane(0.03, 1.0, _wall_points((0, 3), (0, 0))),
        plane(-0.02, 1.0, _wall_points((0, 3), (4, 4))),
        plane(0.7, 0.7, _wall_points((2.5, 3), (3.5, 4))),     # 45 degree corner artefact
    ]
    kept = manhattan_filter(walls)
    assert len(kept) == 4
    for w in kept:
        assert w.normal[1] == 0.0
        assert min(abs(w.normal[0]), abs(w.normal[2])) < 0.05  # snapped onto an axis
    corners = wall_polygon(kept)
    assert len(corners) == 4
    assert abs(polygon_area(corners) - 12.0) < 0.3
