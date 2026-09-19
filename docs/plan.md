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
  extends DUSt3R with metric-scale recovery. Metric scale out of the box.
- **MapAnything** (Meta, 2025): unified feed-forward model, explicitly built
  for metric 3D reconstruction, optionally takes known calibration/poses/depth
  as extra input if available and folds it in. Apache 2.0, weights on Hugging
  Face (`facebook/map-anything-v1`).
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

Plan: use MapAnything (metric output, actively maintained, explicit case for
this exact problem) as the primary reconstruction backend for both the photo
and video tiers. Video frames are just a densely sampled, ordered image set to
this class of model, so one backend covers both tiers, the only difference is
frame extraction (fixed interval sampling with a parallax check for video)
versus using photos directly.

Scale: MapAnything and MASt3R claim metric output directly. Treat that as
unverified until checked against a tape-measure ground truth (the papers'
benchmarks are not room-reconstruction-specific). If metric output drifts,
fall back to a metric depth anchor: run a single-image metric depth model
(Apple **DepthPro**, or **UniDepth**, or **Metric3D v2**, all give true-scale
depth from one frame with no calibration needed) on one reference frame and
rescale the point cloud to match. This is a cleaner scale fix than the old
IMU-fusion/known-object approach: it needs no capture-time cooperation from
the user and no assumption about what is in frame.

Once a point cloud and poses exist, from either tier, the plane-fitting and
polygon-extraction step is shared with the LiDAR tier below. Also worth
building toward: **PolyRoom** (ECCV 2024 lineage), a transformer that goes
directly from a point cloud to a clean vectorized floor-plan polygon, built
specifically to fix the corner/angle/self-intersection errors that hand-rolled
RANSAC plane intersection produces. Start with the RANSAC-based extractor
since it is faster to get working, treat PolyRoom as the upgrade path.

Multi-room stitching ("stitched" floor plans): VGGT/MapAnything handle this
natively for a single continuous capture since all frames go through one
forward pass into one shared point cloud, no separate loop-closure step
needed the way classic SLAM requires it.

Libraries: `map-anything` (pip-installable, Hugging Face checkpoint), OpenCV
for frame extraction and any lightweight preprocessing, Open3D for plane
fitting on the resulting point cloud. COLMAP is not required for the default
path, keep it noted as a fallback only if a feed-forward model checkpoint
fails to load or is unavailable in the actual take-home environment.

## Scale strategy summary

| tier | scale source |
|---|---|
| LiDAR (Apple Pro) | ARKit metric depth, exact |
| depth-from-motion (Android) | ARCore VIO-fused metric depth, verify accuracy |
| video | MapAnything/MASt3R metric output, verify against a DepthPro anchor |
| photos | MapAnything/MASt3R metric output, verify against a DepthPro anchor |

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

- LiDAR tier: consider Apple `RoomPlan` as the primary path for iOS capture apps.
  Confirmed accuracy from real measurement studies: 1-3cm, explicitly not
  sufficient for permit-grade drawings. Keep a custom Open3D pipeline as the
  fallback for raw point cloud exports and for cases needing confidence scoring
  or multi-tier fusion RoomPlan does not expose.
- Video and photo tiers: MapAnything (or VGGT plus a DepthPro metric anchor) as
  the reconstruction core, a pretrained checkpoint, not a from-scratch model and
  not a from-scratch SfM pipeline. Custom code sits around it for frame
  sampling, scale verification, plane extraction, and schema conversion.
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
- The metric-scale claims for MapAnything/MASt3R are from the papers' general
  benchmarks, not room-reconstruction-specific. Verify directly rather than
  trusting the claim, this is the single most important thing to check early.

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
  paper's claim. Do not trust the paper's VRAM numbers, test directly on the
  actual card. A community fork, `harry7557558/vggt-low-vram`, exists
  specifically for this problem (attention-output memory reduction, explicit
  fp16/bf16, `torch.cuda.empty_cache()`, `torch.compile`) and claims 150 images
  on 8GB. Use that fork as the 8GB path rather than stock VGGT. No public 8GB
  data point exists for MapAnything or MASt3R, treat that as unverified and
  profile it directly before relying on it (MapAnything ships a
  `scripts/profile_memory_runtime.py` for exactly this).
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
3. Photo and video tiers together, same backend: run on the local 8GB card
   first, MapAnything if it profiles clean at the target image count,
   `vggt-low-vram` if not (stock VGGT is not reliable at 8GB per real user
   reports, do not use it directly). Confirm point cloud and pose output, then
   reuse the tier-3 plane/polygon extractor on the result. Verify metric-scale
   claims immediately against the LiDAR/ARCore tier or a tape measure, do not
   assume the papers' numbers hold for this use case. Fall back to a rented
   cloud GPU only if the local card cannot fit a usable image count even with
   the low-VRAM path.
4. If MapAnything's metric output is off, add the DepthPro single-frame anchor
   and rescale.
5. A CLI or simple script wrapping the pipeline is enough; a UI is out of scope
   unless explicitly asked for.
6. If time remains: PolyRoom-based polygon extraction as an upgrade over the
   RANSAC version, and a documented COLMAP fallback path for a no-GPU
   environment.
