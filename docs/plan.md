# Floor plan reconstruction: research and architecture plan

Revised 2026-09-20 after a verification pass: every model, API, and hardware
claim below was checked against a primary source (README, spec, chromestatus,
GitHub issue) or run on the actual laptop. Items still unverified are marked.

## Problem

Input: phone camera captures of a room or property, in one of three tiers.
Output: a dimensioned floor plan (wall layout, room outline, measurements in cm),
stitched across the full capture, accurate to the centimeter.

Tiers, in order of increasing raw signal quality:

1. Photos: a sparse set of unordered stills.
2. Video: a continuous handheld walkthrough.
3. Sensor-assisted depth: real-time depth captured at record time, not
   reconstructed after the fact. LiDAR on Apple Pro devices (ARKit scene
   reconstruction), or ARCore Depth API depth-from-motion on Android. Called
   the "depth tier" below, the pipeline is the same for either source.

## Local hardware (verified)

- Laptop: RTX 5050 Laptop GPU, 8GB VRAM, Blackwell sm_120, 15GB RAM, 12
  cores, WSL2. CUDA works inside WSL2 (`nvidia-smi` and torch both see it).
- `torch 2.14.0+cu130` installed via uv, `torch.cuda.is_available()` True,
  arch list includes sm_120, bf16 matmul and `scaled_dot_product_attention`
  run on the card. This is the whole attention stack we can rely on:
  - flash-attn: no official sm_120 wheel, source build fails (Dao-AILab
    issues 2361, 2168). Do not install.
  - xformers: official wheels stop at sm_90 (issue 1279) and installing it
    can downgrade torch to a non-sm_120 build. Do not install, even where a
    README says to (DA3, MUSt3R, UniDepth).
  - cuDNN SDPA backend can fail on Blackwell, call
    `torch.backends.cuda.enable_cudnn_sdp(False)` at process start.
- Phone: Android, Chrome, ARCore. Depth tier tested end to end on the real
  device (see capture page section).

## Common output schema

All three tiers converge on one output so downstream consumers (Xactimate-style
estimate generation) do not care which tier produced it. Implemented in
`pipeline.reconstruct`:

```
FloorPlan
  rooms: list[Room]
  diagnostics: points, planes, walls, closed, wall_lines
  capture: photos, video (what came in the upload)
Room
  id, label
  polygon_cm: list[(x_cm, z_cm)]   # wall corners, closed loop, shared world frame
  wall_lengths_cm, area_m2, perimeter_m
  wall_height_cm: float | null     # ceiling plane minus floor plane
  openings: list[Opening]          # doors, windows: not implemented yet
  confidence: float                # wall inliers / total points, 0 when not closed
  source_tier: photos | video | depth
```

## Tier 3: depth capture (Android ARCore today, ARKit LiDAR later)

Highest confidence, built first.

Device coverage:

- LiDAR is exclusive to iPhone/iPad Pro. Non-Pro iPhones have no on-device
  metric depth, they fall through to the photo/video pipeline.
- ARCore Depth API needs no special hardware, depth-from-motion covers most
  ARCore-certified Android devices. Pose tracking is metric (VIO).
- iOS Safari does not support WebXR `immersive-ar` (Apple forums thread
  756850, still true through Safari 26.6). No iOS browser can, they all use
  WebKit. iOS needs a native app or App Clip wrapper. Not in scope.

### Capture page (web-capture/index.html)

Chrome on Android exposes ARCore to a plain web page through WebXR, no app
install. Verified against the spec, chromestatus, and Chromium source:

- Depth: `depth-sensing`, shipped Chrome 90. ARCore-backed Chrome only
  offers `cpu-optimized` usage, `luminance-alpha` or `unsigned-short`
  formats (uint16 millimetres, `rawValueToMeters` 0.001), and only `smooth`
  depth. `float32` and `raw` are silently unavailable. Confidence is not
  exposed. Resolution is ~160x90 (matches the camera aspect), rejected above
  43,200 pixels, so ToF phones with 640x480 depth may return null (unverified
  on device).
