"""Multi-room segmentation on a processed sample directory (cloud.ply + plan.json)."""

import json
import sys
import time
from pathlib import Path

import numpy as np
import open3d as o3d

from floorplan_takehome.rooms import render_rooms, segment_rooms

if __name__ == "__main__":
    d = Path(sys.argv[1])
    plan = json.loads((d / "plan.json").read_text())
    g = plan["diagnostics"]
    pts = np.asarray(o3d.io.read_point_cloud(str(d / "cloud.ply")).points)
    t = time.time()
    rooms, info = segment_rooms(pts, g["floor_y"], g.get("ceiling_y"))
    print(d.name, f"{time.time() - t:.1f}s", info)
    for r in rooms:
        print(f"  R{r.label}: area {r.area_m2:.2f} m2, corners {len(r.corners_xz)}, walls cm {[round(l * 100) for l in r.wall_lengths_m]}, doors {r.doorways}")
    render_rooms(pts, rooms, d / "rooms.png", title=f"{d.name}: {len(rooms)} rooms")
