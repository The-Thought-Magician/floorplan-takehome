"""Load a depth capture, export a point cloud, and render a top-down sanity check."""

import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import open3d as o3d

sys.path.insert(0, "src")
from floorplan_takehome.depth_capture import load_point_cloud

if __name__ == "__main__":
    json_path = sys.argv[1]
    out_prefix = sys.argv[2]

    cloud = load_point_cloud(json_path)
    points = np.asarray(cloud.points)

    o3d.io.write_point_cloud(out_prefix + ".ply", cloud)

    mins = points.min(axis=0)
    maxs = points.max(axis=0)
    extent = maxs - mins
    print(f"points: {len(points)}")
    print(f"bounding box min: {mins}")
    print(f"bounding box max: {maxs}")
    print(f"extent (x, y up, z): {extent}")

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.scatter(points[:, 0], points[:, 2], s=3, c=points[:, 1], cmap="viridis")
    ax.set_xlabel("x (m)")
    ax.set_ylabel("z (m)")
    ax.set_title("top-down (color = height)")
    ax.set_aspect("equal")
    fig.savefig(out_prefix + "_topdown.png", dpi=150)
