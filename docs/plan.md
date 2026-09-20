# Floor plan reconstruction: plan, findings and state

Rewritten 2026-09-20 as one document. Everything here was either verified
against a primary source or measured on this hardware; items still unverified
say so. Older revisions are in git history.

## 1. Problem and scoring

Phone captures in, dimensioned and stitched floor plans out, at three input
tiers: photos (6 to 8 stills per room, no poses), video (handheld clip), LiDAR
(depth, poses, intrinsics on Pro iPhones). Output contract per capture: per-room
plan with walls, ceiling height, floor area and openings; stitched multi-room
plan with adjacency; per-surface damage regions with class and metric extent;
concealed-damage flags naming the rule; scope line items keyed to surfaces; a
confidence interval on every measurement; one command per capture; JSON to a
published schema; a rendered plan.

Scoring: walk-in test on the graders' iPhone 30 percent, fix loop 25, verified
benchmark 15, compliance matrix 10, head-to-head against a consumer app 10,
capture route 5, commit history 5. Gates: openings 2 cm on 85 percent, ceiling
1.5 cm with 1 cm repeat spread, repeatability 1 cm or 0.5 percent, drift
ablation mandatory, photo tier whole-property stitch within 8 percent, video
3 percent, LiDAR 1 percent. Deadline 2026-09-23 10:00 IST.

## 2. Situation and decisions

- No iPhone. Capture route is Route 2, stock apps: Stray Scanner for LiDAR
  (the format Cozmo's own samples use), Camera app for photos and video.
  Head-to-head app: magicplan on iPhone, CubiCasa LITE on Android. Checked on
  2026-09-20 against the vendors' help centres and store reviews: magicplan
  does not scan on Android at all (manual drawing only), Polycam's dimensioned
  modes need iPhone LiDAR, CubiCasa LITE measures from a video walk on Android
  12+ ARCore phones and returns a free dimensioned PNG/JPG. iPhone magicplan
  users report walls 4 to 8 inches off; CubiCasa claims 2 to 3 percent with
  independent tests showing 3 to 17 inch errors.
- Benchmark data: Cozmo's three Stray Scanner scans (single_room is 3 rooms,
  single_scan_floor_only 6, single_scan_with_ceiling 5 plus corridor, no tape),
  and eight captures of the user's bedroom from an Android TECNO LI9 through the
  web capture page (one closes a polygon, seven were too sparse). Tape ground
  truth for the bedroom: 426.7 x 365.8 cm, ceiling 312.4 cm. No other rooms,
  no staged damage, no marker photo, no magicplan scan are available.
- Local run is the product. Everything runs on the laptop; no hosted backend;
  the Cloudflare tunnel is a capture convenience only. No paid API: the Claude
  vision backend exists but is off by default and untested.
- Hardware: RTX 5050 Laptop 8 GB (Blackwell sm_120), WSL2, torch 2.14+cu130.
  No flash-attn or xformers (no sm_120 wheels; xformers downgrades torch).
  `TORCH_COMPILE_DISABLE=1` and `TORCH_DISABLE_NATIVE_JIT=1` set in the package
  init because this machine has no Python headers for Triton. `HF_HUB_DISABLE_XET=1`
  for downloads.

## 3. Architecture

```
capture dir -> ingest -> metric y-up cloud + camera positions -> floor, walls, rooms, openings -> schema, intervals, damage, scope -> plan.json, plan.png
```

One shared representation (ADR-0001): every tier ends in a metric, y-up point
cloud plus camera positions in one world frame. All geometry consumes only that.

| module | job |
|---|---|
| `stray_scanner.py` | Stray Scanner export to cloud: every depth frame, confidence 2 only, OpenCV camera convention, upright frame extraction with pose adjustment |
| `depth_capture.py` | web page capture (ARCore) to cloud: full depth buffer per frame, grid cross-check, 6 m range cut |
| `multiview.py` | VGGT on photos or frames, chunked video, per-room stills, scale anchors (marker, MoGe-2 with FOV, poses), levelling |
| `plane_extraction.py` | RANSAC planes, floor and ceiling, Manhattan snap, outer wall face, single rectangle |
| `rooms.py` | density masks, doorway split, rectilinear room polygons, adjacency, doors and windows, per-room heights |
| `drift.py` | yaw drift from wall directions per window, orientation correction, ablation metrics |
| `intervals.py` | per-tier error model, interval on every measurement, basis named |
| `damage.py` | OWLv2 candidates, Qwen3-VL-2B crop classification, surface localisation, concealed rules, scope items |
| `pipeline.py` | assembles the plan per tier and per format, writes outputs |
| `server.py`, `web-capture/index.html` | upload page (WebXR on Android, file picker elsewhere), processing queue, results |
| `scripts/floorplan.py` | one command per capture, format detected from the folder |

