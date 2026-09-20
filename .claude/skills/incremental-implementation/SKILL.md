<!-- sourced from: addyosmani/agent-skills (incremental-implementation), mattpocock/skills (implement) -->
---
name: incremental-implementation
description: >
  Execute a spec or task list in thin, verifiable slices instead of writing
  a large amount of code before testing anything. Use when implementing any
  change that touches more than one file or one pipeline stage.
---

# Incremental Implementation

Build one complete, testable slice at a time, then expand. Never write more
than about 100 lines before running something that verifies it.

```
implement -> test -> verify -> commit -> next slice
```

Prefer TDD at the agreed seam (see the `tdd` skill). Run the focused test
regularly, the full suite at the end of a slice. Once a slice is done, run
`code-review` on it before moving on. Commit before starting the next slice.

## Slicing for this pipeline

Vertical, not horizontal: one slice is a complete path through one stage for
one tier, not "build the entire geometry module first." E.g.:

```
Slice 1: load a synthetic point cloud, segment the floor plane, verify
         against a known plane equation
Slice 2: segment wall planes, extract a room polygon, verify dimensions
         against a known cube
Slice 3: wire the LiDAR tier end to end on one real capture
```

Risk-first: tackle the step most likely to fail early (e.g. whether Open3d's
plane segmentation gives usable results on a real noisy capture) before
building the pipeline stages around it.

## Rules

- Simplest thing that could work, first. Naive and obviously correct beats
  clever and unproven. Optimize only after correctness has a test proving it.
- Scope discipline: touch only what the slice needs. Notice something else
  worth fixing, note it, don't fix it inline.
  `NOTICED BUT NOT TOUCHING: <what>, <why it's separate>`
- One thing per commit. A refactor and a feature never share a commit.
- Keep it working: after each slice, the pipeline still runs end to end on
  at least the synthetic test case. Never leave it broken between slices.
- New code defaults to conservative behavior (e.g. flag a low-confidence
  reconstruction rather than silently returning a guess).

## Checklist per slice

- [ ] Does one thing, completely
- [ ] Existing tests still pass, `uv run pytest`
- [ ] New functionality has a test proving it against a known value
- [ ] Committed with a descriptive message

## Red flags

More than ~100 lines written without running a test. Scope creep ("let me
also clean up this other function"). Skipping verification to move faster.
Leaving the pipeline broken between slices.
