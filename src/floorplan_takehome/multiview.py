"""Photo and video tiers: images in, metric point cloud out.

Backbone: VGGT-1B through the low-VRAM fork (relative scale, camera-from-world
OpenCV extrinsics). Scale and world frame come from a similarity transform that
maps VGGT's camera centres onto known camera positions for the same images, the
ARCore poses recorded by the capture page. Without known poses the cloud is
returned as is, in VGGT's relative frame.
"""

import os
from pathlib import Path

import numpy as np
import open3d as o3d

os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")  # no Python headers here, see plan.md


def umeyama(src: np.ndarray, dst: np.ndarray) -> tuple[float, np.ndarray, np.ndarray]:
    """Similarity transform (scale, rotation, translation) with dst ~ s * R @ src + t."""
    if len(src) < 3:
        raise ValueError("need at least 3 point pairs for a similarity transform")
    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    src_c, dst_c = src - mu_s, dst - mu_d
    cov = dst_c.T @ src_c / len(src)
    u, sing, vt = np.linalg.svd(cov)
    sign = np.eye(3)
    if np.linalg.det(u) * np.linalg.det(vt) < 0:
        sign[2, 2] = -1
    rotation = u @ sign @ vt
    var_src = (src_c**2).sum() / len(src)
    scale = float((sing * np.diag(sign)).sum() / var_src)
    translation = mu_d - scale * rotation @ mu_s
    return scale, rotation, translation


# WebXR/ARCore cameras look down -z with y up, OpenCV cameras look down +z with y down.
_GL_TO_CV = np.diag([1.0, -1.0, -1.0])


def align_cameras(extrinsic: np.ndarray, known: dict[int, np.ndarray]) -> tuple[float, np.ndarray, np.ndarray, dict]:
    """Similarity transform from VGGT world to the known cameras' world.

    Rotation comes from the camera orientations (Procrustes over all pairs),
    scale from pairwise camera distances (median ratio), translation from the
    centres. This stays stable when the cameras sit close together, where a
    fit on centres alone does not. known maps image index to a 4x4 camera-to-world
    matrix in WebXR convention.
    """
    idx = sorted(known)
    if len(idx) < 3:
        raise ValueError("need at least 3 known cameras")
    r_cv = extrinsic[idx, :, :3]  # camera-from-world, OpenCV
    src_c2w = np.transpose(r_cv, (0, 2, 1))  # world-from-camera in VGGT world
    dst_c2w = np.array([known[i][:3, :3] @ _GL_TO_CV for i in idx])  # world-from-camera, OpenCV axes

    # rotation R with dst_c2w_i ~ R @ src_c2w_i for all i
    m = sum(d @ s.T for s, d in zip(src_c2w, dst_c2w))
    u, _, vt = np.linalg.svd(m)
    sign = np.diag([1.0, 1.0, np.sign(np.linalg.det(u @ vt))])
    rotation = u @ sign @ vt

    src_c = camera_centers_from_extrinsics(extrinsic[idx])
    dst_c = np.array([known[i][:3, 3] for i in idx])
    ratios = []
    for a in range(len(idx)):
        for b in range(a + 1, len(idx)):
            ds = np.linalg.norm(src_c[a] - src_c[b])
            if ds > 1e-6:
                ratios.append(np.linalg.norm(dst_c[a] - dst_c[b]) / ds)
    scale = float(np.median(ratios))
    translation = dst_c.mean(axis=0) - scale * rotation @ src_c.mean(axis=0)

    aligned = apply_similarity(src_c, scale, rotation, translation)
    pos_residual = np.linalg.norm(aligned - dst_c, axis=1)
    rot_residual = [
        np.degrees(np.arccos(np.clip((np.trace((rotation @ s).T @ d) - 1) / 2, -1, 1)))
        for s, d in zip(src_c2w, dst_c2w)
    ]
    info = {
        "scale": round(scale, 4),
        "aligned_cameras": len(idx),
        "camera_residual_cm_median": round(float(np.median(pos_residual)) * 100, 1),
        "camera_residual_cm_max": round(float(pos_residual.max()) * 100, 1),
        "rotation_residual_deg_median": round(float(np.median(rot_residual)), 1),
        "rotation_residual_deg_max": round(float(np.max(rot_residual)), 1),
    }
    return scale, rotation, translation, info


def apply_similarity(points: np.ndarray, scale: float, rotation: np.ndarray, translation: np.ndarray) -> np.ndarray:
    return scale * points @ rotation.T + translation


def camera_centers_from_extrinsics(extrinsic: np.ndarray) -> np.ndarray:
    """OpenCV camera-from-world [R | t] (S, 3, 4) to world-space camera centres (S, 3)."""
    rot = extrinsic[:, :, :3]
    trans = extrinsic[:, :, 3]
    return -np.einsum("sij,si->sj", rot, trans)


