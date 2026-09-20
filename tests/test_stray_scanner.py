import numpy as np

from floorplan_takehome.stray_scanner import frame_to_points, load_odometry


def test_frame_to_points_unprojects_centre_pixel_along_negative_z(tmp_path):
    import cv2

    depth = np.zeros((192, 256), dtype=np.uint16)
    depth[96, 128] = 2000  # 2 m at the centre
    conf = np.full((192, 256), 2, dtype=np.uint8)
    cv2.imwrite(str(tmp_path / "d.png"), depth)
    cv2.imwrite(str(tmp_path / "c.png"), conf)
    intrinsics = np.array([[1600.0, 0, 960.0], [0, 1600.0, 720.0], [0, 0, 1]])
    pts = frame_to_points(tmp_path / "d.png", tmp_path / "c.png", intrinsics, pixel_stride=1)
    assert pts.shape == (1, 3)
    np.testing.assert_allclose(pts[0, 2], 2.0)
    assert abs(pts[0, 0]) < 0.02 and abs(pts[0, 1]) < 0.02


def test_load_odometry_builds_camera_to_world(tmp_path):
    (tmp_path / "odometry.csv").write_text(
        "timestamp, frame, x, y, z, qx, qy, qz, qw, fx, fy, cx, cy, distortion_center_x, distortion_center_y\n"
        "1.0, 000007, 1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0, 1,1,1,1,,\n"
    )
    poses = load_odometry(tmp_path)
    np.testing.assert_allclose(poses["000007"], np.array([[1, 0, 0, 1], [0, 1, 0, 2], [0, 0, 1, 3], [0, 0, 0, 1]], dtype=float))