Models used, all disclosed in plan.json: VGGT-1B via the vggt-low-vram fork
(FAIR non-commercial), MoGe-2 ViT-L (MIT), OWLv2 base (Apache 2.0), Qwen3-VL-2B-
Instruct (Apache 2.0). Geometry is classical (ADR-0003).

## 4. Tiers

### 4.1 LiDAR: Stray Scanner export

Format per scan: `rgb.mp4` 1920x1440 HEVC 60 fps, `depth/*.png` 256x192 uint16
millimetres, `confidence/*.png` 0 to 2, `odometry.csv` position plus quaternion
per frame, `camera_matrix.csv` for the RGB size, `imu.csv` 100 Hz (unused, the
poses are gravity aligned already).

Verified on the samples:
- Poses are camera-to-world in the OpenCV convention (x right, y down, z
  forward). Found by trying every axis assignment; only that one gives vertical
  walls and a floor 1.4 m below the phone.
- Frames are landscape sensor frames of a portrait capture: rotate 270 degrees
  clockwise, pose rotated by the opposite angle. Confirmed against VGGT on ten
  consecutive frames: 1 to 2 degree residual when right, 25 to 80 when wrong.
- Wall bands are 3 to 8 cm thick. Rooms found: 3, 6, 5. Per-room ceilings 294
  and 308 cm where the ceiling was scanned, reported as absent where not.
- Full run on the 9745-frame scan: about 8 to 12 minutes, 262 s of it LiDAR.

### 4.2 Depth: Android ARCore through the web page

Chrome on Android exposes ARCore through WebXR: `depth-sensing` (uint16 mm,
smooth only, no confidence, about 160x90, Chrome 90+), `camera-access` for
photos (Chrome 107+), video via a second canvas and MediaRecorder, poses every
frame. iOS Safari has no WebXR AR at all (still true in Safari 26.6), so on
iPhone the page is a file picker for photos and video.

Measured on the bedroom (145 frames): walls 421 x 372 cm against 427 x 366,
-1.3 and +1.8 percent after the fix loop; before it 393 x 314. Ceiling 302 cm
from wall extent against 312 (the ceiling itself was never seen). ARCore fills
textureless surfaces with flat depth biased toward the camera; tilted planes
are rejected, and the wall band, 30 to 66 cm thick, is placed at its outer face.

Seven other bedroom captures (15 to 27 frames, older 20x15 grid page, or frames
without depth) do not close a polygon. That is the repeatability finding.

### 4.3 Photos and video: VGGT plus a scale anchor

VGGT-1B returns relative geometry with good shape (aspect ratio within 2
percent of the tape). Everything is in the scale. Measured anchors on the
bedroom, against the tape-implied scale of 2.30:

| anchor | scale | walls | error |
|---|---|---|---|
| poses, rotate-in-place | 1.38 | 258 x 217 | -40 percent |
| ARCore depth per pixel | 2.49 | 465 x 391 | +8 percent |
| MoGe-2, own FOV estimate | 2.05 | 378 x 316 | -12, -14 percent |
| MoGe-2, FOV from projection, far half of frames | 2.28 | 416 x 352 | -2.6, -3.8 percent |
| one measured wall as reference | | other wall 361 (photos), 373 (video) | -1.3, +2.0 percent |

Decision (ADR-0002): scale priority is printed marker, then MoGe-2 with a
known FOV (projection matrix, or EXIF 35 mm focal length on phone photos), then
poses, then MoGe-2 with its own FOV. Poses always give orientation and
placement when present. Video runs in chunks of 16 consecutive frames at 2 fps,
each chunk aligned to its own poses; frames pitched more than 50 degrees off
horizontal are skipped. Photo sets are reconstructed per room and placed by
pose. Without poses the cloud is levelled from the mean camera up axis.

Frame density is not a lever: 1 fps gives -4.6 and -2.6 percent, 4 fps -1.5
and -3.6 percent at 11.9 GB, past the card.

Literature check (2026-09-20): best zero-shot indoor metric depth is 6 to 7
percent relative error (Metric3Dv2, UniDepthV2, DA3 metric), MoGe-2 7.3
percent without intrinsics, multi-view metric models 9 to 32 percent. No
published method reaches 1 percent room dimensions from RGB alone. A physical
reference does: calibrated scale bars 0.1 to 0.3 percent, printed board or A4
sheet 0.3 to 1 percent, one laser length as a constraint. The graders' laser
is 0.04 percent. Sub-percent from pixels alone is not achievable and the report
says so.

Implemented references: a printable 150 mm ArUco marker
(docs/scale-marker-a4.png) detected in the photos and read off the point map,
unit-tested on a synthetic point map, not tested on a real photo (the user
cannot print one); and `--reference-length-cm` for one measured wall.

## 5. Multi-room segmentation

