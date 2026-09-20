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
    scan = Path(scan)
    """frame id -> 4x4 camera-to-world matrix."""
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
    if depth is None:
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


def load_point_cloud(scan: Path, max_frames: int | None = None, min_confidence: int = 2,
                     pixel_stride: int = 1, voxel_m: float = 0.02, chunk: int = 150) -> tuple[o3d.geometry.PointCloud, np.ndarray]:
    """Fuse depth frames into one world-frame cloud. Returns (cloud, camera positions).

    Every frame is used unless max_frames caps it. Frames are voxel-downsampled per
    frame and the running cloud is downsampled every `chunk` frames to bound memory.
    """
    scan = Path(scan)
    intrinsics = load_intrinsics(scan)
    poses = load_odometry(scan)
    frames = sorted(p.stem for p in (scan / "depth").glob("*.png") if p.stem in poses)
    if max_frames:
        frames = frames[:: max(1, len(frames) // max_frames)]

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


def video_frames_with_poses(scan: Path, out_dir: Path, every: int = 60) -> tuple[list[str], dict[int, np.ndarray]]:
    """Extract every Nth frame of rgb.mp4 (frame i of the video is odometry frame i)."""
    import subprocess

    scan, out_dir = Path(scan), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not any(out_dir.glob("*.jpg")):
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(scan / "rgb.mp4"), "-vf", f"select=not(mod(n\\,{every}))",
             "-vsync", "vfr", "-q:v", "2", str(out_dir / "%05d.jpg")],
            check=True,
        )
    poses = poses_webxr(load_odometry(scan))
    paths, known = [], {}
    for k, jpg in enumerate(sorted(out_dir.glob("*.jpg"))):
        frame = f"{(int(jpg.stem) - 1) * every:06d}"
        if frame in poses:
            known[len(paths)] = poses[frame]
            paths.append(str(jpg))
    return paths, known
