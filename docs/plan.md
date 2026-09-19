# Floor plan reconstruction: research and architecture plan

## Problem

Input: phone camera captures of a room or property, in one of three tiers.
Output: a dimensioned floor plan (wall layout, room outline, measurements in cm),
stitched across the full capture, accurate to the centimeter.

Tiers, in order of increasing raw signal quality:

1. Photos: a sparse set of unordered stills.
2. Video: a continuous handheld walkthrough.
3. Sensor-assisted depth: real-time depth captured at record time, not
   reconstructed after the fact. LiDAR on Apple Pro devices (ARKit scene
   reconstruction), or ARCore Depth API depth-from-motion on Android. Kept the
   name "LiDAR" in the rest of this doc for brevity, but the pipeline is the
   same for either source, see below.

## Common output schema

All three tiers should converge on the same output representation, so downstream
consumers (Xactimate-style estimate generation) do not care which tier produced it:

```
FloorPlan
  rooms: list[Room]
Room
  id, label
  polygon: list[(x_cm, y_cm)]   # wall corners, closed loop, in a shared world frame
  wall_height_cm: float
  openings: list[Opening]        # doors, windows: wall_id, position, width_cm
  confidence: float              # per-room reconstruction confidence
  source_tier: photos | video | lidar
```

A single schema means the reconstruction algorithm can change per tier while the
rest of the system (rendering, estimate generation, QA review) stays fixed.

## Tier 3: LiDAR (and its Android equivalent)

Highest confidence, build this first.

Most customers will not have an Apple Pro device. LiDAR (`ARMeshAnchor`,
`sceneDepth`) is exclusive to iPhone/iPad Pro models, non-Pro iPhones have no
software fallback for it in ARKit, this is a hard hardware gate on iOS.

Android does not need special hardware for the equivalent. ARCore's Depth API
computes depth-from-motion from a single moving camera fused with IMU, no ToF
sensor required, and covers roughly 88 percent of active ARCore-certified
Android devices (400+ models: Samsung, Pixel, OnePlus, Xiaomi, and others,
Android 7.0+). Its pose tracking is confirmed metric-scale (camera plus IMU
visual-inertial odometry, benchmarked around 1.6-4cm indoor position error),
which is the same class of accuracy this whole project is targeting. The
depth values themselves inherit that scale since they come from the same
tracked camera poses, though Google's own docs describe the depth-specific
accuracy qualitatively rather than as a hard confirmed number, worth verifying
directly against a tape measure like everything else in this plan.

So tier 3 in practice has two real sources feeding the same pipeline: ARKit
LiDAR on Apple Pro devices, ARCore Depth API on most Android devices. Non-Pro
iPhones are the one real gap, no on-device metric depth exists there, capture
from those falls through to the tier 1/2 feed-forward pipeline instead.

Capture path on Android needs no installed app. Chrome's WebXR Depth Sensing
module ships (not experimental) ARCore's Depth API directly to a website via
`navigator.xr.requestSession()`, no native app to build or ask the customer to
install. Google Play Services for AR, the ARCore runtime itself, auto-installs
in the background the first time it is needed, the user never has to find or
install it manually. No off-the-shelf third-party app does real ARCore depth
capture in a usable form either (checked: the closest comparable app,
SiteScape, is LiDAR-only and explicitly does not support Android), so a
browser-based capture page is both the least-friction and the only realistic
path, not a corner cut for lack of a better option. iOS has no equivalent for
LiDAR in Safari's WebXR support as of this research, native app or a hybrid
wrapper is still needed there.

Input: ARKit `ARMeshAnchor` scene mesh or raw `sceneDepth` plus camera poses,
or ARCore's per-frame depth image plus tracked pose. Both give real-world
metric scale directly, no scale ambiguity.

Pipeline:
1. Load mesh or depth point cloud, transform into a single world frame using the
   ARKit-provided camera poses (already solved on-device, no SLAM needed here).
2. Filter and downsample the point cloud (voxel grid).
3. Segment the floor plane and ceiling plane (RANSAC plane fitting, Open3D
   `segment_plane`). Points within a horizontal band between the two give wall
   candidates.
