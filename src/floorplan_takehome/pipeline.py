"""Capture directory in, FloorPlan schema out. Shared by the CLI and the server."""

import json
from pathlib import Path

import numpy as np
import open3d as o3d

from floorplan_takehome.depth_capture import load_point_cloud
from floorplan_takehome.plane_extraction import (
    manhattan_filter,
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
    walls = manhattan_filter(raw_walls)
    corners = wall_polygon(walls)

    n_points = len(cloud.points)
    wall_points = sum(len(w.points) for w in walls)
    camera_y = float(np.median(cameras[:, 1])) if cameras is not None and len(cameras) else None
    floor_y, ceiling_y = _floor_and_ceiling(planes, camera_y)
    wall_height = None if floor_y is None or ceiling_y is None else ceiling_y - floor_y

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
            "walls_rejected_off_axis": len(raw_walls) - len(walls),
            "closed": bool(corners),
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
    room = plan["rooms"][0]
    return {
        "closed": bool(room["polygon_cm"]),
        "wall_lengths_cm": room.get("wall_lengths_cm"),
        "area_m2": room.get("area_m2"),
        "walls": plan["diagnostics"]["walls"],
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
    frames = video_frame_paths(capture_dir)

    jobs = []
    if len(photos) >= 3:
        jobs.append(("photos", photos, centers))
    if frames and len(photos) >= 3:
        jobs.append(("video", photos + frames, centers))
    elif frames:
        jobs.append(("video", frames, {}))

    for tier, paths, known in jobs:
        try:
            cloud, cameras, info = reconstruct_images(paths, known, cache=capture_dir / f"vggt_{tier}.npz")
            tier_plan = reconstruct(cloud, source_tier=tier, cameras=cameras)
            o3d.io.write_point_cloud(str(capture_dir / f"cloud_{tier}.ply"), clean_cloud(cloud))
            render_topdown(clean_cloud(cloud), tier_plan, capture_dir / f"plan_{tier}.png", cameras)
            (capture_dir / f"plan_{tier}.json").write_text(json.dumps(tier_plan, indent=2))
            check = depth_scale_check(capture_dir, paths, capture_dir / f"vggt_{tier}.npz")
            if check:
                info["scale_check"] = check
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
