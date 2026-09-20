# Floor plan reconstruction

Turns phone camera captures into dimensioned, stitched floor plans, cm-level
accuracy, across three input tiers: photos, video, depth (ARCore / LiDAR).

Full research and architecture: [docs/plan.md](docs/plan.md).

## Setup

```
uv sync
```

Fallback without uv:

```
pip install -r requirements.txt
```

Requires Python 3.14. Torch is pulled in with CUDA 13 wheels (RTX 50 series
needs cu128 or newer).

## One command per capture

```
scripts/setup.sh                                   # once: deps, VGGT fork, weights (about 5 GB)
uv run python scripts/floorplan.py <capture> <out>   # any tier, format detected from the folder
```

`<capture>` is one of:

- a Stray Scanner export (`odometry.csv`, `depth/`, `confidence/`, `rgb.mp4`):
  LiDAR tier from the depth frames, video tier from `rgb.mp4`, photo tier from
  per-room stills cut from the walk, drift ablation, damage pass
- an unpacked upload from the capture page (`capture.json` plus `photos/`,
  `video.*`): depth tier from ARCore frames, then photo and video tiers
- a files-only upload (`capture.json` with no depth frames, `photos/<room>/*.jpg`,
  optional `video.*`): photo and video tiers, relative scale unless poses exist

Outputs in `<out>`: `plan.json` (schema below), `plan.png`, `plan_photos.*`,
`plan_video.*`, `plan_depth_drift_off.*` (ablation), `damage.json`, `summary.json`
with timing. `scripts/benchmark.py` turns every output plus `data/ground_truth`
into `docs/benchmark.md`.

## Capture on a phone

```
scripts/serve.sh
```

Starts the backend on 127.0.0.1:8000 and a Cloudflare quick tunnel. Open the
printed `https://....trycloudflare.com` URL on the phone:

- Android Chrome: start ar, tap capture at each wall (depth + pose + photo),
  record a walkthrough, upload + process. Results render in the overlay.
- Any phone without WebXR (all iPhones): open "upload photos or a video
  instead", pick the room's photos or a video, upload. For LiDAR on iPhone use
  Stray Scanner and hand the export folder to the pipeline (docs/capture-protocol.md).

## Output schema (plan.json)

```
rooms[]        id, polygon_cm, wall_lengths_cm (+_interval_cm), area_m2 (+_interval_m2),
               wall_height_cm (+_interval_cm), height_source, openings[] (doorway/open/door/window,
               width_cm, from_corner_cm, wall), source_tier
adjacency[]    [room_a, room_b, opening_width_cm]
damage         detector, regions[] (class, room, surface, width_cm, height_cm, area_m2,
               height_above_floor_cm, photo, box), concealed_flags[] (rule, text), scope_items[]
diagnostics    points, planes, walls, floor_y, ceiling_y, drift {estimate, ablation}, rooms
interval_basis which error model produced the intervals (prior or calibrated)
```

## Layout

```
src/floorplan_takehome/   depth_capture (ingest), plane_extraction (geometry),
                          pipeline (schema + render), server (FastAPI)
web-capture/              WebXR capture page, served at / by the backend
scripts/                  serve.sh (backend + tunnel), inspect_capture.py
tests/                    synthetic-data tests
docs/                     plan and design notes
data/                     captures (not tracked in git)
```

## Status

All three tiers run end to end on a real Android phone capture. Depth tier
from ARCore, photo and video tiers through VGGT on the local GPU, scaled with
the recorded ARCore poses. Scale agreement between tiers is the open issue,
see docs/plan.md.
