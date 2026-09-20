"""Stray Scanner (iOS LiDAR logging app) export to point cloud.

Layout of one scan directory:
  rgb.mp4                 1920x1440 HEVC, one frame per depth frame
  camera_matrix.csv       3x3 intrinsics for the RGB frame
  odometry.csv            timestamp, frame, x, y, z, qx, qy, qz, qw, ... (ARKit camera-to-world)
  depth/NNNNNN.png        256x192 uint16, millimetres
  confidence/NNNNNN.png   256x192 uint8, ARKit confidence 0 (low) to 2 (high)

Odometry poses are camera-to-world in the OpenCV camera convention (x right, y down,
camera looks down +z), verified empirically: it is the only axis assignment that yields
vertical walls and a floor below the camera. World is y-up.
"""

import csv
from pathlib import Path

import cv2
import numpy as np
import open3d as o3d
from scipy.spatial.transform import Rotation


def is_stray_scan(path: Path) -> bool:
    path = Path(path)
    return (path / "odometry.csv").exists() and (path / "depth").is_dir()


def find_scan_dir(root: Path) -> Path | None:
    """The scan directory itself, or the single scan directory nested under root."""
    root = Path(root)
    if is_stray_scan(root):
        return root
    candidates = [p for p in root.rglob("odometry.csv") if is_stray_scan(p.parent)]
    return candidates[0].parent if len(candidates) == 1 else None


def load_intrinsics(scan: Path) -> np.ndarray:
    scan = Path(scan)
    rows = [[float(v) for v in line.split(",")] for line in (scan / "camera_matrix.csv").read_text().strip().splitlines()]
    return np.array(rows)


def load_odometry(scan: Path) -> dict[str, np.ndarray]:
    """frame id -> 4x4 camera-to-world matrix."""
    scan = Path(scan)
    poses = {}
    with open(scan / "odometry.csv") as f:
        reader = csv.reader(f)
        header = [h.strip() for h in next(reader)]
        col = {name: i for i, name in enumerate(header)}
        for row in reader:
            if not row or not row[0].strip():
                continue
            frame = row[col["frame"]].strip()
            t = np.array([float(row[col[k]]) for k in ("x", "y", "z")])
            q = np.array([float(row[col[k]]) for k in ("qx", "qy", "qz", "qw")])
            m = np.eye(4)
            m[:3, :3] = Rotation.from_quat(q).as_matrix()
            m[:3, 3] = t
            poses[frame] = m
    return poses


def frame_to_points(depth_png: Path, conf_png: Path | None, intrinsics: np.ndarray,
                    min_confidence: int = 2, pixel_stride: int = 2, max_range_m: float = 6.0) -> np.ndarray:
    """Unproject one depth frame into camera coordinates (n, 3)."""
    depth = cv2.imread(str(depth_png), cv2.IMREAD_UNCHANGED)
    if depth is None or depth.ndim != 2 or intrinsics[0, 2] <= 0:
        return np.empty((0, 3))
    h, w = depth.shape
    valid = depth > 0
    if conf_png is not None and conf_png.exists():
        conf = cv2.imread(str(conf_png), cv2.IMREAD_UNCHANGED)
        if conf is not None and conf.shape == depth.shape:
            valid &= conf >= min_confidence

    # intrinsics are for the RGB resolution, the depth map is a scaled copy of the same view
    fx, fy = intrinsics[0, 0], intrinsics[1, 1]
    cx, cy = intrinsics[0, 2], intrinsics[1, 2]
    rgb_w = cx * 2  # principal point sits near the image centre
    scale = w / rgb_w
    fx, fy, cx, cy = fx * scale, fy * scale, cx * scale, cy * scale

    vs, us = np.mgrid[0:h:pixel_stride, 0:w:pixel_stride]
    d = depth[::pixel_stride, ::pixel_stride].astype(float) / 1000.0
    keep = valid[::pixel_stride, ::pixel_stride] & (d <= max_range_m)
    us, vs, d = us[keep], vs[keep], d[keep]
    x = (us + 0.5 - cx) * d / fx
    y = (vs + 0.5 - cy) * d / fy
    z = d
    return np.stack([x, y, z], axis=1)