From a y-up cloud with a known floor: rotate to the dominant wall direction
(Hough on tall points); rasterise at 3 cm; a cell is wall if occupied in at
least 3 of 4 half-metre bands between floor+0.2 and floor+2.2 (furniture fails
the top, ceiling fails the bottom); free space is every occupied non-wall cell,
closed and hole-filled; erode past a doorway half width (0.55 m) for room cores,
a second erosion at 0.30 m seeds corridors, grow back; per room open and close
the mask with 25 cm, trace, classify edges by axis, remove edges under 30 cm by
merging their perpendicular neighbours, intersect consecutive lines; adjacency
from touching regions, doorway up to 1.5 m, open beyond; doors and windows as
gaps along each edge in the full and upper height bands; per-room floor and
ceiling from the point height histogram, a ceiling must be a dense layer with
nothing above it.

Known gaps: rooms scanned only from the doorway get the scanned footprint;
open plans split arbitrarily; doorway widths from region contact overshoot when
the shared wall was not scanned; no windows to the outside are verified against
tape.

## 6. Drift accountability

Heading drift is measured as the deviation of each 5 second window's dominant
wall direction from the first window's, folded to 90 degrees; a linear fit gives
the rate; poses are rotated about vertical by the negative fitted drift.
Orientation only, no loop closure claimed. Ablation writes footprint metrics
with correction off and on. single_room: 1.9 degrees per minute, 0.84 degrees
maximum correction, footprint unchanged within noise.

## 7. Damage, flags, scope

OWLv2 proposes candidate boxes for four classes at a low threshold; Qwen3-VL-2B
looks at each crop and answers crack, water_stain, mould, peeling_paint or none;
the answer decides. Metric extent from the box cast onto the room surface at the
hit distance, or the depth frame when one exists. Concealed-damage rules are
named in the output. Scope items: one line per surface with area, one repair
line per region.

Tested: Cozmo's single_room bathroom has a real 60 cm crack; found and labelled
crack. The undamaged bedroom yields zero regions. Six floor "water stain" calls
on the two flats are unverified by eye. Water stains, mould and peeling paint
have no positive test image. Peak VRAM 4.5 GB, about 1 s per crop.

Survey behind the choice: no released weights cover all four classes; crack-only
segmenters exist (AGPL or unlicensed); Qwen2.5-VL-3B is non-commercial and 7.5
GB; DefectBench places Qwen3-VL near much larger models on building pathology.

## 8. Intervals

Per-tier error model: absolute floor plus relative term plus an alignment term
for view models, on lengths, heights, areas, openings and damage extents.
Priors named in `interval_basis`; the depth prior was reset after the fix loop
to the residual measured (walls within 2 percent, ceiling -11 cm). One room is
not enough to fit intervals; they are priors and the report says so.

## 9. Fix loop

Worst gate: depth-tier wall lengths, -7.9 and -14.2 percent. Root cause with
evidence: every wall band extends 20 to 50 cm outward from the RANSAC line, all
on the room side of the true wall; the outward 80th percentiles sum to the
missing 34 and 52 cm. Fix: for bands thicker than 15 cm, place the wall at the
80th percentile of the band's outward spread (`--wall-face outer`, default).
Predicted within 3 percent; measured -1.3 and +1.8 percent; LiDAR samples
unchanged. Caveat stated: set on the same capture, no second closed capture to
confirm. Before and after regenerable, outputs in data/fixloop.

## 10. Results table

| capture | tier | walls vs tape | ceiling | notes |
|---|---|---|---|---|
| bedroom 145 frames | depth | -1.3, +1.8 percent | -10.6 cm | fix loop applied |
| bedroom | photos, poses | -2.6, -3.8 percent | none | MoGe with FOV |
| bedroom | video | -4.6, -2.6 percent | none | chunked, MoGe with FOV |
| bedroom | photos, no poses | -7.4, -9.0 percent | none | MoGe own FOV, levelled |
| bedroom, 7 sparse captures | depth | no polygon | | repeatability fails to score |
| single_room | lidar | no tape | not scanned | 3 rooms, crack found |
| single_scan_floor_only | lidar | no tape | not scanned | 6 rooms |
| single_scan_with_ceiling | lidar | no tape | 294, 308 per room | 5 rooms |

No gate passes. The depth tier is closest. The report presents exactly this.

## 11. Process

64 commits over two days, one change each. Review pass with the repo skills:
path traversal closed, zip checked before extraction, depth tier through the
multi-room path, VGGT loaded once, dead code removed, ruff clean, pip-audit
clean. Spec, task list, constraints, glossary and five decision records in the
repo.

## 12. Open items

Needs the user: door and window widths for the openings gate; a second bedroom
capture that closes, for repeatability; a CubiCasa LITE scan for the head-to-head.
The marker test is not possible for the user. Needs no one: clean-machine
timing of scripts/setup.sh, final report read against docs/benchmark.md, a look
at the six floor stain calls. Not built: whole-property stitching of per-room
photo folders without poses.
