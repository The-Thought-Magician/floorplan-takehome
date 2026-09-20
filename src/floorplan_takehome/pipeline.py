"""Capture directory in, FloorPlan schema out. Shared by the CLI and the server."""

import json
from pathlib import Path

import numpy as np
import open3d as o3d

from floorplan_takehome.depth_capture import load_point_cloud
from floorplan_takehome.plane_extraction import (
    manhattan_filter,
    merge_walls,
    outer_walls,
    polygon_area,
    polygon_perimeter,
    refine_wall_faces,
    segment_planes,
    wall_polygon,
)


def clean_cloud(cloud: o3d.geometry.PointCloud, voxel_m: float = 0.03) -> o3d.geometry.PointCloud:
    cloud = cloud.voxel_down_sample(voxel_m)
    if len(cloud.points) < 50:
        return cloud
    cloud, _ = cloud.remove_statistical_outlier(nb_neighbors=20, std_ratio=2.0)
    return cloud


def _floor_and_ceiling(planes, camera_y: float | None) -> tuple[float | None, float | None]:
    """Floor is the lowest horizontal plane well below the camera, ceiling the highest well above.

    Without camera heights (synthetic clouds) fall back to lowest and highest.
    """
    heights = [float(np.median(p.points[:, 1])) for p in planes if p.is_horizontal]
    if not heights:
        return None, None
    if camera_y is None:
        return min(heights), max(heights)
    below = [h for h in heights if h < camera_y - 0.8]
    above = [h for h in heights if h > camera_y + 0.3]
    return (min(below) if below else None), (max(above) if above else None)


def camera_positions(json_path: Path) -> np.ndarray:
    data = json.loads(Path(json_path).read_text())
    positions = []
    for capture in data.get("captures", []):
        for view in capture["views"]:
            m = np.array(view["transform_matrix"], dtype=float).reshape(4, 4, order="F")
            positions.append(m[:3, 3])
    return np.array(positions) if positions else np.empty((0, 3))


WALL_FACE = "outer"  # "centre" reproduces the pre-fix behaviour (fix loop, see docs/fix-loop.md)


def reconstruct(cloud: o3d.geometry.PointCloud, source_tier: str, cameras: np.ndarray | None = None, wall_face: str | None = None) -> dict:
    o3d.utility.random.seed(0)  # RANSAC must give the same answer for the same capture
    wall_face = wall_face or WALL_FACE
    cloud = clean_cloud(cloud)
    planes = segment_planes(cloud, distance_threshold=0.04, max_planes=10, min_inliers=80)
    raw_walls = merge_walls([p for p in planes if p.is_wall])
    walls = outer_walls(manhattan_filter(raw_walls))
    face_log = []
    if wall_face == "outer":
        walls, face_log = refine_wall_faces(walls, np.asarray(cloud.points)[:, [0, 2]])
    corners = wall_polygon(walls)

    n_points = len(cloud.points)
    wall_points = sum(len(w.points) for w in walls)
    camera_y = float(np.median(cameras[:, 1])) if cameras is not None and len(cameras) else None
    floor_y, ceiling_y = _floor_and_ceiling(planes, camera_y)
    wall_height = None if floor_y is None or ceiling_y is None else ceiling_y - floor_y
    height_source = "floor_ceiling_planes" if wall_height is not None else None
    if wall_height is None and walls:
        # walls run floor to ceiling, so the vertical extent of their inliers is the room height
        tops = [np.percentile(w.points[:, 1], 99) for w in walls]
        bottoms = [np.percentile(w.points[:, 1], 1) for w in walls]
        top, bottom = float(np.median(tops)), float(np.median(bottoms))
        all_y = np.asarray(cloud.points)[:, 1]
        # the wall extent is the room height only if a ceiling layer sits at its top:
        # a horizontal layer has far more points than a 20 cm wall band just below it
        ceiling_layer = int(((all_y > top - 0.10) & (all_y < top + 0.10)).sum())
        wall_band = int(((all_y > top - 0.60) & (all_y < top - 0.40)).sum())
        if top - bottom >= 2.0 and ceiling_layer >= 1.5 * max(wall_band, 1):
            wall_height = top - bottom
            height_source = "wall_extent"
        else:
            height_source = "ceiling_not_observed"

    room = {
        "id": "room-1",
        "label": "room",
        "polygon_cm": [[round(float(c[0]) * 100, 1), round(float(c[1]) * 100, 1)] for c in corners],
        "wall_height_cm": None if wall_height is None else round(wall_height * 100, 1),
        "openings": [],
        "confidence": round(wall_points / n_points, 3) if n_points and corners else 0.0,
        "source_tier": source_tier,
    }
    if corners:
        room["area_m2"] = round(polygon_area(corners), 3)
        room["perimeter_m"] = round(polygon_perimeter(corners), 3)
        room["wall_lengths_cm"] = [
            round(float(np.linalg.norm(corners[(i + 1) % len(corners)] - corners[i])) * 100, 1)
            for i in range(len(corners))
        ]

    return {
        "rooms": [room],
        "diagnostics": {
            "points": n_points,
            "planes": len(planes),
            "tilted_planes_rejected": sum(1 for p in planes if p.is_tilted),
            "walls": len(walls),
            "walls_rejected_off_axis": len(raw_walls) - len(manhattan_filter(raw_walls)),
            "walls_rejected_interior": len(manhattan_filter(raw_walls)) - len(walls),
            "wall_face": wall_face,
            "wall_face_shifts": face_log,
            "closed": bool(corners),
            "height_source": height_source,
            "camera_height_m": None if camera_y is None or floor_y is None else round(camera_y - floor_y, 3),
            "floor_y": None if floor_y is None else round(floor_y, 3),
            "ceiling_y": None if ceiling_y is None else round(ceiling_y, 3),
            "wall_lines": [
                {"normal": [round(float(v), 4) for v in w.normal], "d": round(float(w.d), 4), "points": len(w.points)}
                for w in walls
            ],
        },
    }