4. Segment wall planes from the remaining points (iterative RANSAC, remove each
   plane's inliers and repeat).
5. Project wall planes to 2D (top-down), intersect adjacent walls to get corner
   points, order them into a closed polygon.
6. Detect openings (doors/windows) as gaps or depth discontinuities in a wall plane.
7. Compute room area and wall lengths directly from the polygon in metric units.

Apple's own `RoomPlan` framework already does steps 1 to 6 on-device and outputs a
USDZ with labeled walls, openings, and dimensions, but it is iOS-only, no Android
equivalent product exists. This is the actual case for building our own pipeline
rather than depending on RoomPlan: it is the only option that works on both ARKit
LiDAR and ARCore depth-from-motion input, plus it gives control over the
intermediate point cloud (needed for confidence scores, custom room labels, or
multi-tier fusion) instead of being locked into one platform's capture app.

## Tier 2: Video, and Tier 1: Photos

Classic SfM (COLMAP: feature matching, essential matrix, incremental
reconstruction, bundle adjustment) is the textbook approach here, but it is not
the current state of the art and not the right default for a fast build. As of
2024-2025 there is a class of feed-forward transformer models that take
unordered, unposed images or video frames and directly regress a point cloud
plus camera poses in a single forward pass, no matching or iterative
optimization loop at all:

- **VGGT** (Meta, CVPR 2025): 1 to ~200 unordered images in, dense point cloud
  and poses out, under a second on a GPU. Relative scale only. Runs from a
  pretrained checkpoint, has a hosted demo (`facebook/vggt` on Hugging Face
  Spaces).
- **MASt3R** (Naver): pairwise dense point-map regression plus a matching head,
  extends DUSt3R with metric-scale recovery. Metric scale out of the box, but
  a real reported number puts it at 11.8GB for 19 images on an RTX 3080, a
  confirmed no-go on 8GB at any useful image count, not just an unverified
  paper figure this time.
- **MapAnything** (Meta, 2025): unified feed-forward model, explicitly built
  for metric 3D reconstruction, optionally takes known calibration/poses/depth
  as extra input if available and folds it in. Apache 2.0, weights on Hugging
  Face (`facebook/map-anything-v1`). No consumer VRAM number in its own README
  at all, only a 2000-views-on-140GB memory-efficient-mode figure, no way to
  extrapolate to 8GB from that.
- **MUSt3R** (Naver, CVPR 2025, DUSt3R successor): 5x lighter and an order of
  magnitude faster than DUSt3R at similar accuracy. A 2025 survey benchmarks
  MUSt3R-224 at 4.1GB and MUSt3R-512 at 8.1GB, real headroom under 8GB rather
  than borderline, though still an A100 figure, not a confirmed consumer-card
  number. Pip-installable, pretrained checkpoints included. Scale: not stated
  as metric anywhere found, same lineage as DUSt3R/VGGT, assume relative and
  pair with a DepthPro anchor unless proven otherwise.
- **Fast3R** (Meta, CVPR 2025): all-images-at-once generalization of DUSt3R,
  scales to 1000+ images, very fast, relative scale.

This is a real workaround, not a minor optimization: COLMAP needs enough
pairwise feature overlap and minutes to hours of matching plus bundle
adjustment; VGGT/MapAnything need no matching step, no ordering, and run in
under a second to seconds per capture. For a sparse, unordered photo set this
directly removes the failure mode that made the photo tier "best-effort" in a
COLMAP-based design: COLMAP fails outright when two photos of the same room
do not share enough matched features, feed-forward models degrade gracefully
instead because they never depend on explicit pairwise matches.

Plan: use MUSt3R-224 (confirmed real headroom under 8GB) or `vggt-low-vram`
as the default reconstruction backend for both the photo and video tiers on
the local 8GB card. MapAnything and MASt3R are named because they are the
strongest metric-scale candidates on paper, but neither has real 8GB evidence
and MASt3R now has a directly disconfirming one, so they are a fallback to
test only if the 8GB-confirmed options come up short on accuracy, not the
first thing to reach for. Video frames are just a densely sampled, ordered
image set to this class of model, so one backend covers both tiers, the only
difference is frame extraction (fixed interval sampling with a parallax check
for video) versus using photos directly.

Scale: none of the 8GB-confirmed options (MUSt3R, VGGT) are metric out of the
box, both are relative-scale by lineage. Fix with a metric depth anchor: run a
single-image metric depth model (Apple **DepthPro**, or **UniDepth**, or
**Metric3D v2**, all give true-scale depth from one frame with no calibration
needed) on one reference frame and rescale the point cloud to match. This is a
cleaner scale fix than the old IMU-fusion/known-object approach: it needs no
capture-time cooperation from the user and no assumption about what is in
frame. If MapAnything or MASt3R get tested later and their metric claim holds
up, the DepthPro anchor step can be dropped for those paths.

Once a point cloud and poses exist, from either tier, the plane-fitting and
polygon-extraction step is shared with the LiDAR tier below. Also worth
building toward: **PolyRoom** (ECCV 2024 lineage), a transformer that goes
directly from a point cloud to a clean vectorized floor-plan polygon, built
specifically to fix the corner/angle/self-intersection errors that hand-rolled
RANSAC plane intersection produces. Start with the RANSAC-based extractor
since it is faster to get working, treat PolyRoom as the upgrade path.

Multi-room stitching ("stitched" floor plans): this whole model class handles
it natively for a single continuous capture since all frames go through one
forward pass into one shared point cloud, no separate loop-closure step
needed the way classic SLAM requires it.

Libraries: `must3r` (pip-installable, pretrained checkpoints) and
`harry7557558/vggt-low-vram` as the primary 8GB-viable options, `map-anything`
kept installed as the metric-scale fallback to test. OpenCV for frame
extraction and any lightweight preprocessing, Open3D for plane fitting on the
resulting point cloud. COLMAP is not required for the default path, keep it
noted as a fallback only if every feed-forward option fails to load or is
unavailable in the actual take-home environment.

## Scale strategy summary

| tier | scale source |
|---|---|
| LiDAR (Apple Pro) | ARKit metric depth, exact |
| depth-from-motion (Android) | ARCore VIO-fused metric depth, verify accuracy |
| video | MUSt3R/VGGT relative output, fixed with a DepthPro anchor |
| photos | MUSt3R/VGGT relative output, fixed with a DepthPro anchor |

## Architecture

```
capture ingestion  ->  tier detection  ->  reconstruction  ->  plane/polygon extraction  ->  schema output  ->  render / export
```

- Capture ingestion: accepts a folder of images, a video file, or an ARKit export
  bundle. Normalizes into frames + optional depth + optional poses.
- Tier detection: based on what's present in the capture (depth data present means
  LiDAR tier, single video file means video tier, loose image set means photo tier).
