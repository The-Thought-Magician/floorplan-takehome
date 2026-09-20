# ADR-0002: scale for view-model tiers comes from poses, then ARCore depth, then MoGe-2

## Status
Accepted

## Context
VGGT returns geometry at relative scale. The case study scores metric
accuracy. Captures arrive with poses (Stray Scanner, capture page), with depth
per photo (capture page), or with nothing (iPhone Camera app).

## Decision
Priority order, chosen per capture from what exists:
1. Recorded poses: similarity transform from camera orientations (Procrustes)
   and pairwise centre distances (median ratio). Used for walking captures.
2. ARCore depth per pixel against VGGT depth on the same photo: used when the
   capture page recorded depth for the photos. Beats the pose fit on a
   rotate-in-place capture (measured: pose fit 40 percent off, depth 8 percent).
3. MoGe-2 monocular metric depth against VGGT depth, median over the farther
   half of the frames, field of view from EXIF when present. Used when nothing
   else exists (the walk-in test's photos and video).

## Alternatives considered
- MapAnything (metric out of the box): no consumer VRAM numbers, untested on 8 GB.
- Depth Pro as the anchor: older, lower reported metric accuracy than MoGe-2.
- Known-object or IMU scale: needs capture-time cooperation, rejected.

## Consequences
Metric accuracy of the photo and video tiers is bounded by the anchor, not by
VGGT: 2 percent on frames that see a whole wall, 10 to 25 percent low on
close-ups. The protocol asks for wall-facing photos for that reason.