- The page now dumps the full `XRCPUDepthInformation.data` buffer per frame
  (base64) plus `normDepthBufferFromNormView`, instead of a 20x15
  `getDepthInMeters` grid. That is 14,400 points per frame instead of 300.
  The coarse grid is still stored and the loader cross-checks the buffer
  decode against it, falling back to the grid with a warning on mismatch.
- Photos: `camera-access` (WebXR Raw Camera Access), shipped by default in
  Chrome 107 for Android. `XRWebGLBinding.getCameraImage(view.camera)`
  returns an opaque texture valid only inside that frame callback, origin
  bottom-left. The page reads it back through an FBO, flips, and saves a
  JPEG on every manual capture, named in the capture record. Camera
  intrinsics are not exposed, derive them from `projectionMatrix` scaled to
  the camera image size. Keep `XRWebGLLayer` as the base layer, the Layers
  API path crashed `getCameraImage` before Chrome 149.
- Video: `getUserMedia` is not usable while ARCore owns the camera, and the
  XR framebuffer is opaque so `captureStream` on the XR canvas records
  nothing. The page draws the camera texture into a second 2D canvas (max
  1280 wide, larger canvases break MediaRecorder on Android) and records that
  with `MediaRecorder` (`video/webm;codecs=vp9`, falls back to vp8, mp4).
  Every drawn frame also stores the XR pose with a timestamp, so the video
  tier gets metric VIO poses for free when captured through this page. While
  recording, depth frames are also stored at ~5 fps.
- Export: JSZip bundle `capture.json` + `photos/NNNN.jpg` + `video.webm`,
  photos and video each optional via checkbox. Download, or upload straight
  to the local backend.
- Metadata: user agent, `userAgentData` model, granted depth format/type,
  camera-access grant.

### Accuracy expectations

- Google: most accurate between 0.5m and 5m, white walls give imprecise
  depth. The loader drops points beyond 6m.
- No Google-published wall-distance error. One independent indoor test
  (arXiv 2204.01693, OnePlus 6, 160x90 raw depth vs LiDAR) reports MAE in
  the tens of cm at low confidence thresholds, exact figure not extracted.
  Treat cm-level accuracy on this tier as unproven until measured against a
  tape, and expect ToF phones (Pixel with ToF, Samsung Ultra) to do better.
- Poses are the reliable part (VIO, roughly 1.6-4cm indoor). The walls the
  camera got close to should be good, far walls will not be.

### Pipeline (implemented in `depth_capture` + `plane_extraction` + `pipeline`)

1. Unproject each frame's depth into the shared world frame using the
   per-frame pose and projection matrix (off-centre terms honoured).
2. Voxel downsample (3cm) and statistical outlier removal.
3. Iterative RANSAC plane segmentation (Open3D). Planes with a near-vertical
   normal are floor/ceiling, their height difference is `wall_height_cm`.
4. Merge wall fragments with the same top-down line, order walls by angle
   around the centroid, intersect neighbours to get corners.
5. Emit the schema, a top-down PNG with wall lengths, and a PLY.
6. Openings (doors/windows) as gaps in a wall plane: not implemented.

Confirmed on two real captures of a furnished room: 3-4 wall planes found,
polygon does not close because furniture hides part of a wall on one side.
`wall_polygon` refuses to guess, which is right, but it means pure RANSAC
fails on realistically furnished rooms. Two fixes, pick one before the real
assignment: walk close to every wall during capture (cheap, capture
discipline), or add a learned prior (RoomFormer, below). The full-resolution
depth buffer (48x more points than the old grid) has not been tested on a
real capture yet, do that first, it may be enough for RANSAC to see past
furniture.

## Tier 2: Video, and Tier 1: Photos

Classic SfM (COLMAP) is the textbook approach and remains the no-GPU
fallback. The default is a feed-forward model that regresses a point cloud
plus camera poses from unordered images in one pass. Verified state as of
September 2026:

