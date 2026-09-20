# ADR-0004: Stray Scanner export is the LiDAR capture route

## Status
Accepted

## Context
No iPhone is available to build or test a native capture app (Route 1). The
LiDAR tier still has to run on the graders' iPhone at the defense. Cozmo's
sample data arrived as Stray Scanner exports.

## Decision
Route 2 with Stray Scanner: free, App Store, exports per-frame depth,
confidence, poses, intrinsics and RGB video. The loader was built and verified
on the three sample scans.

## Alternatives considered
- Polycam: raw export format undocumented, could not be verified without a device.
- Record3D: simpler format but partly paid and not what the samples use.
- Own iOS app: no Mac, no device, no way to test before the defense.

## Consequences
The protocol page tells a non-engineer how to record and export. The poses are
OpenCV convention and the frames are landscape sensor frames, both handled in
the loader and verified against VGGT. If the graders use a different app, the
loader does not apply and the capture falls to the video tier from the RGB.
