# Constraints

## Floor

- No new `# type: ignore` or `# noqa` suppressions without a reason on the same line.
- No stubs (`raise NotImplementedError`) standing in for logic past the slice that owns it.
- No skipped or deleted tests without the reason in the commit message.
- No secrets in source. The optional Claude backend reads its key from the environment only.

## Enforced with numbers

| Dimension | Rule | Checked by |
|---|---|---|
| Lint | zero ruff findings | `uv run ruff check src scripts tests` |
| Tests | 47 tests pass, every geometry change ships with a tolerance test | `uv run pytest -q` |
| Dependencies | no known vulnerabilities | `uv run pip-audit` |
| Reproducibility | the same capture gives the same plan (RANSAC seeded) | rerun `scripts/floorplan.py`, diff plan.json |

## Measured, not yet enforced

Values on 2026-09-20. Each one must not regress; a tightening is silent, a loosening goes in the commit message.

| Metric | Today | Direction |
|---|---|---|
| Synthetic 3 x 4 m room, area error | under 0.05 m2 | keep |
| Synthetic two-room doorway split | 2 rooms, door width 0.6 to 1.3 m | keep |
| Synthetic door and window widths | within 10 cm | keep |
| Synthetic yaw drift 1.2 deg/s | recovered within 5 deg/min | keep |
| Bedroom depth tier walls vs tape (427 x 366 cm) | -1.3 and +1.8 percent | must not widen |
| Bedroom depth tier ceiling vs tape (312 cm) | -10.6 cm | must shrink |
| Bedroom photo tier walls, poses plus MoGe FOV anchor | -2.6 and -3.8 percent | must not widen |
| Bedroom photo tier walls, no poses (MoGe-2) | -7.4 and -9.0 percent | must not widen |
| Bedroom video tier walls, MoGe FOV anchor | -4.6 and -2.6 percent | must not widen |
| Bedroom, one wall given as reference length: other wall, photos / video | -1.3 / +2.0 percent | must not widen |
| Sample crack (single_room) | labelled crack | keep |
| Undamaged bedroom | 0 damage regions | keep |
| LiDAR sample rooms found | 3, 6, 5 | keep |
| Peak VRAM, any stage | 7.6 GB (video chunks), 4.5 GB (damage) | under 8 GB |
| Full run, single_scan_with_ceiling (9745 frames) | about 12 minutes | keep under 15 |

## Not applicable

Accessibility and page-performance budgets, bundle size: the capture page is a
single static file with one library.
