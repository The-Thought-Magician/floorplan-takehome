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


_VGGT = None


def load_vggt():
    """The 1B model, loaded once per process (5 GB, several seconds from disk)."""
    global _VGGT
    if _VGGT is None:
        import torch
        from vggt.models.vggt import VGGT

        torch.backends.cuda.enable_cudnn_sdp(False)  # Blackwell, see plan.md
        _VGGT = VGGT.from_pretrained("facebook/VGGT-1B").to("cuda").to(torch.bfloat16).eval()
    return _VGGT


def release_vggt():
    global _VGGT
    if _VGGT is not None:
        import torch

        _VGGT = None
        torch.cuda.empty_cache()


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
    from vggt.utils.load_fn import load_and_preprocess_images
    from vggt.utils.pose_enc import pose_encoding_to_extri_intri

    dtype = torch.bfloat16
    device = "cuda"
    model = load_vggt()
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
    del images, predictions
    torch.cuda.empty_cache()
    if cache:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, paths=np.array(image_paths), **out)
    return out


def reconstruct_images(
    image_paths: list[str],
    known_poses: dict[int, np.ndarray] | None = None,
    conf_percentile: float = 30.0,
    cache: Path | None = None,
    fov_x: dict[int, float] | None = None,
    release_model: bool = True,
) -> tuple[o3d.geometry.PointCloud, np.ndarray, dict]:
    """Images to a point cloud plus camera centres.

    known_poses maps an index into image_paths to that camera's 4x4 camera-to-world
    matrix (WebXR convention, metric). With 3 or more, the output is metric and in
    that world frame.
    """
    out = run_vggt(image_paths, cache)
    if release_model:
        release_vggt()
    centers = camera_centers_from_extrinsics(out["extrinsic"])
    keep = out["conf"] >= np.percentile(out["conf"], conf_percentile)
    points = out["points"][keep]

    info = {"images": len(image_paths), "peak_vram_gb": out["peak_vram_gb"], "points": len(points)}
    if known_poses and len(known_poses) >= 3:
        scale, rotation, translation, fit = align_cameras(out["extrinsic"], known_poses)
        info.update(fit)
        fov = dict(fov_x or {}) or {i: f for i, p in enumerate(image_paths) if (f := fov_x_from_exif(p))}
        marker = marker_scale(image_paths, out)
        if marker:
            moge, mfit = marker
            pivot = camera_centers_from_extrinsics(out["extrinsic"]).mean(axis=0)
            translation = translation + (scale - moge) * (rotation @ pivot)
            info.update({"pose_scale": round(scale, 4), "scale": round(moge, 4), "scale_used": "printed_marker", **mfit})
            scale = moge
        elif fov:
            # Poses give orientation and placement. Scale from a pose fit is only as good as the
            # baseline (40 percent off on a rotate-in-place capture); MoGe-2 with the true field of
            # view measured within 3 percent of the tape, so it sets the scale when the FOV is known.
            moge, mfit = moge_scale(image_paths, out, fov)
            pivot = camera_centers_from_extrinsics(out["extrinsic"]).mean(axis=0)
            translation = translation + (scale - moge) * (rotation @ pivot)  # keep the camera centroid fixed
            info.update({"pose_scale": round(scale, 4), "scale": round(moge, 4), "scale_used": "moge2_with_fov", **mfit})
            scale = moge
        points = apply_similarity(points, scale, rotation, translation)
        centers = apply_similarity(centers, scale, rotation, translation)
    else:
        # no poses: monocular metric depth is the only scale source. Gravity is
        # unknown too, so the cloud is levelled by its dominant floor plane later.
        fov = {i: f for i, p in enumerate(image_paths) if (f := fov_x_from_exif(p))}
        marker = marker_scale(image_paths, out)
        if marker:
            scale, fit = marker
            fit["scale_used"] = "printed_marker"
        else:
            scale, fit = moge_scale(image_paths, out, fov)
            fit["scale_used"] = "moge2"
        level = level_by_camera_up(out["extrinsic"])
        pivot = centers.mean(axis=0)
        points = (points - pivot) @ level.T * scale
        centers = (centers - pivot) @ level.T * scale
        info.update({"scale": round(scale, 4), "levelled_by": "camera_up", "fov_from_exif": len(fov), **fit})

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points.astype(np.float64))
    return cloud, centers, info


