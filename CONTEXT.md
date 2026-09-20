# Glossary

One word per concept, used the same way in code, docs and commits.

- **capture**: one recording session handed to the pipeline as a directory. A Stray Scanner export, an upload from the capture page, or per-room photo folders. Never a single photo.
- **frame**: one depth image with its pose, or one video image. Photos are stills, not frames.
- **tier**: the input class. `lidar` (Stray Scanner, ARKit), `depth` (ARCore via the capture page), `video`, `photos`. Both `lidar` and `depth` are "the depth tier" in prose when the distinction does not matter.
- **pose**: a 4x4 camera-to-world matrix. WebXR convention inside the pipeline (x right, y up, camera looks down -z), OpenCV convention only inside the Stray Scanner loader and VGGT outputs, converted at the boundary.
- **cloud**: the fused y-up metric point cloud a tier produces. Everything downstream of ingest consumes a cloud plus camera positions.
- **wall band**: the slab of points a wall produces. Its thickness is the tier's depth noise, 3 to 8 cm on LiDAR, 30 to 66 cm on ARCore.
- **wall face**: where a wall line is placed inside its band. `centre` is the RANSAC fit, `outer` is the 80th percentile outward, the fix-loop change.
- **room**: a connected free-space region bounded by walls, with a rectilinear polygon. Rooms come from `rooms.py`; the single-room fallback comes from `plane_extraction.py`.
- **doorway**: a contact between two rooms found by the free-space split, width from the contact length. **door** and **window** are gaps in a wall's point band found per polygon edge. **open** is a contact wider than 1.5 m, open plan or an unscanned wall.
- **anchor**: the scale source for a view-model tier. Poses, ARCore depth per pixel, or MoGe-2 monocular metric depth.
- **interval**: the 95 percent range on a measurement from the per-tier error model. `interval_basis` says whether it is a prior or calibrated.
- **region**: one damage instance on one surface with class, metric extent and the photo it came from.
- **flag**: a concealed-damage rule that fired, named in the output.
- **scope item**: a line keyed to a surface, an area or a repair.
- **drift**: heading error of the VIO poses over time. The correction is orientation-only; position drift is not claimed.
- **gate**: a pass/fail threshold from the case study, scored in docs/benchmark.md.
- **ground truth**: tape measurements in data/ground_truth, one file per room, listing the captures it applies to.