def render_topdown(cloud: o3d.geometry.PointCloud, plan: dict, out_png: Path, cameras: np.ndarray | None = None) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    points = np.asarray(cloud.points)
    fig, ax = plt.subplots(figsize=(6, 6))
    if len(points):
        ax.scatter(points[:, 0], points[:, 2], s=2, c=points[:, 1], cmap="viridis", alpha=0.6)
    if cameras is not None and len(cameras):
        ax.plot(cameras[:, 0], cameras[:, 2], "k.-", linewidth=1, markersize=4, label="camera path")
        ax.legend(loc="lower right", fontsize=8)
    poly = plan["rooms"][0]["polygon_cm"]
    if poly:
        xs = [p[0] / 100 for p in poly] + [poly[0][0] / 100]
        zs = [p[1] / 100 for p in poly] + [poly[0][1] / 100]
        ax.plot(xs, zs, "r-", linewidth=2)
        for i, length in enumerate(plan["rooms"][0]["wall_lengths_cm"]):
            mx = (xs[i] + xs[i + 1]) / 2
            mz = (zs[i] + zs[i + 1]) / 2
            ax.text(mx, mz, f"{length:.0f} cm", color="red", fontsize=8, ha="center")
        ax.set_title(f"area {plan['rooms'][0]['area_m2']:.2f} m2")
    else:
        ax.set_title(f"no closed polygon (walls found: {plan['diagnostics']['walls']})")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.set_aspect("equal")
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def _tier_summary(plan: dict, info: dict) -> dict:
    rooms = plan["rooms"]
    return {
        "rooms": len(rooms),
        "closed": all(bool(r["polygon_cm"]) for r in rooms),
        "wall_lengths_cm": [r.get("wall_lengths_cm") for r in rooms],
        "area_m2": [r.get("area_m2") for r in rooms],
        "wall_height_cm": rooms[0].get("wall_height_cm") if rooms else None,
        "adjacency": plan.get("adjacency", []),
        **info,
    }


