# ADR-0003: classical geometry (Open3D, OpenCV) for rooms, no learned floor plan model

## Status
Accepted

## Context
RoomFormer, PolyRoom, HEAT and SpatialLM produce vectorised floor plans from
point clouds and would replace the density-mask pipeline.

## Decision
Rooms come from density masks, a doorway split by erosion, contour tracing and
rectilinear simplification. Walls come from RANSAC plus Manhattan snapping.

## Alternatives considered
- RoomFormer (MIT, weights): deformable-attention CUDA ops from the torch 1.9
  era, unverified on sm_120, and it needs a density map we already compute.
- PolyRoom: no license, MMDetection stack.
- SpatialLM: needs flash-attn, which has no sm_120 build.
- RoomPlan: iOS only, no intermediates.

## Consequences
Every step is inspectable and testable on synthetic rooms with known
dimensions. Non-rectilinear rooms are out of scope. If a learned model is
added later it slots in as an alternative to `segment_rooms` with the same
input and output.
