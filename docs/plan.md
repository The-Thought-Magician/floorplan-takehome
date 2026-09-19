# Floor plan reconstruction: research and architecture plan

## Problem

Input: phone camera captures of a room or property, in one of three tiers.
Output: a dimensioned floor plan (wall layout, room outline, measurements in cm),
stitched across the full capture, accurate to the centimeter.

Tiers, in order of increasing raw signal quality:

1. Photos: a sparse set of unordered stills.
2. Video: a continuous handheld walkthrough.
3. LiDAR: depth-sensing capture from an iPhone/iPad Pro (ARKit scene reconstruction).

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

## Tier 3: LiDAR

Highest confidence, build this first.

Input: ARKit `ARMeshAnchor` scene mesh, or raw `sceneDepth` + camera poses per frame.
Both give real-world metric scale directly, no scale ambiguity.

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
USDZ with labeled walls, openings, and dimensions. Worth being explicit in the
write-up that `RoomPlan` is the "buy" option for this tier, and the case for
building it ourselves is control over the intermediate point cloud (needed if we
ever want confidence scores, custom room labels, or multi-tier fusion) plus not
being locked into iOS-only capture apps.

## Tier 2: Video

No direct depth, but many overlapping frames.

Approach: visual SLAM / structure-from-motion over the frame sequence.
- Extract frames at a fixed interval, keep ones with enough parallax.
- Feature detection and matching across consecutive frames (ORB or SIFT).
- Estimate relative camera poses (essential matrix, RANSAC), chain into a
  trajectory, then triangulate 3D points from matched features.
- Bundle adjustment to reduce drift across the whole trajectory.
- Loop closure if the walkthrough returns to a previously seen area (needed for
  "stitched" multi-room plans).
- Fixing scale: monocular SLAM only gives structure up to an unknown scale factor.
  Options: use phone IMU (visual-inertial odometry, most video capture apps already
  fuse this), ask for one reference measurement (a door is close to 80cm, a person's
  height), or detect a known-size object in frame.
- Once a scaled point cloud exists, the plane-fitting and polygon-extraction steps
  from the LiDAR tier apply unchanged.

Libraries: COLMAP (full SfM pipeline, can be driven from Python), OpenCV for feature
matching and pose estimation if a lighter custom pipeline is preferred over COLMAP.

## Tier 1: Photos

Same underlying math as video (SfM), but harder because frames are sparse and
unordered: no guaranteed overlap between any two photos, matching has to run on
all pairs or a similarity-indexed subset, and there are more failure modes (too
few shared features between two photos of the same room from different corners).

Approach is COLMAP's standard pipeline: exhaustive or vocabulary-tree feature
matching across all photo pairs, incremental reconstruction (start from the best
pair, add one image at a time, bundle-adjust as you go). Same scale ambiguity and
fix as the video tier.

This tier has the lowest achievable accuracy and the highest chance of outright
failure (not enough overlap, too few photos, textureless walls with no features to
match). The write-up should be explicit that this tier is best-effort, and the
system should report a confidence score and fail loudly rather than emit a
plausible-looking but wrong floor plan.

## Scale strategy summary

| tier | scale source |
|---|---|
| LiDAR | ARKit metric depth, exact |
| video | IMU fusion (preferred) or a reference measurement |
| photos | a reference measurement or a known-size object, required |

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

- LiDAR tier: consider Apple `RoomPlan` as the primary path for iOS capture apps,
  keep a custom Open3D pipeline as the fallback for raw point cloud exports and for
  cases needing confidence scoring or multi-room fusion RoomPlan does not expose.
- Video and photo tiers: COLMAP for the SfM core rather than reimplementing bundle
  adjustment. Custom code sits around it for scale-fixing, plane extraction, and
  schema conversion.
- Plane segmentation and point cloud utilities: Open3D throughout, do not hand-roll.

## Evaluation strategy

- Ground truth: capture a real room with a tape measure, compare reconstructed wall
  lengths and room area against the measured values.
- Per-tier accuracy targets: LiDAR should land within a couple of cm given it has
  direct metric depth; video and photo tiers depend entirely on how well scale gets
  fixed and should be evaluated separately with that caveat stated.
- Track failure rate, not just accuracy on captures that succeeded: report what
  fraction of test captures produce no usable output at all, especially for the
  photo tier.

## Risks and edge cases

- Non-rectangular rooms, curved walls, sloped ceilings: plane-fitting assumptions
  break down, needs explicit handling or explicit non-support.
- Reflective or textureless surfaces (glass, blank drywall): feature matching fails
  for video/photo tiers, LiDAR depth can also be noisy or missing on glass.
- Multi-room stitching: requires loop closure and global registration, meaningfully
  harder than single-room reconstruction, worth scoping down to single-room first
  if time is short.
- Moving furniture or people during capture: violates the static-scene assumption
  SfM and SLAM depend on.

## Execution plan if implementing in one day

1. Common schema and plane/polygon extraction module first, since every tier
   depends on it. Test against a synthetic point cloud (a cube) before touching
   real data.
2. LiDAR tier next: highest chance of a working end-to-end demo by end of day.
3. Video tier if time allows, using COLMAP as the SfM backend rather than a custom
   matcher, to keep scope realistic.
4. Photo tier last, and only as a best-effort path with explicit failure reporting,
   not a fully polished feature.
5. A CLI or simple script wrapping the pipeline is enough; a UI is out of scope
   unless explicitly asked for.