def photo_records(capture_dir: Path) -> list[tuple[str, dict]]:
    """(photo path, view record) for every photo the capture page saved."""
    import json

    capture_dir = Path(capture_dir)
    data = json.loads((capture_dir / "capture.json").read_text())
    out = []
    for record in data.get("captures", []):
        photo = record.get("photo")
        if photo and (capture_dir / photo).exists():
            out.append((str(capture_dir / photo), record["views"][0]))
    return out


def photo_paths_and_poses(capture_dir: Path) -> tuple[list[str], dict[int, np.ndarray]]:
    """Photos saved by the capture page, with the ARCore camera-to-world matrix of each."""
    paths, poses = [], {}
    for path, view in photo_records(capture_dir):
        poses[len(paths)] = np.array(view["transform_matrix"], dtype=float).reshape(4, 4, order="F")
        paths.append(path)
    return paths, poses


def photo_fov_x(capture_dir: Path) -> dict[int, float]:
    """Horizontal field of view per photo from the capture page's projection matrix."""
    fov = {}
    for i, (_, view) in enumerate(photo_records(capture_dir)):
        proj = np.array(view["projection_matrix"], dtype=float).reshape(4, 4, order="F")
        fov[i] = float(np.degrees(2 * np.arctan(1 / proj[0, 0])))
    return fov


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
            check=False,
        )
        if result.returncode != 0:
            import logging

            logging.getLogger("floorplan").warning("ffmpeg failed on %s: %s", video.name, result.stderr.decode(errors="replace")[-300:])
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
    by_photo = {r["photo"]: r for r in data.get("captures", []) if r.get("photo")}
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
    release_vggt()
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


def photo_folders_from_rooms(rooms: list[dict], paths: list[str], known: dict[int, np.ndarray], per_room: int = 8) -> dict[str, tuple[list[str], dict[int, np.ndarray]]]:
    """Group frames into per-room photo sets by camera position inside each room polygon,
    keeping per_room horizontal, time-spread frames. Emulates per-room photo folders."""
    import cv2

    horizontal = set(horizontal_frames(known))
    folders = {}
    for room in rooms:
        poly = np.array(room["polygon_cm"], dtype=np.float32) / 100.0
        if len(poly) < 3:
            continue
        inside = [
            i for i in sorted(known)
            if i in horizontal and cv2.pointPolygonTest(poly.reshape(-1, 1, 2), (float(known[i][0, 3]), float(known[i][2, 3])), False) >= 0
        ]
        if len(inside) < 2:
            continue
        pick = [inside[round(k)] for k in np.linspace(0, len(inside) - 1, min(per_room, len(inside)))]
        pick = sorted(set(pick))
        folders[room["id"]] = ([paths[i] for i in pick], {k: known[i] for k, i in enumerate(pick)})
    return folders


def reconstruct_photo_folders(folders: dict[str, tuple[list[str], dict[int, np.ndarray]]], conf_percentile: float = 30.0,
                              cache_dir: Path | None = None) -> tuple[o3d.geometry.PointCloud, np.ndarray, dict]:
    """One reconstruction per room folder, each placed by its own known poses, merged."""
    clouds, centers, per_room = [], [], {}
    peak = 0.0
    for room_id, (paths, poses) in folders.items():
        cache = (cache_dir / f"{room_id}.npz") if cache_dir else None
        out = run_vggt(paths, cache)
        peak = max(peak, out["peak_vram_gb"])
        keep = out["conf"] >= np.percentile(out["conf"], conf_percentile)
        pts = out["points"][keep]
        cams = camera_centers_from_extrinsics(out["extrinsic"])
        if len(poses) >= 3:
            scale, rotation, translation, fit = align_cameras(out["extrinsic"], poses)
            pts = apply_similarity(pts, scale, rotation, translation)
            cams = apply_similarity(cams, scale, rotation, translation)
            per_room[room_id] = {"images": len(paths), **fit}
        else:
            per_room[room_id] = {"images": len(paths), "scale": None}
        clouds.append(pts.astype(np.float64))
        centers.append(cams)
    release_vggt()
    if not clouds:
        raise ValueError("no room had enough photos")
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(np.concatenate(clouds))
    fits = [v for v in per_room.values() if v.get("scale")]
    info = {
        "images": sum(v["images"] for v in per_room.values()),
        "rooms_reconstructed": len(per_room),
        "peak_vram_gb": round(peak, 2),
        "points": int(sum(len(c) for c in clouds)),
        "scale": round(float(np.median([f["scale"] for f in fits])), 4) if fits else None,
        "camera_residual_cm_median": round(float(np.median([f["camera_residual_cm_median"] for f in fits])), 1) if fits else None,
        "rotation_residual_deg_median": round(float(np.median([f["rotation_residual_deg_median"] for f in fits])), 1) if fits else None,
        "per_room": per_room,
    }
    return cloud, np.concatenate(centers), info


