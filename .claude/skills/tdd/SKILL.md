<!-- sourced from: mattpocock/skills (tdd), addyosmani/agent-skills (test-driven-development) -->
---
name: tdd
description: >
  Test-driven development, the red-green-refactor loop. Use when implementing
  any logic, fixing any bug, or changing any behavior that can be verified.
  Use when a bug report arrives, or before modifying existing functionality.
---

# Test-Driven Development

Write a failing test before the code that makes it pass. For bug fixes,
reproduce the bug with a test before attempting a fix. Tests are proof,
"seems right" is not done.

When NOT to use: pure configuration changes, docs, static content with no
behavioral impact.

## Discover the stack first

The cycle is universal, the commands are not. Before the first test, find
this repo's test framework, how it runs one focused test vs the full suite,
and where tests live and how they're named. Use those commands for every
step. For this repo: pytest, run `uv run pytest`.

## What a good test is

Tests verify behavior through public interfaces, not implementation details.
A good test reads like a specification and survives refactors because it
doesn't care about internal structure.

A **seam** is the public boundary you test at. Test only at pre-agreed seams,
not against internals. Before writing a test, know the seam: what's the
public interface, which capability is this proving.

Anti-patterns:
- Implementation-coupled: mocks internal collaborators, tests private
  methods, queries a side channel instead of the interface. Tell: it breaks
  on refactor when behavior hasn't changed.
- Tautological: the expected value is computed the same way the code
  computes it, so it can never disagree with the code. Expected values come
  from an independent source: a known-good literal, a worked example, a
  hand-computed geometry case.
- Horizontal slicing: writing all tests first, then all implementation.
  Work in vertical slices instead, one test, one minimal implementation,
  repeat, each test a tracer bullet informed by the last cycle.

## The loop

```
RED: write a failing test  ->  GREEN: minimum code to pass  ->  REFACTOR: clean up, tests stay green
```

- Red before green. Write the failing test first, then only enough code to
  pass it. Don't anticipate future tests or add speculative features.
- One slice at a time: one seam, one test, one minimal implementation per cycle.
- Refactoring is not part of the red-green loop, it happens after, paired
  with the `code-review` skill.

## The prove-it pattern for bugs

Bug report arrives, write a test that reproduces it first, confirm it fails,
then fix, then confirm it passes, then run the full suite for regressions.

## Writing good tests

- Test state and outcomes, not which internal methods got called.
- DAMP over DRY in tests: each test should read as a self-contained story,
  duplication that keeps a test independently understandable is fine.
- Prefer real implementations over fakes over stubs over mocks, in that
  order. Mock only when the real thing is slow, non-deterministic, or has
  side effects you can't control.
- Arrange-Act-Assert structure, one concept per test, descriptive test names
  that read like a spec.

For this take-home specifically: geometry/vision code should get correctness
tests against known values, a synthetic cube point cloud with known
dimensions, a set of 3D points with a known best-fit plane, not against
snapshots of the code's own output.

## Test anti-patterns

Testing implementation details, flaky/order-dependent tests, testing
third-party framework code instead of your own, snapshot abuse, tests that
pass individually but fail together (no isolation), mocking everything so
production breaks while tests stay green.

## Verification checklist

- Every new behavior has a corresponding test.
- Full suite passes with the repo's own command.
- Bug fixes include a reproduction test that failed before the fix.
- No tests skipped or disabled.
- Don't re-run a clean test command with no intervening code change.
