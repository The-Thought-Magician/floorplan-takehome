# Technical report: dimensioned floor plans from phone captures

Draft. Every number below is from docs/benchmark.md or docs/fix-loop.md, regenerable with scripts/benchmark.py and scripts/floorplan.py.

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
poses for the photo and video tiers, MoGe-2 supplies metric scale when no poses
exist, OWLv2 and Qwen3-VL-2B supply damage regions. All are disclosed in every
plan.json (`source_tier`, `scale_used`, `damage.detector`).

## 2. Tier design and device matrix

| tier | source | what makes it metric | device |
|---|---|---|---|
| LiDAR | Stray Scanner export: depth 256x192 at 60 fps, confidence, ARKit poses | ARKit depth and poses | iPhone 12 Pro or newer Pro, iPad Pro |
| depth (Android) | web page, WebXR depth sensing, ARCore | ARCore depth and VIO poses | ARCore phones, Chrome 107+ |
| video | rgb.mp4 or Camera app clip, 2 frames per second, VGGT in 16-frame chunks | recorded poses (Stray, web page) or MoGe-2 metric depth | any phone; iPhone 15+ per the brief |
| photos | 6 to 8 stills per room, VGGT per room | recorded poses, or MoGe-2 metric depth with EXIF field of view | any phone |

Honest accuracy per tier, measured so far (see docs/benchmark.md):

| tier | walls | ceiling | basis |
|---|---|---|---|
| LiDAR | not measured (no tape on the sample flats), bands 3 to 8 cm thick | 294 and 308 cm found per room where the ceiling was scanned | 3 Cozmo sample scans |
| depth (Android, TECNO LI9) | -1.3 and +1.8 percent after the fix loop (-8 and -14 before) | -11 cm | one tape-measured bedroom |
| video | -3 to -15 percent | not found | same bedroom, ARCore-depth anchor |
| photos, with poses | -7 to -9 percent | not found | same bedroom, ARCore-depth anchor |
| photos, no poses | -12 and -14 percent | not found | same bedroom, MoGe-2 anchor, no EXIF |

No tier passes the 1.5 cm ceiling gate or the 1 percent wall gate. The depth
tier is within 2 percent after the fix loop on the one tape-measured room. The
view-model tiers are limited by scale recovery, not geometry: their aspect
ratios are within 2 percent of the tape.

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
   the per-chunk fit is within 10 to 15 percent. Without poses MoGe-2 anchors
   the scale: within 2 percent of the tape on frames that see a whole wall, 10
   to 25 percent low on close-ups, 12 to 14 percent low overall on the bedroom
   without EXIF field of view.
2. Depth fill on textureless surfaces (ARCore): smooth depth invents flat
   surfaces on ceilings and floors. Detected and rejected by plane tilt, but it
   removes the ceiling from the depth tier entirely.
3. Wall band thickness: RANSAC fits the middle of a 30 to 66 cm noisy band on
   ARCore, so room dimensions came out 8 to 14 percent small. The fix loop moves
   thick bands to their outer face, leaving 1 to 2 percent. LiDAR bands are 3
   to 8 cm and untouched.
4. Room polygon from free space: the polygon follows the inner face of the wall
   band. Systematic inward bias of about half the band thickness.
5. Ceiling height: floor and ceiling are textureless, so they are the last
   surfaces any tier sees well. Per-room height from the point height histogram
   is the current best.

## 5. Calibration analysis

Intervals come from a per-tier error model (absolute floor plus relative term
plus alignment term for view models), stated as priors and named in every
plan.json as `interval_basis`. One tape-measured room is not enough to fit
them; the depth-tier prior was reset after the fix loop to the residual it
showed there (walls within 2 percent, ceiling -11 cm). Every other tier's
interval is a prior and the report says so.

## 6. Fix loop

docs/fix-loop.md. Worst gate: depth-tier wall lengths, -7.9 and -14.2 percent.
Root cause: depth-from-motion fills textureless walls with points biased into
the room, so the fitted wall line sits inside the true wall. Fix: for wall
bands thicker than 15 cm, place the wall at the 80th percentile of the band's
outward spread. Predicted within 3 percent; measured -1.3 and +1.8 percent.
LiDAR bands are thin, so LiDAR rooms did not move. The percentile was set on
the same capture it was tested on, and no second closed capture exists yet to
check it, which the fix-loop page states.

## 6a. Damage detection

OWLv2 localizes candidates, Qwen3-VL-2B classifies each crop or rejects it.
Cozmo's single_room sample contains a real 60 cm crack in a bathroom wall: the
first stage found it and called it a water stain, the second stage relabels it
crack. On the undamaged bedroom every candidate is rejected. Concealed-damage
flags are rules named in the output. Metric extent comes from the box cast
onto the room surface at the depth of the hit, or from the depth frame when
one exists for the photo.

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
- Damage detector: tested on one real crack (Cozmo sample) and one undamaged
  room. Water stains, mould and peeling paint have not been seen in any test
  image; the classifier's behaviour on them is untested.