def run_vggt(image_paths: list[str], cache: Path | None = None) -> dict:
    """Run VGGT once over all images. Returns world points, confidence, extrinsics.

    With cache set, the raw output is stored there as npz and reused on the next
    call with the same image list.
    """
    if cache and cache.exists():
        data = np.load(cache, allow_pickle=True)
        if list(data["paths"]) == list(image_paths):
            return {k: data[k] for k in ("points", "conf", "extrinsic", "intrinsic")} | {"peak_vram_gb": float(data["peak_vram_gb"])}
    import torch
    from vggt.models.vggt import VGGT
    from vggt.utils.load_fn import load_and_preprocess_images
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    torch.backends.cuda.enable_cudnn_sdp(False)  # Blackwell, see plan.md
    dtype = torch.bfloat16
    device = "cuda"
    model = VGGT.from_pretrained("facebook/VGGT-1B").to(device).to(dtype).eval()
    images = load_and_preprocess_images(image_paths, mode="pad").to(device).to(dtype)  # keep floor and ceiling of portrait frames

    with torch.no_grad():
        predictions = model(images)
        extrinsic, intrinsic = pose_encoding_to_extri_intri(predictions["pose_enc"], images.shape[-2:])

    out = {
        "points": predictions["world_points"][0].float().cpu().numpy(),  # (S, H, W, 3)
        "conf": predictions["world_points_conf"][0].float().cpu().numpy(),  # (S, H, W)
        "extrinsic": extrinsic[0].float().cpu().numpy(),
        "intrinsic": intrinsic[0].float().cpu().numpy(),
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2),
    }
    del model, images, predictions
    torch.cuda.empty_cache()
    if cache:
        np.savez_compressed(cache, paths=np.array(image_paths), **out)
    return out


def reconstruct_images(
    image_paths: list[str],
    known_poses: dict[int, np.ndarray] | None = None,
    conf_percentile: float = 30.0,
    cache: Path | None = None,
) -> tuple[o3d.geometry.PointCloud, np.ndarray, dict]:
    """Images to a point cloud plus camera centres.

    known_poses maps an index into image_paths to that camera's 4x4 camera-to-world
    matrix (WebXR convention, metric). With 3 or more, the output is metric and in
    that world frame.
    """
    out = run_vggt(image_paths, cache)
    centers = camera_centers_from_extrinsics(out["extrinsic"])
    keep = out["conf"] >= np.percentile(out["conf"], conf_percentile)
    points = out["points"][keep]

    info = {"images": len(image_paths), "peak_vram_gb": out["peak_vram_gb"], "points": int(len(points))}
    if known_poses and len(known_poses) >= 3:
        scale, rotation, translation, fit = align_cameras(out["extrinsic"], known_poses)
        points = apply_similarity(points, scale, rotation, translation)
        centers = apply_similarity(centers, scale, rotation, translation)
        info.update(fit)
    else:
        info["scale"] = None

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points.astype(np.float64))
    return cloud, centers, info


def photo_paths_and_poses(capture_dir: Path) -> tuple[list[str], dict[int, np.ndarray]]:
    """Photos saved by the capture page, with the ARCore camera-to-world matrix of each."""
    import json

    data = json.loads((capture_dir / "capture.json").read_text())
    paths, centers = [], {}
    for record in data["captures"]:
        photo = record.get("photo")
        if not photo or not (capture_dir / photo).exists():
            continue
        m = np.array(record["views"][0]["transform_matrix"], dtype=float).reshape(4, 4, order="F")
        centers[len(paths)] = m
        paths.append(str(capture_dir / photo))
    return paths, centers


def video_frame_paths(capture_dir: Path, fps: float = 1.0) -> list[str]:
    """Extract frames from video.webm with ffmpeg (once) and return their paths."""
    import subprocess

    frames_dir = capture_dir / "frames"
    video = next((p for p in capture_dir.glob("video.*")), None)
    if video is None:
        return []
    if not frames_dir.exists() or not any(frames_dir.glob("*.jpg")):
        frames_dir.mkdir(exist_ok=True)
        # ffmpeg applies the container rotation tag, so portrait phone video comes out upright
        result = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vf", f"fps={fps}", "-q:v", "2", str(frames_dir / "%04d.jpg")],
            capture_output=True,
        )
        if result.returncode != 0:
            return []
    return sorted(str(p) for p in frames_dir.glob("*.jpg"))