| Model | Metric | Poses | License | 8GB evidence | Attention deps |
|---|---|---|---|---|---|
| VGGT-1B via `harry7557558/vggt-low-vram` | no | yes | FAIR non-commercial (commercial ckpt by application) | 25 imgs 3.5GB, 125 imgs 5.8GB, 150 imgs on an RTX 5070 Laptop 8GB, CUDA 12.8, torch 2.7.1 | none |
| MapAnything (`facebook/map-anything-apache`) | yes | yes | Apache 2.0 weights available | none published, 1B params, likely tens of frames per pass | none |
| Depth Anything 3 (DA3, ByteDance, Nov 2025) | yes via DA3METRIC-LARGE / nested | yes | Small/Base/Metric-L Apache, Giant/Large-1.1 non-commercial | streaming mode 11.5-28GB peak, 24GB OOM over 100 imgs, no 8GB figure | README says `pip install xformers`, see hardware section |
| VGGT-Omega (Meta, May 2026) | no | yes | FAIR non-commercial, gated | A100: 25 frames 7.8GB, ~30% of VGGT memory | none |
| Pi3 / Pi3X (Dec 2025) | Pi3X approximate | yes | code BSD, weights CC BY-NC | none published | none |
| MUSt3R (Naver) | not stated | yes | non-commercial | none on consumer cards (the 4.1GB figure was an A100 survey number) | xformers recommended |
| MASt3R | yes | yes | CC BY-NC-SA | 11.8GB for 19 images on a 3080, no-go | |
| AMB3R (CVPR 2026) | yes | yes | | pins torch 2.5 + flash-attn 2.7.3, no-go on sm_120 | flash-attn |
| LingBot-Map (ECCV 2026, Apache) | no | yes | Apache | user OOM at 16GB | FlashInfer with SDPA fallback |

Corrections to the previous version of this plan:

- MUSt3R-224 was the default on the strength of a 4.1GB benchmark. That
  number is from an A100 survey, not a consumer card, and MUSt3R recommends
  xformers, which is not usable on this GPU. Demoted to "try if VGGT falls
  short".
- `vggt-low-vram` is the only backbone with a published number on an 8GB
  Blackwell laptop, nearly identical to this one. It is the default.
- MapAnything now has an Apache-licensed checkpoint (Jan 2026), and it is
  metric out of the box. It is the second option and the one to prefer if
  the take-home needs a commercially clean license or drops the scale anchor.
- Depth Pro (Oct 2024) as the scale anchor is superseded. MoGe-2 (Jul 2025,
  MIT code, commercial weights, metric depth plus intrinsics from one image)
  reports lower metric error than Depth Pro, UniDepth, and Metric3Dv2 in its
  paper. MoGe-3 (Aug 2026, same repo) exists but has no independent indoor
  numbers yet. DA3METRIC-LARGE (Apache) is the alternative.
- PolyRoom has no license file and sits on an MMDetection stack. RoomFormer
  (MIT, weights released, density-map in, polygons out) is the learned floor
  plan model to reach for, with the caveat that its deformable-attention CUDA
  ops are torch 1.9 era and need a rebuild for sm_120 (unverified).
  SpatialLM 1.1 (Qwen 0.5B, Apache) does walls/doors/windows straight from a
  point cloud but needs flash-attn, so it is out on this GPU.
- Nothing released between January and September 2026 supersedes the above
  for an 8GB card. No MapAnything v2 or Depth Anything 4 exists.

Plan: `vggt-low-vram` as the backbone for both tiers, bf16, SDPA only, chunk
video into 30-60 keyframes with overlap (VGGT-Long pattern) if a capture
exceeds ~150 frames. Video frames are an ordered, densely sampled image set
to the model, so one backend covers both tiers, the only difference is frame
extraction (fixed interval plus a parallax check for video).

Scale:

