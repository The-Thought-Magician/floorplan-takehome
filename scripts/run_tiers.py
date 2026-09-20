"""Run the photo and video tiers on an already processed capture directory."""

import json
import sys
import time
from pathlib import Path

from floorplan_takehome.pipeline import process_image_tiers

if __name__ == "__main__":
    capture_dir = Path(sys.argv[1])
    plan = json.loads((capture_dir / "plan.json").read_text())
    t = time.time()
    tiers = process_image_tiers(capture_dir, plan)
    print(f"took {time.time() - t:.0f}s")
    print(json.dumps(tiers, indent=2))
