import numpy as np

from floorplan_takehome.multiview import apply_similarity, camera_centers_from_extrinsics, umeyama


def test_umeyama_recovers_scale_rotation_translation():
    rng = np.random.default_rng(1)
    src = rng.normal(size=(8, 3))
    angle = 0.7
    rot = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]])
    dst = 2.5 * src @ rot.T + np.array([1.0, -2.0, 0.5])

    scale, r, t = umeyama(src, dst)
    assert abs(scale - 2.5) < 1e-9
    np.testing.assert_allclose(r, rot, atol=1e-9)
    np.testing.assert_allclose(apply_similarity(src, scale, r, t), dst, atol=1e-9)


def test_camera_centers_invert_opencv_extrinsics():
    rot = np.eye(3)
    center = np.array([1.0, 2.0, 3.0])
    extrinsic = np.concatenate([rot, (-rot @ center)[:, None]], axis=1)[None]
    np.testing.assert_allclose(camera_centers_from_extrinsics(extrinsic)[0], center)


def test_align_cameras_recovers_similarity_from_orientations_and_centres():
    from floorplan_takehome.multiview import _GL_TO_CV, align_cameras

    rng = np.random.default_rng(2)
    angle = 0.4
    rot_true = np.array([[np.cos(angle), 0, np.sin(angle)], [0, 1, 0], [-np.sin(angle), 0, np.cos(angle)]])
    scale_true, t_true = 1.7, np.array([0.3, -0.2, 1.1])

    extrinsics, known = [], {}
    for i in range(5):
        q, _ = np.linalg.qr(rng.normal(size=(3, 3)))
        if np.linalg.det(q) < 0:
            q[:, 0] *= -1
        centre = rng.normal(size=3)
        r_cv = q.T  # camera-from-world in VGGT world
        extrinsics.append(np.concatenate([r_cv, (-r_cv @ centre)[:, None]], axis=1))
        c2w = np.eye(4)
        c2w[:3, :3] = rot_true @ q @ _GL_TO_CV  # back to WebXR camera axes
        c2w[:3, 3] = scale_true * rot_true @ centre + t_true
        known[i] = c2w

    scale, rotation, translation, info = align_cameras(np.array(extrinsics), known)
    assert abs(scale - scale_true) < 1e-9
    np.testing.assert_allclose(rotation, rot_true, atol=1e-9)
    np.testing.assert_allclose(translation, t_true, atol=1e-9)
    assert info["rotation_residual_deg_max"] < 1e-6


def test_horizontal_frames_drops_floor_facing_cameras():
    from floorplan_takehome.multiview import horizontal_frames

    def pose(pitch_deg):
        th = np.radians(pitch_deg)
        m = np.eye(4)
        # camera looks along -z rotated about x by pitch (positive = up)
        m[:3, :3] = np.array([[1, 0, 0], [0, np.cos(th), -np.sin(th)], [0, np.sin(th), np.cos(th)]])
        return m

    poses = {0: pose(0), 1: pose(-70), 2: pose(30), 3: pose(80)}
    assert horizontal_frames(poses) == [0, 2]


def test_fov_from_exif_uses_the_short_side_for_portrait(tmp_path):
    from PIL import Image
    from PIL.ExifTags import Base

    from floorplan_takehome.multiview import fov_x_from_exif

    im = Image.new("RGB", (600, 800))
    exif = Image.Exif()
    exif[Base.FocalLengthIn35mmFilm] = 26
    p = tmp_path / "p.jpg"
    im.save(p, exif=exif)
    fov = fov_x_from_exif(str(p))
    assert abs(fov - np.degrees(2 * np.arctan(24 / 52))) < 0.1
    assert fov_x_from_exif(str(tmp_path / "missing.jpg")) is None


def test_far_frames_anchor_the_scale():
    from floorplan_takehome.multiview import aggregate_frame_scales

    per_frame = [(1.7, 1.0), (1.8, 1.2), (2.3, 2.5), (2.25, 2.6), (2.35, 2.8), (1.6, 0.9)]
    scale, info = aggregate_frame_scales(per_frame)
    assert abs(scale - 2.3) < 0.05
    assert info["moge_scale_all_frames"] < scale


def test_level_by_camera_up_rotates_mean_up_axis_to_y():
    from floorplan_takehome.multiview import level_by_camera_up

    # cameras whose up axis (OpenCV -y) points along world +z, with some pitch spread
    ext = []
    for pitch in (-10, 0, 10):
        th = np.radians(pitch)
        # world-from-camera with camera y (down) = -z world rotated by pitch about x
        r_wc = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=float) @ np.array([[1, 0, 0], [0, np.cos(th), -np.sin(th)], [0, np.sin(th), np.cos(th)]])
        ext.append(np.concatenate([r_wc.T, np.zeros((3, 1))], axis=1))
    level = level_by_camera_up(np.array(ext))
    up = -np.array(ext)[:, :, :3].transpose(0, 2, 1)[:, :, 1].mean(axis=0)
    np.testing.assert_allclose(level @ (up / np.linalg.norm(up)), [0, 1, 0], atol=1e-9)