- Reconstruction: tier-specific module (three separate implementations sharing a
  point-cloud-out interface).
- Plane and polygon extraction: shared across all three tiers, operates on a point
  cloud plus (if available) camera poses.
- Schema output: the `FloorPlan` structure above, tier-tagged and confidence-scored.
- Render/export: 2D floor plan image, dimension overlay, and a machine-readable
  export (JSON) for downstream estimate generation.

Module boundaries matter here because the interesting long-term work (per the JD)
is the data layer: every capture should produce structured points that outlive the
one-off reconstruction, not just a picture of a floor plan.

## Build vs buy

- LiDAR tier: a custom Open3D pipeline, not `RoomPlan`, since RoomPlan is
  iOS-only and this project needs one pipeline covering both ARKit LiDAR and
  ARCore depth-from-motion. RoomPlan's confirmed accuracy (1-3cm, from real
  measurement studies, explicitly not sufficient for permit-grade drawings) is
  still a useful reference target even though it is not being used directly.
- Android capture: browser-based, WebXR Depth Sensing in Chrome, not a native
  app. No install friction, no separate SDK integration to maintain.
- Video and photo tiers: MUSt3R or `vggt-low-vram` as the reconstruction core
  on the local 8GB card, a pretrained checkpoint, not a from-scratch model and
  not a from-scratch SfM pipeline. MapAnything/MASt3R as a metric-scale
  fallback to test, not the default, given the VRAM findings above. Custom
  code sits around whichever backend for frame sampling, scale verification,
  plane extraction, and schema conversion.
