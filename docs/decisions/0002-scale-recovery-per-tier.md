# ADR-0002: scale for view-model tiers comes from poses, then ARCore depth, then MoGe-2

## Status
Accepted

## Context
VGGT returns geometry at relative scale. The case study scores metric
accuracy. Captures arrive with poses (Stray Scanner, capture page), with depth
per photo (capture page), or with nothing (iPhone Camera app).

## Decision
Priority order, chosen per capture from what exists:
1. MoGe-2 monocular metric depth against VGGT depth on the same frames, median
   over the farther half of the frames, when the horizontal field of view is
   known (capture page projection matrix, EXIF 35mm focal length on phone
   photos). Poses, when present, still give orientation and placement.
   Measured on the bedroom: photos -2.6 and -3.8 percent, video -4.6 and -2.6.
2. Recorded poses alone: similarity transform from camera orientations and
   pairwise centre distances. Used when no FOV is known. 40 percent off on a
   rotate-in-place capture, 10 to 15 percent on a walking one.
3. MoGe-2 with its own FOV estimate when neither poses nor FOV exist: 12 to 14
   percent low on the bedroom.

ARCore depth per pixel was the anchor before 2026-09-20 09:50; it measured 8
percent far on this phone and is kept as a diagnostic in the output.

## Alternatives considered
- MapAnything (metric out of the box): no consumer VRAM numbers, untested on 8 GB.
- Depth Pro as the anchor: older, lower reported metric accuracy than MoGe-2.
- Known-object or IMU scale: needs capture-time cooperation, rejected.

## Consequences
Metric accuracy of the photo and video tiers is bounded by the anchor, not by
VGGT: 2 percent on frames that see a whole wall, 10 to 25 percent low on
close-ups. The protocol asks for wall-facing photos for that reason.
