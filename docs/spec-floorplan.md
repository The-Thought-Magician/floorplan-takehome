# Spec: floor plans from phone captures

Written after the fact against the Cozmo case study (Applied AI.pdf), per the
spec-and-planning skill. Assumptions first, then the spec, then the capability
map that drives docs/todo.md.

ASSUMPTIONS:
1. The walk-in capture arrives as a Stray Scanner export (LiDAR), a Camera app
   video, or per-room photo folders. No poses come with photos or video.
2. Interior walls are vertical and rooms are rectilinear (Manhattan). Curved
   or angled walls are out of scope and reported as such.
3. One floor level per capture, one ceiling height per room.
4. The pipeline runs on the author's laptop (8 GB GPU) at the defense; nothing
   calls a remote service unless a key is present, and by default none is.
-> proceeding with these.

## Objective

Turn a phone capture of a property into a dimensioned, stitched floor plan
with intervals on every number, at three input tiers, with damage regions and
scope lines, in one command. Success is the gate table in the case study;
honest failure with the number stated is the fallback.

## Approach

One shared internal representation: a metric, y-up point cloud plus camera
positions. Three ingest paths produce it (LiDAR export, ARCore web page, view
model on images), one geometry path consumes it (floor, wall bands, room
masks, rectilinear polygons, openings), one contract path formats it
(schema, intervals, damage, scope). Alternatives rejected: RoomPlan (iOS
only, no control of intermediates), COLMAP (fails on textureless rooms, slow),
end-to-end learned floor plan models (weights either unavailable or CUDA ops
that will not build on this GPU). Details and dates in docs/plan.md and
docs/decisions/.

## Interfaces

- Ingest -> geometry: `(points (n,3) metres y-up, cameras (m,3))`, plus for
  the depth tiers the per-frame poses used to build it.
- Geometry -> contract: rooms with rectilinear corners in metres, per-room
  floor and ceiling heights, openings per wall, adjacency with contact widths,
  diagnostics (planes, walls, drift estimate and ablation).
- Contract -> consumer: plan.json (schema in README), plan.png, summary.json,
  damage.json. The tier only changes `source_tier`, `scale_used` and the
  interval model.
- Capture -> ingest: a directory. Format detected from contents (odometry.csv
  and depth/, or capture.json, or photos/ and video.*).

## Testing

- Synthetic rooms with known dimensions: 3 x 4 m rectangle to 0.3 m2 area,
  two rooms joined by a 0.9 m doorway split into two with the door found,
  door 90 cm and window 120 cm on known walls within 10 cm, drift of 1.2
  degrees per second recovered within 5 degrees per minute.
- Real reference values: bedroom tape 426.7 x 365.8 cm, ceiling 312.4 cm.
  Every tier's number against those is in docs/benchmark.md.
- Format conventions verified empirically, not assumed: Stray Scanner poses
  are OpenCV, frames need a 270 degree rotation, VGGT pairs with the opposite
  pose rotation (1 to 2 degree residual when right, 25 to 80 when wrong).

## Out of scope

Native iOS app, curved walls, multi-level floors, furniture detection,
mirror phantom detection, live UI beyond the capture page, calibration of
intervals from more than one room (no more rooms exist).

## Open questions

- Whole-property stitching of per-room photo folders without poses: needs
  doorway photos shared between rooms and a chained alignment. Not built.
- The 80th percentile wall face was set on one room; a second closed capture
  is needed to confirm or refute it.
- Damage classes other than crack have no positive test image.

## Capability map

| id | responsibility | depends on | status |
|---|---|---|---|
| C1 ingest-lidar | Stray Scanner export to cloud plus poses | none | done |
| C2 ingest-arcore | web page capture to cloud plus poses | none | done |
| C3 ingest-images | VGGT on photos or frames, scale from poses, ARCore depth or MoGe-2 | C2 for anchors | done |
| C4 geometry-single | RANSAC planes, Manhattan walls, outer face, rectangle | C1 or C2 or C3 | done |
| C5 geometry-rooms | masks, doorway split, rectilinear polygons, openings, per-room heights | C4 floor | done |
| C6 drift | yaw drift estimate, correction, ablation | C1 | done |
| C7 contract | schema, intervals, damage, scope, render | C4, C5 | done |
| C8 transport | server, page, one-command CLI, setup scripts | C7 | done |
| C9 evaluation | ground truth files, benchmark report, fix loop | C7 | done, one room |
| C10 poseless stitch | multi-room from photo folders without poses | C3, C5 | not built |