def fov_x_from_exif(path: str) -> float | None:
    """Horizontal field of view in degrees from the 35mm-equivalent focal length, if present."""
    try:
        from PIL import Image
        from PIL.ExifTags import Base

        with Image.open(path) as im:
            exif = im.getexif()
            f35 = exif.get(Base.FocalLengthIn35mmFilm)
            w, h = im.size
    except Exception:  # noqa: BLE001, any unreadable EXIF means no FOV
        return None
    if not f35:
        return None
    sensor_side = 36.0 if w >= h else 24.0  # width of the image on a 35mm frame
    return float(np.degrees(2 * np.arctan(sensor_side / (2 * float(f35)))))


def level_by_camera_up(extrinsic: np.ndarray) -> np.ndarray:
    """Rotation that makes world y point up, from the cameras' own up axes.

    Without poses the VGGT world is the first camera's frame. Phones are held upright,
    so the mean of the cameras' up axes (minus the OpenCV y column of camera-to-world)
    is the best available gravity estimate; pitch on individual frames averages out.
    """
    ups = -np.transpose(extrinsic[:, :, :3], (0, 2, 1))[:, :, 1]  # world-from-camera columns
    up = ups.mean(axis=0)
    up /= np.linalg.norm(up) + 1e-9
    target = np.array([0.0, 1.0, 0.0])
    v = np.cross(up, target)
    c = float(up @ target)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else np.diag([1.0, -1.0, -1.0])
    vx = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + vx + vx @ vx * (1 / (1 + c))


def aggregate_frame_scales(per_frame: list[tuple[float, float]]) -> tuple[float, dict]:
    """per_frame: (scale ratio, median metric depth). Frames that see a whole wall (the
    farther half by depth) are where a monocular metric model and a view model agree
    best, so the anchor is the median over that half. Both numbers are returned."""
    ratios = np.array([r for r, _ in per_frame])
    depths = np.array([d for _, d in per_frame])
    far = ratios[depths >= np.median(depths)] if len(per_frame) >= 4 else ratios
    return float(np.median(far)), {
        "moge_scale_all_frames": round(float(np.median(ratios)), 4),
        "moge_scale_far_frames": round(float(np.median(far)), 4),
        "moge_scale_min": round(float(ratios.min()), 4),
        "moge_scale_max": round(float(ratios.max()), 4),
        "moge_frames": len(ratios),
    }


