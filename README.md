# Cozmo AI — Take-Home Prep

## Context

- Role: AI Backend Engineer, Cozmo AI (YC W25) — India Remote, reporting to CTO.
- Recruiter: Bhavana (Brynz). Take-home assignment expected **2026-09-20, 10:00 AM**.
- Company: AI operating system for property claims (restoration franchisors, TPAs, adjusters).
  Agents capture the loss, enter claims into Xactimate/Cotality, dispatch contractors,
  chase SLAs, and draft carrier-ready estimates from field photos.

## Problem statement (given by recruiter ahead of the take-home)

> Turn phone camera captures into dimensioned, stitched floor plans with cm-level
> accuracy across three input tiers (photos, video, LiDAR).

This maps directly to the "draft the carrier-ready estimate from field photos" part of
the product: a field tech/adjuster walks a damaged property with their phone, and the
system needs to reconstruct a measured floor plan (room dimensions, wall layout) good
enough to feed into an Xactimate-style estimate.

Three input tiers, likely increasing in fidelity / decreasing in required cleverness:

1. **Photos** — sparse, unordered still images. Hardest tier: needs structure-from-motion
   (SfM) / multi-view geometry, and scale is ambiguous without a reference (need a known
   object, ARKit metadata, or user-provided single measurement to fix scale).
2. **Video** — a continuous walkthrough. Easier than photos because you get near-continuous
   frames for SfM / SLAM (temporal continuity, more overlap, denser correspondences).
3. **LiDAR** — modern iPhones/iPads expose depth + point clouds via ARKit
   (`ARFrame.sceneDepth`, `ARMeshAnchor` for scene reconstruction). This tier gets you
   metric scale for free and dense geometry — the job becomes plane-fitting /
   room-layout extraction from a point cloud rather than 3D reconstruction from scratch.

## Open questions / doubts to raise with Bhavana or in the technical discussion

- [ ] Is the take-home about **implementing the full pipeline** (SfM/SLAM + floor-plan
      extraction) or about **designing the system architecture** (agent orchestration,
      APIs, data model) around an existing reconstruction library?
- [ ] What's the expected input format for each tier — raw JPEGs, an MP4, or an ARKit
      capture bundle (e.g. exported `.usdz` / point cloud / depth frames)? This changes
      the scope enormously.
- [ ] "cm-level accuracy" — accuracy against what ground truth, and is a synthetic/sample
      dataset provided, or are we expected to source/capture our own test data?
- [ ] Is "stitched" floor plan singular (one room) or multi-room (needs loop closure /
      global registration across a walkthrough)?
- [ ] Time budget and expected deliverable format — working code + README, a design doc,
      a demo video, or all three?
- [ ] Language/stack constraints — JD says Python or TypeScript; is there a preferred
      one for this specific assignment (e.g. because of existing infra)?
- [ ] Should this run as an offline batch pipeline or does it need to be a real-time/
      on-device experience (matters for algorithm choice: full SfM vs. visual-inertial
      SLAM vs. ARKit's built-in RoomPlan API)?

## Likely shape of the assignment (guesses, to prep for)

Given "0-4 years", "0-2 years experience", a 1-day-ish take-home, and the emphasis on
first-principles reasoning over exhaustive engineering, the assignment is probably scoped
down from the full problem statement to something tractable, e.g.:

- Given a **set of photos with camera intrinsics/poses (or EXIF) provided**, estimate room
  dimensions and produce a 2D floor-plan sketch (skip the hardest SfM step).
- Given an **ARKit point cloud / depth data sample**, fit planes (walls/floor/ceiling) and
  output a dimensioned polygon (this tier is the most tractable to actually finish).
- A **design-only** exercise: write up how you'd architect the three-tier pipeline, what
  you'd build vs. buy (COLMAP, Open3D, Apple RoomPlan, ARCore Depth API), where accuracy
  breaks down, and a minimal working prototype for the easiest tier as proof.

Worth pre-reading/refreshing before 10 AM tomorrow:
- Structure from Motion basics (COLMAP pipeline, essential matrix, bundle adjustment)
- Apple ARKit `RoomPlan` framework (does almost exactly tier 3 already — worth knowing
  its exact capabilities/limits so you can say "buy vs. build" intelligently)
- Point cloud plane segmentation (RANSAC plane fitting, Open3D `segment_plane`)
- Monocular depth / scale ambiguity and how apps like Polycam/Matterport handle it

## Environment

- Python 3.11+, see `requirements.txt` (populated once the actual assignment is known —
  candidates: `numpy`, `opencv-python`, `open3d`, `trimesh`, `scipy`).
- `src/` — implementation
- `notebooks/` — exploration/scratch work
- `tests/` — test cases
- `data/` — sample inputs per tier (gitignored except `.gitkeep`)
- `docs/` — write-up / design notes for submission
