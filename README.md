# Floor plan reconstruction

Turns phone camera captures into dimensioned, stitched floor plans, cm-level
accuracy, across three input tiers: photos, video, LiDAR.

Full research and architecture: [docs/plan.md](docs/plan.md).

## Setup

```
uv sync
```

Fallback without uv:

```
pip install -r requirements.txt
```

Requires Python 3.14.

## Layout

```
src/floorplan_takehome/   implementation
tests/                    tests
notebooks/                exploration
docs/                     plan and design notes
data/                     sample captures per tier (not tracked in git)
```

## Status

Planning and research complete. Implementation not started.
