import numpy as np

from floorplan_takehome.drift import apply_drift_correction, estimate_yaw_drift, footprint_metrics, rotate_pose_yaw


def _room_walls(rng, n=3000):
    pts = []
    for (xa, xb, za, zb) in ((0, 0, 0, 4), (5, 5, 0, 4), (0, 5, 0, 0), (0, 5, 4, 4)):
        xs = rng.uniform(xa, xb, n) if xa != xb else np.full(n, xa)
        zs = rng.uniform(za, zb, n) if za != zb else np.full(n, za)
        pts.append(np.stack([xs, rng.uniform(0.1, 2.5, n), zs], axis=1))
    return np.concatenate(pts)


def test_yaw_drift_rate_is_recovered_from_rotating_windows():
    rng = np.random.default_rng(0)
    walls = _room_walls(rng)
    windows = []
    for k in range(6):
        frame = k * 300 + 150
        deg = 0.02 * frame  # 1.2 degrees per second at 60 fps
        m = rotate_pose_yaw(np.eye(4), deg)
        windows.append((frame, walls @ m[:3, :3].T))
    est = estimate_yaw_drift(windows, floor_y=0.0)
    assert est is not None
    assert abs(est.rate_deg_per_min - 0.02 * 60 * 60) < 5.0  # 72 deg/min, within 5


def test_correction_undoes_the_rotation():
    est_frames = [0, 300, 600]
    from floorplan_takehome.drift import DriftEstimate

    est = DriftEstimate(window_frames=est_frames, deviation_deg=[0, 3, 6], rate_deg_per_min=36.0, fit_deg=[0, 3, 6], fps=60)
    pose = rotate_pose_yaw(np.eye(4), 6.0)
    fixed = apply_drift_correction({"000600": pose}, est)["000600"]
    np.testing.assert_allclose(fixed[:3, :3], np.eye(3), atol=1e-9)


def test_footprint_thickness_grows_when_walls_are_smeared():
    rng = np.random.default_rng(1)
    walls = _room_walls(rng)
    crisp = footprint_metrics(walls, floor_y=0.0)
    smeared = footprint_metrics(np.concatenate([walls, walls @ rotate_pose_yaw(np.eye(4), 3.0)[:3, :3].T]), floor_y=0.0)
    assert smeared["mean_wall_thickness_cm"] > crisp["mean_wall_thickness_cm"]