- Video captured through our page: use the recorded VIO poses. Fit a
  similarity transform from VGGT's relative camera centres to the ARCore
  camera centres, that gives metric scale with no monocular model at all.
- Plain video or photos from any other source: MoGe-2 ViT-L on 3-5 frames,
  median ratio of MoGe depth to VGGT depth is the scale factor. Or run
  MapAnything and take its metric output directly.
- Whichever path: verify against a tape measure first, before trusting any
  paper number.

Once a point cloud and poses exist, plane fitting and polygon extraction are
shared with the depth tier. Multi-room stitching for a single continuous
capture is native to this model class, all frames share one forward pass.

### Photo and video tiers: first real run (2026-09-20)

Implemented in `multiview.py`, wired into `pipeline.process_image_tiers`, runs
after the depth plan on every upload. Measured on the furnished-room capture:

| tier | images | peak VRAM | result |
|---|---|---|---|
| photos | 10 (851x1920, crop mode 518x518) | 5.0GB | closed rectangle, 258 x 217 cm |
| video | 38 (1 fps frames + 10 photos as anchors) | 5.6GB | closed rectangle, 269 x 197 cm |
| depth | 145 ARCore frames | n/a | closed rectangle, 393 x 314 cm |

- VGGT-1B via the low-VRAM fork runs on the RTX 5050 in bf16 with SDPA.
  `TORCH_COMPILE_DISABLE=1` is required, the fork decorates layers with
  `torch.compile` and this machine has no Python headers for the Triton
  build. Weight download needs `HF_HUB_DISABLE_XET=1`, the Xet path stalled.
- VGGT geometry is much cleaner than ARCore depth: thin walls, no fill on
  white surfaces, the rectangle fits the point band exactly.
- Scale is the open problem. Three estimates disagree:
  - camera-pose alignment (orientation Procrustes + median pairwise distance
    ratio against ARCore poses of the 10 photos): 1.38. Position residual
    34cm median on a 1m path, so this is weak. VGGT translation on a
    rotate-in-place capture is noisy.
  - ARCore depth vs VGGT depth pixel by pixel on the same 10 photos: 2.49
    median, but per frame from 2.0 to 3.8. Either ARCore depth or VGGT's
    per-frame depth is not self-consistent across frames.
  - depth tier rectangle is 1.5x the photo tier rectangle.
- Tape ground truth (data/ground_truth/bedroom.json): 426.7 x 365.8 cm.
  Against it:

  | tier, scale source | result | error |
  |---|---|---|
  | depth (ARCore) | 393 x 314 | -8%, -14% |
  | photos, pose-based scale 1.38 | 258 x 217 | -40% |
  | photos, ARCore-depth-based scale 2.49 | 465 x 391 | +9%, +7% |
  | scale that would be exact | 2.30 | |

  VGGT's aspect ratio is 1.19 against a true 1.17, its geometry is the best
  of the three. The pose-based scale is unusable on a rotate-in-place
  capture (VGGT translations are noise on a 1m baseline). The ARCore-depth
  anchor is 8% high, consistent with ARCore reading textured walls about 8%
  too far on this phone. The depth tier rectangle is low because RANSAC fits
  the middle of a thick, fill-contaminated band. Photo and video tiers now
  use the depth anchor when ARCore depth exists for the photos.
- Fix for the pose-based scale: capture photos while walking, not rotating.
  A 3m baseline gives VGGT translations that a similarity fit can trust.
  This is what the iPhone protocol will require, since there is no ARCore
  depth to anchor on there.

## Sample data from Cozmo (2026-09-20)

Three Stray Scanner exports (iOS LiDAR logging app): `single_room` (37s, 1715
frames, actually 3 rooms), `single_scan_floor_only` (115s, 5251 frames, 6
rooms, camera pointed at the floor), `single_scan_with_ceiling` (215s, 9745
frames, 5 rooms plus corridor). Format per scan: `rgb.mp4` 1920x1440 HEVC 60
fps, `depth/*.png` 256x192 uint16 mm, `confidence/*.png` 0-2, `odometry.csv`
camera-to-world position plus quaternion per frame, `camera_matrix.csv` for
the RGB resolution, `imu.csv` at 100 Hz. No ground truth was supplied.