def process_image_tiers(capture_dir: Path, plan: dict) -> dict:
    """Photo tier on the saved JPEGs, video tier on frames plus photos as scale anchors.

    Both go through VGGT and are aligned to the ARCore camera positions recorded
    for the photos. Results land in plan_photos.* and plan_video.* and a summary
    in plan["tiers"]. GPU errors are recorded, not raised.
    """
    from floorplan_takehome.multiview import (
        depth_scale_check,
        photo_fov_x,
        photo_paths_and_poses,
        reconstruct_images,
        video_frame_paths,
    )

    capture_dir = Path(capture_dir)
    tiers = {}
    photos, centers = photo_paths_and_poses(capture_dir)
    fov = photo_fov_x(capture_dir)
    if not photos:  # files-only upload: any images under photos/, no poses
        photos = sorted(str(p) for p in (capture_dir / "photos").rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
        centers = {}
    frames = video_frame_paths(capture_dir)

    jobs = []
    if len(photos) >= 2:
        jobs.append(("photos", photos, centers))
    if frames and len(centers) >= 3:
        jobs.append(("video", photos + frames, centers))
    elif frames:
        jobs.append(("video", frames, {}))

    for tier, paths, known in jobs:
        try:
            cache = capture_dir / f"vggt_{tier}.npz"
            # video frames share the photos' camera, so the photos' FOV applies to every image
            fov_all = {i: (fov.get(i) if i < len(photos) else (np.median(list(fov.values())) if fov else None)) for i in range(len(paths))}
            fov_all = {i: f for i, f in fov_all.items() if f}
            cloud, cameras, info = reconstruct_images(paths, known, cache=cache, fov_x=fov_all)
            check = depth_scale_check(capture_dir, paths, cache)
            if check:
                info["arcore_depth_scale_check"] = check  # diagnostic only, measured 8 percent far
            tier_plan = reconstruct_multiroom(cloud, tier, cameras)
            _write_plan(tier_plan, cloud, cameras, capture_dir, tier, info)
            tiers[tier] = _tier_summary(tier_plan, info)
        except Exception as e:  # noqa: BLE001, surfaced in the plan
            tiers[tier] = {"error": f"{type(e).__name__}: {e}"}

    plan["tiers"] = tiers
    (capture_dir / "plan.json").write_text(json.dumps(plan, indent=2))
    return tiers


def process_capture_dir(capture_dir: Path) -> dict:
    """Run the depth tier on an unpacked capture and write plan.json, plan.png, cloud.ply."""
    capture_dir = Path(capture_dir)
    json_path = capture_dir / "capture.json"
    data = json.loads(json_path.read_text())
    if not data.get("captures"):  # files-only upload: photos and/or a video, no depth frames
        plan = {
            "rooms": [],
            "diagnostics": None,
            "capture": {
                "kind": "files",
                "photos": sorted(str(p.relative_to(capture_dir)) for p in (capture_dir / "photos").rglob("*") if p.is_file()),
                "video": next((p.name for p in capture_dir.glob("video.*")), None),
            },
        }
        (capture_dir / "plan.json").write_text(json.dumps(plan, indent=2))
        return plan
    cloud = load_point_cloud(str(json_path))
    cameras = camera_positions(json_path)
    plan = reconstruct_multiroom(cloud, "depth", cameras)
    plan["capture"] = {
        "format": "web_capture",
        "frames": len(cameras),
        "photos": sorted(p.name for p in (capture_dir / "photos").glob("*.jpg")) if (capture_dir / "photos").exists() else [],
        "video": next((p.name for p in capture_dir.glob("video.*")), None),
    }
    _write_plan(plan, cloud, cameras, capture_dir, "depth")
    return plan


def rooms_to_schema(rooms, floor_y, ceiling_y, wall_height_cm, source_tier: str) -> dict:
    """Multi-room FloorPlan from segment_rooms output."""
    out_rooms = []
    for r in rooms:
        out_rooms.append(
            {
                "id": f"room-{r.label}",
                "label": "room",
                "polygon_cm": [[round(float(x) * 100, 1), round(float(z) * 100, 1)] for x, z in r.corners_xz],
                "wall_lengths_cm": [round(l * 100, 1) for l in r.wall_lengths_m],
                "area_m2": round(r.area_m2, 3),
                "perimeter_m": round(sum(r.wall_lengths_m), 3),
                "wall_height_cm": round((r.ceiling_y - r.floor_y) * 100, 1) if r.floor_y is not None and r.ceiling_y is not None else wall_height_cm,
                "height_source": "room_layers" if r.floor_y is not None and r.ceiling_y is not None else "global",
                "openings": [{"to": f"room-{d['to']}", "width_cm": round(d["width_m"] * 100, 1), "kind": d.get("kind", "doorway")} for d in r.doorways]
                + [dict(o, to=None) for o in r.openings],
                "confidence": None,
                "source_tier": source_tier,
            }
        )
    adjacency = sorted({tuple(sorted((f"room-{r.label}", f"room-{d['to']}"))) + (round(d["width_m"] * 100, 1),) for r in rooms for d in r.doorways})
    return {"rooms": out_rooms, "adjacency": [list(a) for a in adjacency], "floor_y": floor_y, "ceiling_y": ceiling_y}


def reconstruct_multiroom(cloud: o3d.geometry.PointCloud, source_tier: str, cameras: np.ndarray | None) -> dict:
    """Single-rectangle reconstruction plus, when a floor is found, the multi-room segmentation."""
    from floorplan_takehome.rooms import segment_rooms

    plan = reconstruct(cloud, source_tier=source_tier, cameras=cameras)
    g = plan["diagnostics"]
    if g["floor_y"] is not None:
        pts = np.asarray(clean_cloud(cloud).points)
        rooms, info = segment_rooms(pts, g["floor_y"], g["ceiling_y"])
        if rooms:
            multi = rooms_to_schema(rooms, g["floor_y"], g["ceiling_y"], plan["rooms"][0]["wall_height_cm"], source_tier)
            plan["single_room_fallback"] = plan["rooms"]
            plan["rooms"] = multi["rooms"]
            plan["adjacency"] = multi["adjacency"]
            plan["diagnostics"]["rooms"] = info
            plan["_rooms"] = rooms
    return plan


def _write_plan(plan: dict, cloud, cameras, out_dir: Path, tier: str, info: dict | None = None) -> None:
    from floorplan_takehome.intervals import add_intervals
    from floorplan_takehome.rooms import render_rooms

    fmt = plan.get("capture", {}).get("format", "stray_scanner")
    add_intervals(plan, "lidar" if tier.startswith("depth") and fmt == "stray_scanner" else tier.split("_")[0], info)

    suffix = "" if tier == "depth" else f"_{tier}"
    rooms = plan.pop("_rooms", None)
    cleaned = clean_cloud(cloud)
    o3d.io.write_point_cloud(str(out_dir / f"cloud{suffix}.ply"), cleaned)
    if rooms:
        render_rooms(np.asarray(cleaned.points), rooms, out_dir / f"plan{suffix}.png", cameras,
                     title=f"{tier}: {len(rooms)} rooms, {sum(r.area_m2 for r in rooms):.1f} m2")
    else:
        render_topdown(cleaned, {"rooms": plan.get("single_room_fallback", plan["rooms"]), "diagnostics": plan["diagnostics"]}, out_dir / f"plan{suffix}.png", cameras)
    (out_dir / f"plan{suffix}.json").write_text(json.dumps(plan, indent=2, default=str))


def process_stray_scan(scan_dir: Path, out_dir: Path, run_image_tiers: bool = True, max_images: int = 60) -> dict:
    """LiDAR tier from depth frames, video tier from rgb.mp4 with per-frame poses, photo tier from 8 stills."""
    import time

    from floorplan_takehome import stray_scanner as ss
    from floorplan_takehome.multiview import (
        photo_folders_from_rooms,
        reconstruct_photo_folders,
        reconstruct_video_chunked,
    )

    scan_dir, out_dir = Path(scan_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timing = {}

    from floorplan_takehome.drift import (
        apply_drift_correction,
        estimate_yaw_drift,
        footprint_metrics,
    )

    t = time.time()
    # drift: estimate heading drift from wall directions per time window, correct poses,
    # and keep the uncorrected footprint as the ablation
    windows, raw_poses = ss.window_clouds(scan_dir)
    floor_guess = float(np.percentile(np.concatenate([w[1][:, 1] for w in windows]), 2)) if windows else 0.0
    drift = estimate_yaw_drift(windows, floor_guess)
    cloud_off, cameras = ss.load_point_cloud(scan_dir)
    drift_info = {"method": "plane-anchored yaw correction (orientation only, no loop closure)", "estimate": None}
    if drift is not None:
        cloud, cameras = ss.load_point_cloud(scan_dir, poses=apply_drift_correction(raw_poses, drift))
        drift_info["estimate"] = {
            "rate_deg_per_min": drift.rate_deg_per_min,
            "window_frames": drift.window_frames,
            "deviation_deg": drift.deviation_deg,
            "fit_deg": drift.fit_deg,
            "max_correction_deg": round(max(abs(f) for f in drift.fit_deg), 2),
        }
    else:
        cloud = cloud_off
        drift_info["estimate"] = "not enough wall-bearing windows to estimate drift"
    plan_off = reconstruct_multiroom(cloud_off, "lidar", cameras)
    plan_off["capture"] = {"format": "stray_scanner"}
    plan = reconstruct_multiroom(cloud, "lidar", cameras)
    floor_y = plan["diagnostics"]["floor_y"] or floor_guess
    drift_info["ablation"] = {
        "off": {**footprint_metrics(np.asarray(clean_cloud(cloud_off).points), floor_y), "rooms": len(plan_off["rooms"]), "area_m2": [r.get("area_m2") for r in plan_off["rooms"]]},
        "on": {**footprint_metrics(np.asarray(clean_cloud(cloud).points), floor_y), "rooms": len(plan["rooms"]), "area_m2": [r.get("area_m2") for r in plan["rooms"]]},
    }
    plan["diagnostics"]["drift"] = drift_info
    plan["capture"] = {"format": "stray_scanner", "frames": len(cameras), "scan": str(scan_dir)}
    timing["lidar_s"] = round(time.time() - t, 1)
    _write_plan(plan_off, cloud_off, cameras, out_dir, "depth_drift_off")
    _write_plan(plan, cloud, cameras, out_dir, "depth")
    summary = {"lidar": _tier_summary(plan, {"frames": len(cameras), "drift": drift_info})}

    if run_image_tiers:
        every = 30  # 2 frames per second at 60 fps; chunking bounds memory, not the frame count
        paths, known = ss.video_frames_with_poses(scan_dir, out_dir / "frames", every=every)

        t = time.time()
        try:
            cloud_t, cams_t, info = reconstruct_video_chunked(paths, known, cache_dir=out_dir / "vggt_video_chunks")
            plan_t = reconstruct_multiroom(cloud_t, "video", cams_t)
            _write_plan(plan_t, cloud_t, cams_t, out_dir, "video", info)
            summary["video"] = _tier_summary(plan_t, info)
        except Exception as e:  # noqa: BLE001
            summary["video"] = {"error": f"{type(e).__name__}: {e}"}
        timing["video_s"] = round(time.time() - t, 1)

        # photo tier: the assessment delivers 2 to 8 stills per room. Emulate that from the
        # walk: frames are assigned to the LiDAR rooms by camera position, 8 spread stills per
        # room, one reconstruction per room, all placed in the shared frame by their poses.
        t = time.time()
        try:
            folders = photo_folders_from_rooms(plan["rooms"], paths, known, per_room=8)
            cloud_t, cams_t, info = reconstruct_photo_folders(folders, cache_dir=out_dir / "vggt_photos")
            plan_t = reconstruct_multiroom(cloud_t, "photos", cams_t)
            _write_plan(plan_t, cloud_t, cams_t, out_dir, "photos", info)
            summary["photos"] = _tier_summary(plan_t, info)
        except Exception as e:  # noqa: BLE001
            summary["photos"] = {"error": f"{type(e).__name__}: {e}"}
        timing["photos_s"] = round(time.time() - t, 1)

        t = time.time()
        try:
            damage = run_damage_for_stray(scan_dir, out_dir, plan)
            summary["damage"] = None if damage is None else {"detector": damage["detector"], "regions": len(damage["regions"]), "rejected": len(damage["rejected"]), "flags": damage["concealed_flags"]}
        except Exception as e:  # noqa: BLE001
            summary["damage"] = {"error": f"{type(e).__name__}: {e}"}
        timing["damage_s"] = round(time.time() - t, 1)

    summary["timing"] = timing
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary


def run_damage_for_capture(capture_dir: Path, plan: dict, backend: str | None = None) -> dict | None:
    """Damage regions on the photos of a web capture (poses and depth per photo)."""
    from floorplan_takehome.damage import run_damage
    from floorplan_takehome.depth_capture import _depth_grid

    capture_dir = Path(capture_dir)
    from floorplan_takehome.multiview import photo_records

    photo_poses, depth_views = {}, {}
    for path, view in photo_records(capture_dir):
        photo_poses[path] = (np.array(view["projection_matrix"]).reshape(4, 4, order="F"), np.array(view["transform_matrix"]).reshape(4, 4, order="F"))
        depth_views[path] = view
    if not photo_poses:
        return None

    def depth_lookup(path, u, v):
        grid = _depth_grid(depth_views[path])
        if grid is None:
            return None
        h, w = grid.shape
        d = grid[min(int(v * h), h - 1), min(int(u * w), w - 1)]
        return None if not np.isfinite(d) else float(d)

    g = plan.get("diagnostics") or {}
    result = run_damage(sorted(photo_poses), photo_poses, plan["rooms"], g.get("floor_y"), g.get("ceiling_y"), depth_lookup, backend)
    (capture_dir / "damage.json").write_text(json.dumps(result, indent=2))
    plan["damage"] = {k: v for k, v in result.items() if k != "raw_detections"}
    (capture_dir / "plan.json").write_text(json.dumps(plan, indent=2, default=str))
    return result


def run_damage_for_stray(scan_dir: Path, out_dir: Path, plan: dict, backend: str | None = None) -> dict | None:
    """Damage regions on upright video frames of a Stray Scanner scan (poses per frame)."""
    from floorplan_takehome import stray_scanner as ss
    from floorplan_takehome.damage import run_damage
    from floorplan_takehome.multiview import horizontal_frames

    scan_dir, out_dir = Path(scan_dir), Path(out_dir)
    # the video tier already extracted frames at 2 per second; damage uses every other one
    paths, known = ss.video_frames_with_poses(scan_dir, out_dir / "frames", every=30)
    paths = paths[::2]
    known = {k: known[i] for k, i in enumerate(range(0, len(known), 2)) if i in known}
    keep = horizontal_frames(known)
    if not keep:
        return None
    K = ss.load_intrinsics(scan_dir)
    import cv2

    img = cv2.imread(paths[keep[0]])
    h, w = img.shape[:2]
    # frames were rotated upright: the long sensor axis is now vertical. Focal lengths in
    # normalized device units for the rotated frame.
    f_px = K[0, 0] * (h / max(K[0, 2] * 2, 1))  # scale RGB intrinsics to the frame's long side
    proj = np.diag([2 * f_px / w, 2 * f_px / h, 1.0, 1.0])
    photo_poses = {paths[i]: (proj, known[i]) for i in keep}
    g = plan.get("diagnostics") or {}
    result = run_damage(sorted(photo_poses), photo_poses, plan["rooms"], g.get("floor_y"), g.get("ceiling_y"), None, backend)
    (out_dir / "damage.json").write_text(json.dumps(result, indent=2))
    plan["damage"] = {k: v for k, v in result.items() if k != "raw_detections"}
    (out_dir / "plan.json").write_text(json.dumps(plan, indent=2, default=str))
    return result


def apply_reference_length(plan: dict, measured_cm: float) -> dict:
    """Rescale every length in the plan so the longest wall of the first room equals a
    laser or tape measurement. The whole plan shares one scale, so one reference fixes
    all of it. Recorded in the output; intervals shrink to the reference's own error."""
    rooms = [r for r in plan.get("rooms", []) if r.get("wall_lengths_cm")]
    if not rooms:
        return plan
    longest = max(rooms[0]["wall_lengths_cm"])
    k = measured_cm / longest
    for r in plan["rooms"]:
        if r.get("polygon_cm"):
            r["polygon_cm"] = [[round(x * k, 1), round(z * k, 1)] for x, z in r["polygon_cm"]]
        for key in ("wall_lengths_cm",):
            if r.get(key):
                r[key] = [round(v * k, 1) for v in r[key]]
        for key in ("area_m2",):
            if r.get(key) is not None:
                r[key] = round(r[key] * k * k, 3)
        if r.get("perimeter_m") is not None:
            r["perimeter_m"] = round(r["perimeter_m"] * k, 3)
        for o in r.get("openings", []):
            for key in ("width_cm", "from_corner_cm"):
                if o.get(key) is not None:
                    o[key] = round(o[key] * k, 1)
    plan["reference_length"] = {"measured_cm": measured_cm, "applied_factor": round(k, 4), "note": "one measured wall length rescales the plan; lengths inherit the measurement's error"}
    return plan
