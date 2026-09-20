<!-- sourced from: addyosmani/agent-skills (constraint-driven-development), heavily trimmed: JS/web toolchain (eslint, lighthouse, axe, size-limit, dependency-cruiser) replaced with Python equivalents; accessibility/performance-budget dimensions dropped as not applicable to a local geometry pipeline -->
---
name: constraint-driven-development
description: >
  Write the project's quality bar down as CONSTRAINTS.md so it survives the
  session and can be checked mechanically, and watch diffs for it being
  quietly weakened. Use once early in the project, and again anytime an
  agent starts writing more code than gets read line by line.
---

# Constraint Driven Development

A quality bar in prose gets forgotten under time pressure. Written down with
numbers and a command that checks it, it survives.

## The floor (always enforced, no setup)

- No new `# type: ignore` or `# noqa` suppressions without a reason.
- No unimplemented stubs (`raise NotImplementedError` standing in for real
  logic) left past the slice that was supposed to implement it.
- No skipped or deleted tests without a reason in the commit message.
- No secrets in source.

## CONSTRAINTS.md

```markdown
# Constraints

## Floor
(the four rules above)

## Enforced with numbers

| Dimension | Rule | Checked by |
|---|---|---|
| Types | zero mypy errors | `uv run mypy src` |
| Lint | zero ruff errors | `uv run ruff check` |
| Tests | changed logic has a test against a known value | `uv run pytest` |
| Dependencies | nothing at high severity | `uv run pip-audit` |

## Measured, not yet enforced
| Metric | Today | Direction |
|---|---|---|
| Reconstruction error on the synthetic cube test | <value> | must not regress |
```

Pick numbers by measuring where the codebase is today and refusing to
regress, rather than inventing an aspirational target that just gets
ignored.

## Guarding the bar

At review time, diff `CONSTRAINTS.md` against its state at the start of the
task. Watch for: a threshold quietly lowered, a test skipped or deleted
instead of fixed, a new suppression comment, a stub left in place of real
logic. Tightening the bar is silent and fine, loosening it should be loud
and explicit.

## Not applicable here

Accessibility and page-performance budgets (no UI), bundle size (not a web
app). Skip them rather than inventing a check that can't run.