Findings that changed the code:

- Odometry poses are camera-to-world in the OpenCV convention (x right, y down,
  z forward), not ARKit's. Verified by trying all axis assignments: only that
  one gives vertical walls and a floor 1.4m below the phone.
- Frames are landscape sensor frames of a portrait capture. Rotate 270
  degrees clockwise (from gravity in the poses) and rotate the pose by the
  opposite angle. Verified against VGGT on ten consecutive frames: 1 to 2
  degree rotation residual, under 8cm position residual, once both are right.
- VGGT holds a room, not an apartment. 58 frames spanning three rooms gave a
  29 degree median orientation error against the poses. Consecutive chunks of
  16 frames, each aligned to its own poses and merged in the world frame, is
  the fix (VGGT-Long pattern). Frames pitched more than 50 degrees off
  horizontal (floor shots) are skipped.
- Eight stills spread across an apartment do not overlap. The photo tier now
  reconstructs each room's stills separately and places rooms by pose, which
  is also what per-room photo folders in the assessment amount to.
- IMU is not used. The poses are already gravity aligned and the IMU carries
  nothing the odometry lacks for this task. Confidence maps are used, only
  confidence 2 depth pixels enter the cloud.
- Ceiling detection by global RANSAC is unstable across rooms with different
  ceilings. Per-room floor and ceiling now come from the point height
  histogram inside each room polygon.

This settles the capture route for the LiDAR tier on iPhone: Stray Scanner,
free, exports everything the pipeline needs, and Cozmo's own samples use it.

## Multi-room segmentation (rooms.py)

No learned model. From a y-up cloud with a known floor:

1. Rotate to the dominant wall direction (Hough on the tall-point density).
2. Rasterise at 3cm. A cell is wall if points occupy at least 3 of 4
   half-metre height bands between floor+0.2 and floor+2.2 (furniture fails
   the top bands, ceiling fails the bottom ones).
3. Free space is every occupied non-wall cell, closed and hole-filled.
4. Erode free space past a doorway half width (0.55m), label the cores as
   rooms; a second erosion at 0.30m seeds corridors no room core reached.
   Grow seeds back inside free space.
5. Per room: open and close the mask with a 25cm square (removes notches),
   trace the contour, classify edges by axis, remove edges under 30cm by
   merging their perpendicular neighbours, intersect consecutive lines.
6. Adjacency from touching grown regions, contact length as the opening
   width, "doorway" up to 1.5m, "open" beyond.

Known gaps: openings are only found between rooms, not to the outside or as
windows. A room scanned only from its doorway gets the scanned footprint, not
the room. Doorway widths from region contact overshoot when the shared wall
was not scanned.

## Scale without poses: MoGe-2 anchor (2026-09-20)

iPhone photos and Camera-app video carry no poses, so the walk-in test's photo
and video tiers need a monocular metric anchor. Measured on the bedroom photos
against the tape-implied VGGT scale of 2.30:

| anchor | scale | error |
|---|---|---|
| camera poses (rotate-in-place) | 1.38 | -40 percent |
| ARCore depth per pixel | 2.49 | +8 percent |
| MoGe-2 ViT-L, FOV estimated by the model | 1.88 (per frame 1.48 to 2.24) | -18 percent |
| MoGe-2 ViT-L, FOV from the projection matrix | 2.05 (per frame 1.69 to 2.33) | -11 percent |
| MoGe-2 with FOV, far half of the frames only | 2.30 | within 2 percent |

