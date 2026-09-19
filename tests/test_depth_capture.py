import json

import numpy as np

from floorplan_takehome.depth_capture import _unproject_grid, load_point_cloud


def _identity_view(depth_grid, fx=1.0, fy=1.0):
    identity = np.eye(4).flatten(order="F").tolist()
    proj = np.diag([fx, fy, 1.0, 1.0]).flatten(order="F").tolist()
    return {
        "transform_matrix": identity,
        "projection_matrix": proj,
        "depth_grid_meters": depth_grid,
    }


def test_center_ray_at_known_depth():
    view = _identity_view([[2.0]])
    points = _unproject_grid(view)
    assert points.shape == (1, 3)
    np.testing.assert_allclose(points[0], [0.0, 0.0, -2.0], atol=1e-9)


def test_two_rays_spread_symmetrically():
    view = _identity_view([[1.0, 1.0]])
    points = _unproject_grid(view)
    assert points.shape == (2, 3)
    xs = sorted(points[:, 0])
    np.testing.assert_allclose(xs, [-0.5, 0.5], atol=1e-9)
    np.testing.assert_allclose(points[:, 2], [-1.0, -1.0], atol=1e-9)


def test_missing_depth_values_are_skipped():
    view = _identity_view([[1.0, None]])
    points = _unproject_grid(view)
    assert points.shape == (1, 3)


def test_camera_translation_carries_through():
    view = _identity_view([[3.0]])
    view["transform_matrix"] = (
        np.array(
            [
                [1, 0, 0, 5],
                [0, 1, 0, 0],
                [0, 0, 1, 0],
                [0, 0, 0, 1],
            ],
            dtype=float,
        )
        .flatten(order="F")
        .tolist()
    )
    points = _unproject_grid(view)
    np.testing.assert_allclose(points[0], [5.0, 0.0, -3.0], atol=1e-9)


def test_load_point_cloud_from_capture_file(tmp_path):
    capture = {
        "captures": [
            {"views": [_identity_view([[1.0]])]},
            {"views": [_identity_view([[2.0]])]},
        ]
    }
    path = tmp_path / "capture.json"
    path.write_text(json.dumps(capture))

    cloud = load_point_cloud(str(path))
    assert len(cloud.points) == 2
