# Project instructions

Take-home assessment for an Applied AI / Backend Engineer role at Cozmo AI. Problem:
turn phone camera captures into dimensioned, stitched floor plans with cm-level
accuracy across three input tiers, photos, video, LiDAR. Full plan in docs/plan.md,
requirement coverage in docs/compliance.md, protocol in docs/capture-protocol.md.

## The assessment (facts)

- Case study PDF: ~/dev/cozmo/Applied AI.pdf. Deadline 2026-09-23 10:00 IST.
  Recruiter: Siva (Brynz Tech), thread in the personal Gmail. Round 1 references
  in the PDF are void, only the gates in the PDF count (recruiter, 2026-09-20).
- Sample data from Cozmo: ~/dev/cozmo/sample_data/Assignment/, three Stray Scanner
  exports (single_room = 3 rooms, single_scan_floor_only = 6 rooms,
  single_scan_with_ceiling = 5 rooms). No ground truth supplied.
- Scoring: walk-in test 30 percent (their iPhone 15+, tier chosen on the day, live
  run against a laser), fix loop 25 percent, verified benchmark 15 percent,
  compliance matrix 10 percent, head-to-head vs magicplan or polycam 10 percent,
  capture route 5 percent, process evidence (commit history) 5 percent.
- Gates: opening widths 2 cm on 85 percent; ceiling height 1.5 cm, repeat spread
  1 cm; repeatability 1 cm or 0.5 percent per wall; drift accountability with an
  on/off ablation ("poses as-is" fails); photo tier whole-property stitch within 8
  percent with calibrated intervals; video 3 percent; photo 8 percent.
- Benchmark set we must build: 3+ rooms plus connector, one furnished room with
  staged damage in two classes, every room at all three tiers, one room captured
  twice, tape ground truth on everything, raw data submitted.
- Constraints: handheld consumer capture, any pretrained model or API with
  disclosure, nothing may call the author's infrastructure, weights fetched by
  script, mirrors/glass/wet surfaces/low light covered.
- Deliverables: compliance matrix, capture route plus device matrix, repo with a
  15-minute README and one command per capture, reproduction bundle, benchmark
  report, fix loop bundle, technical report (6 pages max), raw benchmark data.

## Our situation and decisions

- No iPhone available. Capture route is Route 2 (stock apps): Stray Scanner for
  LiDAR (the format Cozmo's own samples use), Camera app for photos and video,
  magicplan on Android for the head-to-head. Benchmark captures come from the
  user's Android phone (TECNO LI9, ARCore) through the web capture page.
- Local run is the product. Render or any hosted backend is out: no GPU on free
  tiers and the assessment forbids calling our infrastructure. The Cloudflare
  quick tunnel is a capture convenience only.
- Laptop: RTX 5050 Laptop 8 GB (Blackwell sm_120), WSL2, torch 2.14+cu130 works.
  Never install xformers or flash-attn (no sm_120 wheels, xformers downgrades
  torch). TORCH_COMPILE_DISABLE=1 is required for the VGGT fork (no Python
  headers here). HF_HUB_DISABLE_XET=1 for weight downloads (Xet stalls).
- Repo: private, github.com/The-Thought-Magician/floorplan-takehome, pushed via
  the `github-ttm` SSH alias. gh active account is The-Thought-Magician.
- Tape ground truth so far: bedroom 426.7 x 365.8 cm, ceiling 312.4 cm
  (data/ground_truth/bedroom.json). Staged damage planned: wet patch + taped crack.

## Progress (2026-09-20, 37 commits)

Done and committed:

- Depth tier: ARCore via WebXR page (full depth buffer, photos, video with poses,
  zip upload) and Stray Scanner loader (OpenCV camera convention verified, every
  frame, confidence 2 only). Multi-room segmentation (rooms.py), rectilinear
  polygons, adjacency, doors and windows from wall gaps, per-room heights.
- Photo and video tiers: VGGT-1B via vggt-low-vram, upright frames from gravity,
  chunked video aligned per chunk to poses, per-room stills reconstructed room by
  room. Scale from poses (walking capture) or ARCore depth (rotate-in-place).
- Contract: intervals on every measurement (priors, not calibrated), damage
  regions with metric extent (OWLv2 local, Claude optional), concealed-damage
  rules, scope items, drift accountability with ablation.
- Ops: FastAPI backend, one-command CLI (scripts/floorplan.py), setup and weight
  scripts, benchmark report generator, compliance matrix, protocol, report draft.

Measured: bedroom depth tier 393 x 314 cm vs 427 x 366 (-8, -14 percent),
ceiling 302 vs 312. Photo tier -7 to -9 percent, video -3 to -15 percent. No gate
passed yet. LiDAR tier on the samples segments 3, 6 and 5 rooms; image tiers on
the samples reach 10 to 15 degree orientation residuals against the poses.

Pending: user benchmark capture (3 rooms, damage, repeat), magicplan head-to-head,
fix loop declaration and shipped fix, technical report numbers, calibration from
ground truth, MoGe-2 metric anchor for poseless photos and video, clean-machine
test of scripts/setup.sh.

## Writing rules

- No em dashes anywhere: not in code comments, commit messages, README, docs.
- Minimal prose outside code. Bullet points over paragraphs. State facts, skip
  filler and hedging.
- Do not mention AI coding tools in commits, code, comments or docs. This file
  is the one exception, kept in the repo at the user's request.
- Commit messages: short summary line, plain language, no attribution footer.

## Tooling

- Package management: uv. `uv add <pkg>` to add a dependency, `uv sync` to
  install, `uv run` to execute. Keep requirements.txt in sync as a fallback but
  uv is the source of truth (pyproject.toml + uv.lock).
- Python 3.14. Do not downgrade for a dependency unless a real incompatibility
  shows up, check PyPI wheel availability first.
- Prefer Open3D, OpenCV, NumPy, SciPy over hand-rolled geometry or vision code.
- third_party/vggt-low-vram is cloned by scripts/setup.sh, installed with
  --no-deps (its requirements pin an old torch).

## Working style

- Follow docs/plan.md architecture and module boundaries unless a real
  implementation constraint forces a change, then update the doc.
- Common schema (FloorPlan/Room) before tier-specific code.
- Test against synthetic data before real captures; every numeric claim in a
  test checks a tolerance.
- No speculative abstractions or config options for cases that are not needed.
- Commit as you work, one logical change per commit. The graders read history.
- Record every non-obvious finding in docs/plan.md as it happens.

## Skills

16 skills in .claude/skills/ (committed), merged and trimmed from
mattpocock/skills, DietrichGebert/ponytail, UditAkhourii/adhd,
addyosmani/agent-skills. Each SKILL.md notes its sources.

- spec-and-planning: turn the assignment into a spec and task list before building.
- codebase-design: module boundaries (ingest, geometry, contract, transport).
- source-driven-development: ground Open3D, OpenCV, ARKit, WebXR usage in docs.
- incremental-implementation: one tier end to end before the next.
- tdd: tests before plane fitting or polygon logic, tolerances not "runs".
- minimal-code: default while writing; audit mode before submitting.
- debugging: systematic loop for degenerate polygons.
- code-review: self-review against the spec before calling it done.
- git-workflow: commit discipline.
- documentation-and-decisions: log non-obvious calls as they happen.
- security-and-hardening: captures are untrusted input, validate before parsing.
- constraint-driven-development: write the accuracy bar down, flag shortcuts.
- doubt-driven-development, interview-me, idea-refine, adhd: only for real open
  design questions.

Default: do not invoke a skill because it exists. tdd, incremental-implementation
and minimal-code are the baseline.