Frames that see a whole wall at 2 to 3 m agree with the tape; close-ups of
furniture at 1 to 1.5 m come out low, most likely because VGGT's per-frame
depth is inconsistent on a rotate-in-place capture rather than because MoGe is.
Implemented: FOV from EXIF (35mm-equivalent focal length) when present, per-frame
ratio of MoGe to VGGT depth on confident pixels, anchor = median over the farther
half of the frames, both aggregates recorded. Poseless clouds are levelled from
the mean camera up axis (phones are held upright). MoGe-2 is MIT with commercial
weights, 1.3 GB VRAM, 0.3 s per frame after loading.

End-to-end poseless test (the bedroom's 10 page photos copied into a files-only
upload, no poses, no EXIF): closed rectangle 378 x 316 cm against 427 x 366,
-12 and -14 percent, levelled correctly, MoGe far-frame scale 2.16 against the
2.30 the tape implies. The page's JPEGs carry no EXIF, so MoGe estimated the
FOV itself; iPhone photos carry the 35mm focal length and should do better.
Photo gate is 8 percent, so this fails narrowly and honestly.

## Damage detection findings (2026-09-20)

- OWLv2 (local, Apache 2.0) localizes damage but confuses classes. Cozmo's
  single_room sample has a real 60 cm crack in the bathroom wall: found at the
  right place, labelled water stain at 0.55 even after re-scoring the crop
  across all class prompts. On the undamaged bedroom it produced three low-score
  false positives, rejected by the score and size rule (0.40, 8 cm).
- Fix: a second stage. OWLv2 keeps localizing candidates at a low threshold,
  then Qwen3-VL-2B-Instruct (Apache 2.0, 4.5 GB VRAM for the pair, about 1 s per
  crop) looks at each crop and answers crack, water_stain, mould, peeling_paint
  or none. On the sample bathroom the crack is now labelled crack by every box
  that covers it; on the undamaged bedroom every candidate is answered none, so
  zero regions come out. Chosen after a survey of open models: no released
  weights cover all four classes, crack-only segmenters exist (YOLOv8-crack-seg
  AGPL, SegFormer DeepCrack), and DefectBench (arXiv 2603.20148) puts Qwen3-VL
  near much larger models on building pathology. Qwen2.5-VL-3B was rejected
  for its non-commercial license and 8 GB footprint.
- Claude vision stays wired as an optional backend. It costs money and needs a
  key, so it is off by default and untested.
- PyTorch 2.14 routes some ops through Triton JIT kernels, which need Python
  headers this machine lacks. `TORCH_DISABLE_NATIVE_JIT=1` and
  `TORCH_COMPILE_DISABLE=1` are set in the package `__init__` and must be in
  the environment before torch is imported.
- Damage acceptance and rejects are both written to damage.json so the report
  can show precision honestly once the staged-damage room is captured.

## Scale strategy summary

| tier | scale source |
|---|---|
| depth (ARKit LiDAR) | ARKit metric depth, exact |
| depth (Android ARCore) | ARCore VIO-fused metric depth, accuracy unverified |
| video via our capture page | MoGe-2 with the projection FOV for scale, poses for orientation and placement |
| video from elsewhere | MoGe-2 with EXIF FOV when present, chunked VGGT |
| photos | MoGe-2 with FOV (projection or EXIF), poses for placement when recorded |

## Architecture

```
phone (Chrome, WebXR)  --zip over https-->  local backend (FastAPI)  -->  pipeline  -->  plan.json + plan.png
```

- Capture page: served by the backend at `/`. Depth, photos, video, poses in
  one zip. Optional pieces are checkboxes.
- Backend (`server.py`): `POST /api/captures` takes the zip, validates it
  (path traversal check, size cap, must contain `capture.json`), unpacks to
  `data/captures/<id>/`, runs the pipeline in a thread. `GET
  /api/captures/<id>` polls status and returns the plan, `plan.png` renders
  the top-down view. The page polls and shows the result in the overlay.
