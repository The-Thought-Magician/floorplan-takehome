"""Turn a browser depth-capture JSON (see web-capture/index.html) into a point cloud.

Two depth encodings are supported per view:

- depth_buffer: the full XRCPUDepthInformation buffer (uint16 luminance-alpha or
  float32), base64 encoded, plus the normDepthBufferFromNormView matrix. This is
  the preferred source, every depth pixel becomes a point.
- depth_grid_meters: a coarse grid of getDepthInMeters samples in normalized view
  coordinates. Kept as a fallback and as a cross-check for the buffer decode.
"""

import base64
import json
import logging
import warnings

import numpy as np
import open3d as o3d

log = logging.getLogger(__name__)


def _col_major(values, shape=(4, 4)) -> np.ndarray:
    return np.array(values, dtype=float).reshape(shape, order="F")


def decode_depth_buffer(buffer: dict) -> np.ndarray:
    """Decode a captured depth buffer into an (h, w) array of meters, NaN where invalid."""
    raw = base64.b64decode(buffer["data_b64"])
    w, h = int(buffer["width"]), int(buffer["height"])
    fmt = buffer.get("format", "luminance-alpha")
    if fmt == "float32":
        values = np.frombuffer(raw, dtype="<f4").astype(float)
    elif fmt in ("luminance-alpha", "unsigned-short"):
        values = np.frombuffer(raw, dtype="<u2").astype(float)
    else:
        raise ValueError(f"unsupported depth format {fmt!r}")
    if values.size != w * h:
        raise ValueError(f"depth buffer has {values.size} values, expected {w * h}")
    meters = values.reshape(h, w) * float(buffer["raw_value_to_meters"])
    meters[meters <= 0] = np.nan
    return meters


def _depth_in_view_coords(view: dict, grid_w: int, grid_h: int) -> np.ndarray:
    """Resample the full depth buffer onto a (grid_h, grid_w) grid of normalized view coords.

    Uses the inverse of normDepthBufferFromNormView to map each depth pixel into
    view space, mirroring what getDepthInMeters does in the browser.
    """
    buffer = view["depth_buffer"]
    meters = decode_depth_buffer(buffer)
    h, w = meters.shape
    m = _col_major(buffer["norm_depth_buffer_from_norm_view"])

    us = (np.arange(grid_w) + 0.5) / grid_w
    vs = (np.arange(grid_h) + 0.5) / grid_h
    uu, vv = np.meshgrid(us, vs)
    view_coords = np.stack([uu.ravel(), vv.ravel(), np.zeros(uu.size), np.ones(uu.size)])
    depth_coords = m @ view_coords
    cols = np.clip((depth_coords[0] * w).astype(int), 0, w - 1)
    rows = np.clip((depth_coords[1] * h).astype(int), 0, h - 1)
    return meters[rows, cols].reshape(grid_h, grid_w)


def _depth_grid(view: dict) -> np.ndarray | None:
    """Best available depth for a view as an (h, w) array in normalized view coords."""
    buffer = view.get("depth_buffer")
    grid = view.get("depth_grid_meters")
    if buffer:
        h, w = int(buffer["height"]), int(buffer["width"])
        full = _depth_in_view_coords(view, w, h)
        if grid:
            coarse = _depth_in_view_coords(view, len(grid[0]), len(grid))
            ref = np.array([[np.nan if d is None else d for d in row] for row in grid])
            ok = np.isfinite(coarse) & np.isfinite(ref)
            if ok.sum() and np.nanmedian(np.abs(coarse[ok] - ref[ok])) > 0.05:
                warnings.warn("depth buffer disagrees with sampled grid, using the grid")
                return ref
        return full
    if grid:
        return np.array([[np.nan if d is None else d for d in row] for row in grid])
    return None


def _unproject_grid(view: dict, max_range_m: float = 6.0) -> np.ndarray:
    """Unproject one view's depth (in normalized view coords) into world-space points."""
    depth = _depth_grid(view)
    if depth is None:
        return np.empty((0, 3))

    proj = _col_major(view["projection_matrix"])
    cam_to_world = _col_major(view["transform_matrix"])
    fx, fy = proj[0, 0], proj[1, 1]
    cx, cy = proj[0, 2], proj[1, 2]

    grid_h, grid_w = depth.shape
    cols, rows = np.meshgrid(np.arange(grid_w), np.arange(grid_h))
    u = (cols + 0.5) / grid_w
    v = (rows + 0.5) / grid_h
    ndc_x = u * 2 - 1
    ndc_y = 1 - v * 2

    valid = np.isfinite(depth) & (depth <= max_range_m)
    d = depth[valid]
    x_cam = (ndc_x[valid] + cx) * d / fx
    y_cam = (ndc_y[valid] + cy) * d / fy
    z_cam = -d
    cam_points = np.stack([x_cam, y_cam, z_cam, np.ones_like(d)], axis=0)
    world = (cam_to_world @ cam_points)[:3].T
    return world


def load_point_cloud(json_path: str, max_range_m: float = 6.0) -> o3d.geometry.PointCloud:
    with open(json_path) as f:
        data = json.load(f)

    all_points = []
    for capture in data["captures"]:
        for view in capture["views"]:
            all_points.append(_unproject_grid(view, max_range_m))

    chunks = [p for p in all_points if len(p)]
    points = np.concatenate(chunks, axis=0) if chunks else np.empty((0, 3))

    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    return cloud
