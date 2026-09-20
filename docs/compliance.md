# Compliance matrix

Requirement, where it lives, what artifact proves it, status on 2026-09-20. Status
values: done, partial (works, gate not met or coverage incomplete), pending (needs
the benchmark capture), not attempted.

## Part 1: capture route and tiers

| requirement | file | artifact | status |
|---|---|---|---|
| Capture route (Route 2, stock apps), one-page protocol | docs/capture-protocol.md | the page | done |
| Device matrix | docs/report.md (tier design) | table | pending report |
| Photo tier: 2-8 stills per room, no depth, no poses, stitched plan | src/floorplan_takehome/multiview.py (`reconstruct_photo_folders`), pipeline.py | data/sample/*/plan_photos.json | partial: stitching needs poses today, files-only uploads are relative scale |
| Video tier: handheld clip | multiview.py (`reconstruct_video_chunked`) | data/sample/*/plan_video.json | partial: metric via recorded poses only |
| LiDAR tier: depth, poses, intrinsics | stray_scanner.py, depth_capture.py | data/sample/*/plan.json | done on Stray Scanner and ARCore |

## Part 2: output contract

| requirement | file | artifact | status |
|---|---|---|---|
| Dimensioned per-room plan with walls | rooms.py, plane_extraction.py | plan.json rooms[].polygon_cm, wall_lengths_cm | done |
| Ceiling height | rooms.py `room_heights`, pipeline.py | rooms[].wall_height_cm, height_source | done, gate not met |
| Floor area | rooms.py | rooms[].area_m2 | done |
| Openings | rooms.py `wall_openings` (doors, windows), adjacency contacts (doorways) | rooms[].openings | done, unverified against tape |
| Stitched multi-room plan with adjacency | rooms.py `segment_rooms` | plan.json adjacency, plan.png | done on 3 sample scans |
| Per-surface damage regions with class and metric extent | damage.py | damage.json regions | done, detector untested on real damage |
| Concealed-damage flags with the rule that fired | damage.py `CONCEALED_RULES`, `flag_concealed` | damage.json concealed_flags | done |
| Scope line items keyed to surfaces | damage.py `scope_items` | damage.json scope_items | done |
| Confidence interval on every measurement | intervals.py | *_interval_cm fields, interval_basis | done, priors not yet calibrated |
| One command per capture | scripts/floorplan.py | summary.json | done |
| JSON to the published schema | README.md schema section | plan.json | done |
| Rendered plan | pipeline.py `_write_plan`, rooms.py `render_rooms` | plan.png | done |

## Part 2: benchmark set and gates

| requirement | file | artifact | status |
|---|---|---|---|
| Multi-room capture, 3+ rooms plus connector | data/sample/single_scan_with_ceiling (Cozmo sample), user capture pending | plan.json | partial: sample has no ground truth |
| Furnished room with staged damage in two classes | user capture pending (wet patch, taped crack) | damage.json | pending |
| Same rooms at all three tiers | pipeline.py `process_stray_scan` runs all three on one scan | summary.json | done on samples, pending on user rooms |
| One room captured twice, same tier | user capture pending | scripts/benchmark.py repeatability table | pending |
| Laser or tape ground truth, raw data submitted | data/ground_truth/*.json, data/captures, data/sample | files | partial: one room so far |
| Opening widths gate (2 cm on 85 percent) | scripts/benchmark.py | docs/benchmark.md | pending ground truth |
| Ceiling height gate (1.5 cm, spread 1 cm) | scripts/benchmark.py | docs/benchmark.md | FAIL on bedroom (-10.6 cm at depth tier) |
| Repeatability gate (1 cm or 0.5 percent) | scripts/benchmark.py | docs/benchmark.md | pending second capture |
| Drift accountability with on/off ablation | drift.py, pipeline.py | plan.json diagnostics.drift, plan_depth_drift_off.png, docs/benchmark.md | done (yaw correction, orientation only) |
| Photo-tier whole-property stitch, no overlaps, footprint within 8 percent | multiview.py, rooms.py | plan_photos.json | partial: needs poses or per-room folders with doorway overlap |
| Calibration scored at every tier | intervals.py, data/calibration.json (not yet written) | interval_basis | partial: priors only |

## Part 3: head-to-head

| requirement | file | artifact | status |
|---|---|---|---|
| Consumer app on 2 rooms, table of errors | docs/report.md | magicplan export + table | pending (magicplan on Android) |

## Part 4: fix loop

| requirement | file | artifact | status |
|---|---|---|---|
| Fix declaration: worst gate, root cause, predicted number | docs/fix-loop.md | the page | pending benchmark numbers |
| Before and after runs, regenerable, readable diff | git history, scripts/floorplan.py | two summary.json plus git diff | pending |

## Part 5: process evidence

| requirement | file | artifact | status |
|---|---|---|---|
| Incremental commit history | git log | 40+ commits over two days | done |

## Deliverables

| deliverable | file | status |
|---|---|---|
| Compliance matrix | docs/compliance.md | this file |
| Capture route and device matrix | docs/capture-protocol.md, docs/report.md | protocol done, matrix pending |
| Repo, README to first plan in 15 minutes, one command | README.md, scripts/setup.sh, scripts/floorplan.py | done, untested on a clean machine |
| Reproduction bundle | scripts/fetch_weights.sh, cached VGGT outputs (vggt_*.npz) replay deterministically, live path is the same command | done |
| Benchmark report | scripts/benchmark.py, docs/benchmark.md | generated, ground truth pending |
| Fix loop bundle | docs/fix-loop.md | pending |
| Technical report, 6 pages | docs/report.md | pending |
| Raw benchmark data | data/ (sensor logs, ground truth, app exports) | partial |

## Constraints

| constraint | how | status |
|---|---|---|
| Handheld consumer capture only | phone apps and the web page | done |
| Pretrained models disclosed | VGGT-1B (FAIR non-commercial), OWLv2 (Apache 2.0), optional Claude API, all named in plan.json and docs/plan.md | done |
| Runs without the author's infrastructure | everything local, tunnel is a capture convenience only | done |
| Weights fetched by script | scripts/fetch_weights.sh | done |
| Mirrors, glass, wet surfaces, low light | docs/capture-protocol.md (avoidance), docs/report.md failure modes | partial |
