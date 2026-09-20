"""Capture directory in, FloorPlan schema out. Shared by the CLI and the server."""

import json
from pathlib import Path

import numpy as np
import open3d as o3d

from floorplan_takehome.depth_capture import load_point_cloud
from floorplan_takehome.plane_extraction import (
    manhattan_filter,
    outer_walls,
    merge_walls,
    polygon_area,
    polygon_perimeter,
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
    for capture in data["captures"]:
        for view in capture["views"]:
            m = np.array(view["transform_matrix"], dtype=float).reshape(4, 4, order="F")
            positions.append(m[:3, 3])
    return np.array(positions) if positions else np.empty((0, 3))


def reconstruct(cloud: o3d.geometry.PointCloud, source_tier: str, cameras: np.ndarray | None = None) -> dict:
    o3d.utility.random.seed(0)  # RANSAC must give the same answer for the same capture
    cloud = clean_cloud(cloud)
    planes = segment_planes(cloud, distance_threshold=0.04, max_planes=10, min_inliers=80)
    raw_walls = merge_walls([p for p in planes if p.is_wall])
    walls = outer_walls(manhattan_filter(raw_walls))
    corners = wall_polygon(walls)

    n_points = len(cloud.points)
    wall_points = sum(len(w.points) for w in walls)
    camera_y = float(np.median(cameras[:, 1])) if cameras is not None and len(cameras) else None
    floor_y, ceiling_y = _floor_and_ceiling(planes, camera_y)
    wall_height = None if floor_y is None or ceiling_y is None else ceiling_y - floor_y
    height_source = "floor_ceiling_planes" if wall_height is not None else None
    if wall_height is None and walls:
        # walls run floor to ceiling, so the vertical extent of their inliers is the room height
        extents = [np.percentile(w.points[:, 1], 99) - np.percentile(w.points[:, 1], 1) for w in walls]
        if np.median(extents) >= 2.0:  # anything lower means the ceiling was never observed
            wall_height = float(np.median(extents))
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
        ax.set_title("no closed polygon (walls found: %d)" % plan["diagnostics"]["walls"])
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
    from floorplan_takehome.multiview import depth_scale_check, photo_paths_and_poses, reconstruct_images, video_frame_paths

    capture_dir = Path(capture_dir)
    tiers = {}
    photos, centers = photo_paths_and_poses(capture_dir)
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
            cloud, cameras, info = reconstruct_images(paths, known, cache=cache)
            check = depth_scale_check(capture_dir, paths, cache)
            if check and info.get("scale"):
                # Pixel-wise depth agreement beats a pose fit on a short baseline (tape-verified,
                # see plan.md). Rescale about the aligned cameras' centroid.
                factor = check["depth_based_scale"] / info["scale"]
                pivot = cameras.mean(axis=0)
                pts = (np.asarray(cloud.points) - pivot) * factor + pivot
                cloud.points = o3d.utility.Vector3dVector(pts)
                cameras = (cameras - pivot) * factor + pivot
                info["scale_check"] = check
                info["scale_used"] = "arcore_depth"
                info["pose_scale"] = info["scale"]
                info["scale"] = check["depth_based_scale"]
            tier_plan = reconstruct_multiroom(cloud, tier, cameras)
            _write_plan(tier_plan, cloud, cameras, capture_dir, tier)
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
    plan = reconstruct(cloud, source_tier="depth", cameras=cameras)
    plan["capture"] = {
        "photos": sorted(p.name for p in (capture_dir / "photos").glob("*.jpg")) if (capture_dir / "photos").exists() else [],
        "video": (capture_dir / "video.webm").name if (capture_dir / "video.webm").exists() else None,
    }
    o3d.io.write_point_cloud(str(capture_dir / "cloud.ply"), clean_cloud(cloud))
    render_topdown(clean_cloud(cloud), plan, capture_dir / "plan.png", cameras)
    (capture_dir / "plan.json").write_text(json.dumps(plan, indent=2))
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
                "openings": [{"to": f"room-{d['to']}", "width_cm": round(d["width_m"] * 100, 1), "kind": d.get("kind", "doorway")} for d in r.doorways],
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


def _write_plan(plan: dict, cloud, cameras, out_dir: Path, tier: str) -> None:
    from floorplan_takehome.rooms import render_rooms

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
    from floorplan_takehome.multiview import reconstruct_images

    scan_dir, out_dir = Path(scan_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timing = {}

    t = time.time()
    cloud, cameras = ss.load_point_cloud(scan_dir)
    plan = reconstruct_multiroom(cloud, "lidar", cameras)
    plan["capture"] = {"format": "stray_scanner", "frames": int(len(cameras)), "scan": str(scan_dir)}
    timing["lidar_s"] = round(time.time() - t, 1)
    _write_plan(plan, cloud, cameras, out_dir, "depth")
    summary = {"lidar": _tier_summary(plan, {"frames": int(len(cameras))})}

    if run_image_tiers:
        n_frames = len(cameras)
        every = max(30, int(np.ceil(n_frames / max_images)))
        for tier, step in (("video", every), ("photos", max(every, n_frames // 8))):
            t = time.time()
            try:
                paths, known = ss.video_frames_with_poses(scan_dir, out_dir / f"frames_{tier}", every=step)
                cloud_t, cams_t, info = reconstruct_images(paths, known, cache=out_dir / f"vggt_{tier}.npz")
                plan_t = reconstruct_multiroom(cloud_t, tier, cams_t)
                _write_plan(plan_t, cloud_t, cams_t, out_dir, tier)
                summary[tier] = _tier_summary(plan_t, info)
            except Exception as e:  # noqa: BLE001
                summary[tier] = {"error": f"{type(e).__name__}: {e}"}
            timing[f"{tier}_s"] = round(time.time() - t, 1)

    summary["timing"] = timing
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    return summary