- Cloudflare: `scripts/serve.sh` starts uvicorn on 127.0.0.1:8000 and a
  `cloudflared` quick tunnel in front of it. The phone opens the printed
  `trycloudflare.com` URL. WebXR requires a secure context, the tunnel gives
  https with zero config and nothing leaves the laptop except the tunnel.
  Quick tunnels are ephemeral and unauthenticated, fine for a demo, a named
  tunnel with Access in front is the production version.
- Pipeline (`pipeline.py`): capture directory in, schema out, shared by the
  server and a future CLI. Tier detection is trivial today (depth tier only),
  photos and video in the zip are recorded but not yet reconstructed.
- Module boundaries: `depth_capture` (ingest), `plane_extraction` (geometry),
  `pipeline` (schema + render), `server` (transport). The photo/video backend
  slots in as a second ingest module producing the same point cloud.

## Build vs buy

- Depth tier: custom Open3D pipeline, not RoomPlan, because one pipeline has
  to cover ARKit LiDAR and ARCore. RoomPlan's 1-3cm is the reference target.
- Android capture: browser, WebXR, not a native app. Confirmed on device.
- Photo and video tiers: `vggt-low-vram` first, MapAnything second, DA3 third
  (only if xformers can be avoided). Never stock VGGT, MASt3R, AMB3R, or
  SpatialLM on this card.
- Scale anchor: MoGe-2, not Depth Pro.
- Plane segmentation: Open3D throughout.
- Polygon extraction: RANSAC intersection now, RoomFormer as the upgrade.
- Backend: FastAPI + uvicorn, cloudflared quick tunnel. No database, the
  capture directory is the record.

## Evaluation strategy

- Ground truth: tape measure a real room, compare wall lengths and area.
- Per-tier accuracy targets: depth tier should land within a few cm on walls
  the camera got close to. Video and photo depend on the scale path, report
  them separately with that caveat.
- Track failure rate, not just accuracy on captures that succeeded.
- First thing to measure: full-buffer capture of the same furnished room,
  does the polygon close now, and how far off is each wall.

## Risks and edge cases

- Non-rectangular rooms, curved walls, sloped ceilings: plane fitting breaks,
  needs explicit non-support.
- Reflective or textureless surfaces: ARCore and feed-forward models both
  degrade, LiDAR too on glass.
- Moving furniture or people: violates the static scene assumption.
- Static furniture occluding walls: confirmed real failure, see depth tier.
- GPU memory: paper VRAM numbers do not hold. VGGT upstream OOMs an 8GB 4070
  at 6 images. Only the low-VRAM fork has real 8GB numbers. Profile
  MapAnything and DA3 directly before relying on them.
- WSL2 on Blackwell: open Microsoft issues on hidden driver memory overhead
  and unified-memory segfaults. If something looks like a phantom OOM, test
  the same script on Windows-native Python before debugging the model.
- Licenses: VGGT and MUSt3R weights are non-commercial. For a company
  deliverable, MapAnything (Apache), DA3 Small/Base/Metric-L (Apache), MoGe
  (MIT), RoomFormer (MIT) are the clean set.
- ARCore depth accuracy is unverified at cm level. If it measures at 10cm+,
  the honest framing is "walls from VIO poses plus close-range depth", not
  "cm-accurate LiDAR-equivalent".

## Execution plan

1. Done: schema, plane/polygon extraction with synthetic tests, depth
   capture page, unprojection, pipeline, backend, tunnel script.
2. Next: capture the furnished room again with the new page (full buffer,
   photos, video). Check whether the polygon closes, measure each wall with a
   tape, record the numbers in this doc.
3. Photo and video tiers: install `vggt-low-vram`, run it on the photos from
   step 2 in bf16 with SDPA, confirm memory on this card, fit the similarity
   transform to the recorded poses, run the shared extractor.
4. MoGe-2 anchor for captures without poses. Compare to the pose-based scale
   on the same capture, that is the accuracy check for the anchor.
5. Openings from wall-plane gaps. Then RoomFormer if closure keeps failing.
6. COLMAP path documented, not built, for a no-GPU environment.
