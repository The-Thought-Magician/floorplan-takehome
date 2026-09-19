"""Turn a browser depth-capture JSON (see web-capture/index.html) into a point cloud."""

import json

import numpy as np
import open3d as o3d


def _unproject_grid(view: dict) -> np.ndarray:
    """Unproject one view's depth grid into world-space points."""
    grid = view["depth_grid_meters"]
    if grid is None:
        return np.empty((0, 3))

    proj = np.array(view["projection_matrix"]).reshape(4, 4, order="F")
    cam_to_world = np.array(view["transform_matrix"]).reshape(4, 4, order="F")
    fx, fy = proj[0, 0], proj[1, 1]

    grid_h = len(grid)
    grid_w = len(grid[0])

    points = []
    for row in range(grid_h):
        for col in range(grid_w):
            depth = grid[row][col]
            if depth is None:
                continue
            u = (col + 0.5) / grid_w
            v = (row + 0.5) / grid_h
            ndc_x = u * 2 - 1
            ndc_y = 1 - v * 2

            x_cam = ndc_x * depth / fx
            y_cam = ndc_y * depth / fy
            z_cam = -depth

            cam_point = np.array([x_cam, y_cam, z_cam, 1.0])
            world_point = cam_to_world @ cam_point
            points.append(world_point[:3])

    return np.array(points)


def load_point_cloud(json_path: str) -> o3d.geometry.PointCloud:
    with open(json_path) as f:
        data = json.load(f)

    all_points = []
    for capture in data["captures"]:
        for view in capture["views"]:
            all_points.append(_unproject_grid(view))

    points = np.concatenate([p for p in all_points if len(p)], axis=0)

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    return cloud