def depth_scale_check(capture_dir: Path, image_paths: list[str], cache: Path, conf_percentile: float = 70.0) -> dict | None:
    """Ratio of ARCore depth to VGGT depth, pixel by pixel, on photos that have both.

    An independent estimate of the metric scale to compare with the pose-based
    one. A large spread between frames means one of the two depth sources is not
    self-consistent.
    """
    import json

    from floorplan_takehome.depth_capture import _depth_in_view_coords

    data = json.loads((capture_dir / "capture.json").read_text())
    by_photo = {r["photo"]: r for r in data["captures"] if r.get("photo")}
    z = np.load(cache, allow_pickle=True)
    pts, conf, ext = z["points"], z["conf"], z["extrinsic"]
    _, h, w, _ = pts.shape

    per_frame = []
    for i, path in enumerate(image_paths):
        record = by_photo.get(str(Path(path).relative_to(capture_dir)))
        if not record or not record["views"][0].get("depth_buffer"):
            continue
        ph_w, ph_h = record["photo_size"]
        # pad mode: the long side becomes 518, the short side is scaled and centred with padding
        if ph_h >= ph_w:
            img_w = round(ph_w * h / ph_h / 14) * 14
            x0 = (w - img_w) // 2
            arcore = np.full((h, w), np.nan)
            arcore[:, x0 : x0 + img_w] = _depth_in_view_coords(record["views"][0], img_w, h)
        else:
            img_h = round(ph_h * w / ph_w / 14) * 14
            y0 = (h - img_h) // 2
            arcore = np.full((h, w), np.nan)
            arcore[y0 : y0 + img_h, :] = _depth_in_view_coords(record["views"][0], w, img_h)
        rot, t = ext[i, :, :3], ext[i, :, 3]
        vggt = (pts[i].reshape(-1, 3) @ rot.T + t)[:, 2].reshape(h, w)
        good = np.isfinite(arcore) & (arcore > 0.3) & (arcore < 5) & (vggt > 1e-3) & (conf[i] >= np.percentile(conf[i], conf_percentile))
        if good.sum() < 100:
            continue
        per_frame.append(float(np.median(arcore[good] / vggt[good])))
    if not per_frame:
        return None
    return {
        "depth_based_scale": round(float(np.median(per_frame)), 3),
        "depth_based_scale_min": round(min(per_frame), 3),
        "depth_based_scale_max": round(max(per_frame), 3),
        "frames": len(per_frame),
    }


def horizontal_frames(known_poses: dict[int, np.ndarray], max_pitch_deg: float = 50.0) -> list[int]:
    """Indices whose viewing direction is within max_pitch_deg of horizontal (WebXR poses, look = -z)."""
    keep = []
    for i, m in known_poses.items():
        look = -m[:3, 2]
        pitch = np.degrees(np.arcsin(np.clip(look[1], -1, 1)))
        if abs(pitch) <= max_pitch_deg:
            keep.append(i)
    return sorted(keep)


def reconstruct_video_chunked(
    image_paths: list[str],
    known_poses: dict[int, np.ndarray],
    chunk: int = 16,
    overlap: int = 4,
    conf_percentile: float = 30.0,
    cache_dir: Path | None = None,
) -> tuple[o3d.geometry.PointCloud, np.ndarray, dict]:
    """Long walks in overlapping chunks of consecutive frames, each chunk aligned to its
    own known poses, merged in the world frame. A feed-forward model holds a room, not
    a whole apartment, and known poses make every chunk independently metric.
    """
    idx = horizontal_frames(known_poses)
    if len(idx) < 3:
        idx = sorted(known_poses)
    starts = list(range(0, max(1, len(idx) - overlap), max(1, chunk - overlap)))
    clouds, centers, fits = [], [], []
    peak = 0.0
    for c, s in enumerate(starts):
        sel = idx[s : s + chunk]
        if len(sel) < 3:
            continue
        paths = [image_paths[i] for i in sel]
        poses = {k: known_poses[i] for k, i in enumerate(sel)}
        cache = (cache_dir / f"chunk_{c:03d}.npz") if cache_dir else None
        out = run_vggt(paths, cache)
        peak = max(peak, out["peak_vram_gb"])
        scale, rotation, translation, fit = align_cameras(out["extrinsic"], poses)
        keep = out["conf"] >= np.percentile(out["conf"], conf_percentile)
        pts = apply_similarity(out["points"][keep], scale, rotation, translation)
        clouds.append(pts.astype(np.float64))
        centers.append(apply_similarity(camera_centers_from_extrinsics(out["extrinsic"]), scale, rotation, translation))
        fits.append(fit)
    if not clouds:
        raise ValueError("no chunk could be reconstructed")
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.concatenate(clouds))
    info = {
        "images": len(idx),
        "chunks": len(fits),
        "chunk_size": chunk,
        "peak_vram_gb": round(peak, 2),
        "points": int(sum(len(c) for c in clouds)),
        "scale": round(float(np.median([f["scale"] for f in fits])), 4),
        "camera_residual_cm_median": round(float(np.median([f["camera_residual_cm_median"] for f in fits])), 1),
        "rotation_residual_deg_median": round(float(np.median([f["rotation_residual_deg_median"] for f in fits])), 1),
        "worst_chunk_rotation_deg": round(float(max(f["rotation_residual_deg_median"] for f in fits)), 1),
    }
    return cloud, np.concatenate(centers), info
