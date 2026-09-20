# Technical report: dimensioned floor plans from phone captures

Draft, numbers marked TBD are filled by scripts/benchmark.py output before submission.

## 1. Architecture

```
capture (phone)  ->  ingest  ->  point cloud + poses  ->  floor, walls, rooms  ->  schema + render
```

- Ingest: three loaders produce the same thing, a y-up metric point cloud plus
  camera positions. `stray_scanner.py` (iOS LiDAR export), `depth_capture.py`
  (ARCore via the web page), `multiview.py` (VGGT on photos or video frames,
  scaled by poses when they exist).
- Geometry: `plane_extraction.py` (RANSAC planes, floor and ceiling, Manhattan
  wall snap) for the single-room path, `rooms.py` for the multi-room path
  (density masks, doorway split, rectilinear polygons, adjacency, doors and
  windows, per-room heights).
- Contract: `pipeline.py` assembles the FloorPlan JSON, `intervals.py` attaches
  a confidence interval to every measurement, `damage.py` adds damage regions,
  concealed flags and scope items, `drift.py` supplies the drift correction and
  its ablation.
- Transport: `server.py` (FastAPI) plus `web-capture/index.html`. One command
  per capture is `scripts/floorplan.py`.

No learned model is used for geometry. VGGT-1B supplies point maps and camera
poses for the photo and video tiers, OWLv2 supplies damage detections. Both are
disclosed in every plan.json (`source_tier`, `damage.detector`).

## 2. Tier design and device matrix

| tier | source | what makes it metric | device |
|---|---|---|---|
| LiDAR | Stray Scanner export: depth 256x192 at 60 fps, confidence, ARKit poses | ARKit depth and poses | iPhone 12 Pro or newer Pro, iPad Pro |
| depth (Android) | web page, WebXR depth sensing, ARCore | ARCore depth and VIO poses | ARCore phones, Chrome 107+ |
| video | rgb.mp4 or Camera app clip, 2 frames per second, VGGT in 16-frame chunks | recorded poses (Stray, web page) or, without them, relative scale | any phone; iPhone 15+ per the brief |
| photos | 6 to 8 stills per room, VGGT per room | recorded poses, or relative scale | any phone |

Honest accuracy per tier, measured so far (see docs/benchmark.md):

| tier | walls | ceiling | basis |
|---|---|---|---|
| LiDAR | TBD | TBD | 3 Cozmo sample scans, no tape yet |
| depth (Android, TECNO LI9) | -8 to -14 percent | -11 cm | one tape-measured bedroom |
| video | -3 to -15 percent | -42 cm | same bedroom, ARCore-depth anchor |
| photos | -7 to -9 percent | -70 cm | same bedroom, ARCore-depth anchor |

No tier passes the 1.5 cm ceiling gate yet. The LiDAR tier is the only one with
a credible path to the wall gates; the two view-model tiers are limited by scale
recovery, not by geometry (their aspect ratios are within 2 percent of the tape).

## 3. Drift handling

VIO heading drifts, walls do not. Per 5-second window of a scan the dominant wall
direction is measured (Hough on the tall-point density); its deviation from the
first window, folded to a 90 degree period, is the heading drift at that time. A
linear fit gives the rate and each pose is rotated about the vertical axis by the
negative of the fitted drift. This is an orientation-only correction; position
drift is not recovered and no loop closure is claimed. Ablation (footprint with
correction off and on) is in docs/benchmark.md. On the Cozmo single-room sample:
1.9 degrees per minute, 0.84 degrees maximum correction, footprint unchanged
within noise, which says ARKit heading drift over 37 seconds is not the error
budget's problem.

## 4. Error budget

Where the centimetres go, largest first:

1. Scale, view-model tiers: VGGT is relative. Poses fix it when they exist; on a
   rotate-in-place capture the pose fit was 40 percent off, on a walking capture
   the per-chunk fit is within 10 to 15 percent. Without poses a monocular
   metric anchor (MoGe-2) is the plan, not yet built.
2. Depth fill on textureless surfaces (ARCore): smooth depth invents flat
   surfaces on ceilings and floors. Detected and rejected by plane tilt, but it
   removes the ceiling from the depth tier entirely.
3. Wall band thickness: RANSAC fits the middle of a 20 to 50 cm noisy band, so
   room dimensions come out 5 to 15 percent small on ARCore. LiDAR bands are 3
   to 8 cm.
4. Room polygon from free space: the polygon follows the inner face of the wall
   band. Systematic inward bias of about half the band thickness.
5. Ceiling height: floor and ceiling are textureless, so they are the last
   surfaces any tier sees well. Per-room height from the point height histogram
   is the current best.

## 5. Calibration analysis

Intervals come from a per-tier error model (absolute floor plus relative term
plus alignment term), stated as priors until data/calibration.json refits them
from data/ground_truth. Coverage is scored by scripts/benchmark.py: TBD.

## 6. Fix loop

See docs/fix-loop.md. Worst gate: TBD after the benchmark capture.

## 7. Known failure modes

- Rooms scanned only from the doorway: the polygon is the scanned footprint.
- Open-plan spaces: the doorway split merges or arbitrarily splits them; the
  contact is labelled "open" rather than a doorway.
- Mirrors: LiDAR and ARCore return the reflected geometry as a phantom room
  behind the mirror. The protocol says to close mirrored doors; no detection yet.
- Glass and wet surfaces: depth holes, VGGT sees through windows and places
  points outside the room, which the outermost-wall rule can pick up.
- Low light: ARCore and VGGT degrade, LiDAR does not.
- Sloped or multi-level ceilings: one height per room.
- Damage detector: OWLv2 false positives on shadows at low scores, filtered by
  score and physical size; untested on real staged damage until the benchmark
  capture.
