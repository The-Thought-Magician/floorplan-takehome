import json

import numpy as np
import pytest

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


def _buffer_view(depth_m, fx=1.0, fy=1.0, fmt="luminance-alpha", flip_matrix=None):
    import base64

    depth_m = np.asarray(depth_m, dtype=float)
    h, w = depth_m.shape
    if fmt == "float32":
        raw = depth_m.astype("<f4").tobytes()
        scale = 1.0
    else:
        raw = np.round(depth_m * 1000).astype("<u2").tobytes()
        scale = 0.001
    view = _identity_view(None, fx, fy)
    view["depth_buffer"] = {
        "width": w,
        "height": h,
        "format": fmt,
        "raw_value_to_meters": scale,
        "norm_depth_buffer_from_norm_view": (np.eye(4) if flip_matrix is None else flip_matrix).flatten(order="F").tolist(),
        "data_b64": base64.b64encode(raw).decode(),
    }
    return view


def test_full_buffer_matches_grid_unprojection():
    grid = [[1.0, 1.0]]
    from_grid = _unproject_grid(_identity_view(grid))
    from_buffer = _unproject_grid(_buffer_view(grid))
    np.testing.assert_allclose(from_buffer, from_grid, atol=1e-9)


def test_float32_buffer_and_zero_means_invalid():
    view = _buffer_view([[2.0, 0.0]], fmt="float32")
    points = _unproject_grid(view)
    assert points.shape == (1, 3)
    np.testing.assert_allclose(points[0, 2], -2.0, atol=1e-6)


def test_norm_matrix_y_flip_is_honoured():
    # a y-flipping normDepthBufferFromNormView means view row 0 reads buffer row 1
    flip = np.array([[1, 0, 0, 0], [0, -1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
    view = _buffer_view([[1.0], [3.0]], flip_matrix=flip)
    points = _unproject_grid(view)
    # top of view (ndc_y > 0) should carry the depth stored in the bottom buffer row (3.0)
    top = points[points[:, 1] > 0]
    np.testing.assert_allclose(top[0, 2], -3.0, atol=1e-6)


def test_buffer_falls_back_to_grid_when_inconsistent():
    view = _buffer_view([[1.0]])
    view["depth_grid_meters"] = [[5.0]]
    with pytest.warns(UserWarning):
        points = _unproject_grid(view)
    np.testing.assert_allclose(points[0, 2], -5.0, atol=1e-6)


def test_points_beyond_max_range_are_dropped():
    view = _identity_view([[1.0, 9.0]])
    assert _unproject_grid(view, max_range_m=6.0).shape == (1, 3)