def window_clouds(scan: Path, window: int = 300, stride: int = 6, min_confidence: int = 2,
                  pixel_stride: int = 2) -> tuple[list[tuple[int, np.ndarray]], dict[str, np.ndarray]]:
    """Per time window, the world points of a strided subset of its frames (raw poses)."""
    scan = Path(scan)
    intrinsics = load_intrinsics(scan)
    poses = load_odometry(scan)
    frames = sorted(p.stem for p in (scan / "depth").glob("*.png") if p.stem in poses)
    out = []
    for start in range(0, len(frames), window):
        pts = []
        for frame in frames[start : start + window : stride]:
            local = frame_to_points(scan / "depth" / f"{frame}.png", scan / "confidence" / f"{frame}.png", intrinsics, min_confidence, pixel_stride)
            if len(local):
                m = poses[frame]
                pts.append(local @ m[:3, :3].T + m[:3, 3])
        if pts:
            out.append((start + min(window, len(frames) - start) // 2, np.concatenate(pts)))
    return out, poses


def load_point_cloud(scan: Path, min_confidence: int = 2, pixel_stride: int = 1, voxel_m: float = 0.02,
                     chunk: int = 150, poses: dict[str, np.ndarray] | None = None) -> tuple[o3d.geometry.PointCloud, np.ndarray]:
    """Fuse every depth frame into one world-frame cloud. Returns (cloud, camera positions).

    Frames are voxel-downsampled per frame and the running cloud is downsampled every
    `chunk` frames to bound memory. poses overrides the odometry (drift-corrected poses).
    """
    scan = Path(scan)
    intrinsics = load_intrinsics(scan)
    poses = poses if poses is not None else load_odometry(scan)
    frames = sorted(p.stem for p in (scan / "depth").glob("*.png") if p.stem in poses)

    merged = o3d.geometry.PointCloud()
    pending = o3d.geometry.PointCloud()
    cameras = []
    for i, frame in enumerate(frames):
        pts = frame_to_points(scan / "depth" / f"{frame}.png", scan / "confidence" / f"{frame}.png",
                              intrinsics, min_confidence, pixel_stride)
        m = poses[frame]
        cameras.append(m[:3, 3])
        if not len(pts):
            continue
        world = pts @ m[:3, :3].T + m[:3, 3]
        piece = o3d.geometry.PointCloud()
        piece.points = o3d.utility.Vector3dVector(world)
        pending += piece.voxel_down_sample(voxel_m)
        if (i + 1) % chunk == 0:
            merged += pending
            merged = merged.voxel_down_sample(voxel_m)
            pending = o3d.geometry.PointCloud()
    merged += pending
    return merged.voxel_down_sample(voxel_m), np.array(cameras)


_CV_TO_GL = np.diag([1.0, -1.0, -1.0, 1.0])


def poses_webxr(poses: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Same camera-to-world poses expressed with WebXR/OpenGL camera axes (x right, y up, -z forward)."""
    return {k: m @ _CV_TO_GL for k, m in poses.items()}


_ROT = {0: None, 90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}


def upright_rotation(poses_cv: dict[str, np.ndarray]) -> int:
    """Image rotation (degrees clockwise) that puts gravity down in the frames.

    The sensor frame is landscape. If the phone was held portrait, camera x points along
    gravity. Pick the in-plane rotation whose new image-down axis points down in the world.
    """
    down = np.array([0.0, -1.0, 0.0])
    best, best_score = 0, -2.0
    for deg in (0, 90, 180, 270):
        th = np.radians(deg)
        score = 0.0
        for m in list(poses_cv.values())[::50]:
            x, y = m[:3, 0], m[:3, 1]
            new_y = -np.sin(th) * x + np.cos(th) * y  # image-down axis after rotating the image clockwise by deg
            score += float(new_y @ down)
        if score > best_score:
            best, best_score = deg, score
    return best


def rotate_pose_cv(m: np.ndarray, deg: int) -> np.ndarray:
    """Camera-to-world after rotating the image clockwise by deg (OpenCV axes)."""
    # verified against VGGT on the sample scans: image rotated 270 clockwise pairs with -270
    th = -np.radians(deg)
    rz = np.array([[np.cos(th), -np.sin(th), 0], [np.sin(th), np.cos(th), 0], [0, 0, 1]])
    out = m.copy()
    out[:3, :3] = m[:3, :3] @ rz
    return out


def video_frames_with_poses(scan: Path, out_dir: Path, every: int = 60) -> tuple[list[str], dict[int, np.ndarray]]:
    """Extract every Nth frame of rgb.mp4 (frame i of the video is odometry frame i).

    Frames are rotated upright (portrait capture) and the poses adjusted to match, so a
    view model sees walls vertical.
    """
    import subprocess

    scan, out_dir = Path(scan), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    poses_cv = load_odometry(scan)
    deg = upright_rotation(poses_cv)
    marker = out_dir / f"rotation_{deg}.txt"
    if not marker.exists():
        for old in out_dir.glob("*.jpg"):
            old.unlink()
        for old in out_dir.glob("rotation_*.txt"):
            old.unlink()
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(scan / "rgb.mp4"), "-vf", f"select=not(mod(n\\,{every}))",
             "-vsync", "vfr", "-q:v", "2", str(out_dir / "%05d.jpg")],
            check=True,
        )
        if deg:
            for jpg in out_dir.glob("*.jpg"):
                cv2.imwrite(str(jpg), cv2.rotate(cv2.imread(str(jpg)), _ROT[deg]))
        marker.write_text(str(deg))
    poses = poses_webxr({k: rotate_pose_cv(m, deg) for k, m in poses_cv.items()})
    paths, known = [], {}
    for jpg in sorted(out_dir.glob("*.jpg")):
        frame = f"{(int(jpg.stem) - 1) * every:06d}"
        if frame in poses:
            known[len(paths)] = poses[frame]
            paths.append(str(jpg))
    return paths, known
