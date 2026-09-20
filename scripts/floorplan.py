"""One command per capture.

    uv run python scripts/floorplan.py <capture_dir> [out_dir]

Detects the capture format: a Stray Scanner export (odometry.csv + depth/), or an
unpacked zip from the web capture page (capture.json).
"""

import argparse
import json
from pathlib import Path

from floorplan_takehome import pipeline, stray_scanner
from floorplan_takehome.pipeline import process_capture_dir, process_image_tiers, process_stray_scan

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("capture")
    ap.add_argument("out", nargs="?")
    ap.add_argument("--wall-face", choices=["centre", "outer"], default="outer", help="centre reproduces the pre-fix wall placement")
    args = ap.parse_args()
    pipeline.WALL_FACE = args.wall_face
    src = Path(args.capture)
    out = Path(args.out) if args.out else src / "out"
    scan = stray_scanner.find_scan_dir(src)
    if scan is not None:
        summary = process_stray_scan(scan, out)
    elif (src / "capture.json").exists():
        plan = process_capture_dir(src)
        summary = {"depth": plan["rooms"], "tiers": process_image_tiers(src, plan)}
    else:
        sys.exit(f"{src}: not a Stray Scanner export or a web capture")
    print(json.dumps(summary, indent=2, default=str))
