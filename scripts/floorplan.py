"""One command per capture.

    uv run python scripts/floorplan.py <capture_dir> [out_dir]

Detects the capture format: a Stray Scanner export (odometry.csv + depth/), or an
unpacked zip from the web capture page (capture.json).
"""

import argparse
import json
import sys
from pathlib import Path

from floorplan_takehome import pipeline, stray_scanner
from floorplan_takehome.pipeline import (
    process_capture_dir,
    process_image_tiers,
    process_stray_scan,
    run_damage_for_capture,
)

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
        tiers = process_image_tiers(src, plan)
        damage = run_damage_for_capture(src, plan)
        summary = {
            "depth": {"rooms": len(plan["rooms"]), "wall_lengths_cm": [r.get("wall_lengths_cm") for r in plan["rooms"]], "wall_height_cm": [r.get("wall_height_cm") for r in plan["rooms"]]},
            "tiers": tiers,
            "damage": None if damage is None else {"regions": len(damage["regions"]), "rejected": len(damage["rejected"]), "flags": len(damage["concealed_flags"])},
        }
        (src / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    else:
        sys.exit(f"{src}: not a Stray Scanner export or a web capture")
    print(json.dumps(summary, indent=2, default=str))
