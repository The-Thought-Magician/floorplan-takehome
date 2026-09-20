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

## Run the capture flow

```
scripts/serve.sh
```

Starts the backend on 127.0.0.1:8000 and a Cloudflare quick tunnel. Open the
printed `https://....trycloudflare.com` URL in Chrome on an Android phone:

1. start ar, walk the room, tap capture near each wall (saves depth + pose +
   photo), tap record for a video with poses.
2. stop, then upload + process. The floor plan renders in the overlay.
3. or untick upload and export zip to download `capture.json`, `photos/`,
   `video.webm` for offline processing.

Process a capture directory without the server:

```
uv run python -c "from floorplan_takehome.pipeline import process_capture_dir; process_capture_dir('data/captures/<id>')"
```

Writes `plan.json`, `plan.png`, `cloud.ply` next to `capture.json`.

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