def moge_scale(image_paths: list[str], out: dict, fov_x: dict[int, float] | None = None,
               conf_percentile: float = 70.0, max_frames: int = 12) -> tuple[float, dict]:
    """Metric scale for a VGGT reconstruction from MoGe-2 monocular metric depth.

    For each image the ratio of MoGe depth to VGGT depth is taken pixel by pixel on
    the confident pixels; the frame ratio is the median. fov_x (degrees per image
    index) sharpens MoGe's metric estimate when known.
    """
    import cv2
    import torch
    from moge.model.v2 import MoGeModel

    pts, conf, ext = out["points"], out["conf"], out["extrinsic"]
    s, h, w, _ = pts.shape
    pick = list(range(s)) if s <= max_frames else [round(k) for k in np.linspace(0, s - 1, max_frames)]
    model = MoGeModel.from_pretrained("Ruicheng/moge-2-vitl").to("cuda").eval()
    per_frame = []
    for i in pick:
        img = cv2.cvtColor(cv2.imread(image_paths[i]), cv2.COLOR_BGR2RGB)
        ph_h, ph_w = img.shape[:2]
        x = torch.tensor(img / 255, dtype=torch.float32, device="cuda").permute(2, 0, 1)
        with torch.no_grad():
            fov = (fov_x or {}).get(i)
            res = model.infer(x, fov_x=fov) if fov else model.infer(x)
        depth = res["depth"].cpu().numpy()
        mask = res["mask"].cpu().numpy()
        # VGGT pad mode: the long side is 518, the short side scaled and centred
        if ph_h >= ph_w:
            img_w = round(ph_w * h / ph_h / 14) * 14
            x0 = (w - img_w) // 2
            sl = (slice(None), slice(x0, x0 + img_w))
            size = (img_w, h)
        else:
            img_h = round(ph_h * w / ph_w / 14) * 14
            y0 = (h - img_h) // 2
            sl = (slice(y0, y0 + img_h), slice(None))
            size = (w, img_h)
        rot, t = ext[i, :, :3], ext[i, :, 3]
        vg = (pts[i].reshape(-1, 3) @ rot.T + t)[:, 2].reshape(h, w)[sl]
        cf = conf[i][sl]
        mg = cv2.resize(depth, size, interpolation=cv2.INTER_NEAREST)
        mk = cv2.resize(mask.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST).astype(bool)
        good = mk & (vg > 1e-3) & (cf >= np.percentile(cf, conf_percentile)) & (mg > 0.1)
        if good.sum() < 200:
            continue
        per_frame.append((float(np.median(mg[good] / vg[good])), float(np.median(mg[good]))))
    del model
    torch.cuda.empty_cache()
    if not per_frame:
        raise ValueError("MoGe found no usable overlap with the VGGT depth")
    return aggregate_frame_scales(per_frame)


MARKER_SIDE_M = 0.150  # docs/scale-marker-a4.png printed at 100 percent
MARKER_ID = 7


def marker_scale(image_paths: list[str], out: dict, side_m: float = MARKER_SIDE_M, marker_id: int = MARKER_ID) -> tuple[float, dict] | None:
    """Metric scale from a printed ArUco marker of known size seen in the images.

    The marker's four corners are read off VGGT's world point map at their pixel
    positions; the ratio of the known side to the reconstructed side is the scale.
    Median over every sighting. Returns None when no image shows the marker. A
    physical reference is the only route below 1 percent, see docs/plan.md.
    """
    import cv2

    detector = cv2.aruco.ArucoDetector(cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50), cv2.aruco.DetectorParameters())
    pts = out["points"]
    _, h, w, _ = pts.shape
    ratios = []
    for i, path in enumerate(image_paths):
        img = cv2.imread(path)
        if img is None:
            continue
        corners, ids, _ = detector.detectMarkers(img)
        if ids is None or marker_id not in ids.ravel():
            continue
        quad = corners[list(ids.ravel()).index(marker_id)][0]  # (4, 2) pixels in the photo
        ph_h, ph_w = img.shape[:2]
        # photo pixel -> VGGT pad-mode grid pixel (long side 518, short side centred)
        if ph_h >= ph_w:
            img_w = round(ph_w * h / ph_h / 14) * 14
            gx = quad[:, 0] / ph_w * img_w + (w - img_w) / 2
            gy = quad[:, 1] / ph_h * h
        else:
            img_h = round(ph_h * w / ph_w / 14) * 14
            gx = quad[:, 0] / ph_w * w
            gy = quad[:, 1] / ph_h * img_h + (h - img_h) / 2
        gi = np.clip(np.round(gy).astype(int), 0, h - 1)
        gj = np.clip(np.round(gx).astype(int), 0, w - 1)
        world = pts[i][gi, gj]
        sides = [np.linalg.norm(world[k] - world[(k + 1) % 4]) for k in range(4)]
        if min(sides) <= 1e-6:
            continue
        ratios.append(side_m / float(np.median(sides)))
    if not ratios:
        return None
    return float(np.median(ratios)), {"marker_sightings": len(ratios), "marker_scale_min": round(min(ratios), 4), "marker_scale_max": round(max(ratios), 4)}