- Plane segmentation and point cloud utilities: Open3D throughout, do not hand-roll.
- Polygon extraction: start with RANSAC plane intersection in Open3D, PolyRoom
  as a later upgrade if time allows and the hand-rolled version is producing
  bad corners.

## Evaluation strategy

- Ground truth: capture a real room with a tape measure, compare reconstructed wall
  lengths and room area against the measured values.
- Per-tier accuracy targets: LiDAR should land within a couple of cm given it has
  direct metric depth; video and photo tiers depend entirely on how well scale gets
  fixed and should be evaluated separately with that caveat stated.
- Track failure rate, not just accuracy on captures that succeeded: report what
  fraction of test captures produce no usable output at all.
- Whichever scale path is used (DepthPro anchor by default, or MapAnything's
  native metric claim if it gets tested), verify directly against a tape
  measure rather than trusting a paper's general benchmark. This is the single
  most important thing to check early.

## Risks and edge cases

- Non-rectangular rooms, curved walls, sloped ceilings: plane-fitting assumptions
  break down, needs explicit handling or explicit non-support.
- Reflective or textureless surfaces (glass, blank drywall): classic feature
  matching fails here, feed-forward models are more robust to this but not
  immune, LiDAR depth can also be noisy or missing on glass.
- Moving furniture or people during capture: violates the static-scene
  assumption every one of these methods depends on, feed-forward models
  included.
- GPU memory: the paper figures for VGGT (5.6GB at 20 views) do not hold up in
  practice. Real user reports on the official repo show OOM on an 8GB RTX 4070
  with 6 images, and even OOM on a 24GB RTX 4090 with 10 images, far past the
  paper's claim. Do not trust paper VRAM numbers, test directly on the actual
  card. Use `harry7557558/vggt-low-vram` (claims 150 images on 8GB) rather than
  stock VGGT, or MUSt3R-224 (a real benchmark puts it at 4.1GB, more headroom
  than VGGT's own figures). MASt3R has a confirmed disconfirming number,
  11.8GB for 19 images on an RTX 3080, treat 8GB as a real no-go for it, not
  just unverified. MapAnything's README gives no consumer VRAM number at all
  (only a 2000-views-on-140GB figure), still fully unverified at 8GB, profile
  it directly before relying on it (it ships
  `scripts/profile_memory_runtime.py` for exactly this) rather than assuming
  either way.
- If 8GB genuinely cannot fit the target image count even with the low-VRAM
  fork, fall back to a rented cloud GPU for that run, or reduce input
  resolution and image count and accept a lower-confidence reconstruction.

## Execution plan

Building all three tiers for real is the target, not a fallback to "design
only." A pretrained feed-forward model plus AI-assisted implementation makes
this a day of integration work, not a multi-month research project.

1. Common schema and plane/polygon extraction module first, since every tier
   depends on it. Test against a synthetic point cloud (a cube) before touching
   real data.
2. LiDAR tier next: direct metric depth, fastest path to a working end-to-end
   demo, and a correctness reference for the other two tiers.
3. Photo and video tiers together, same backend: run `vggt-low-vram` or
   MUSt3R-224 on the local 8GB card first, both have real evidence of fitting
   (stock VGGT and MASt3R do not, do not use either directly at 8GB). Confirm
   point cloud and pose output, then reuse the tier-3 plane/polygon extractor
   on the result. Fall back to a rented cloud GPU only if the local card
   cannot fit a usable image count even with these options, or if MapAnything
   needs testing for its metric-scale claim.
4. Add the DepthPro single-frame anchor and rescale, since neither
   `vggt-low-vram` nor MUSt3R is metric out of the box. Verify the rescaled
   result against the LiDAR/ARCore tier or a tape measure immediately, do not
   assume any paper's numbers hold for this use case.
5. A CLI or simple script wrapping the pipeline is enough; a UI is out of scope
   unless explicitly asked for.
6. If time remains: PolyRoom-based polygon extraction as an upgrade over the
   RANSAC version, and a documented COLMAP fallback path for a no-GPU
   environment.
