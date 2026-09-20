<!-- sourced from: mattpocock/skills (to-spec, to-tickets, wayfinder), addyosmani/agent-skills (spec-driven-development, planning-and-task-breakdown). Issue-tracker plumbing from the sources dropped, replaced with plain markdown files in this repo. -->
---
name: spec-and-planning
description: >
  Turn a vague idea or requirement into a written spec and an ordered task
  list before writing code. Use when starting a new feature or module, when
  requirements are ambiguous, when a task feels too large to just start, or
  when a chunk of work spans more than one focused session.
---

# Spec and Planning

Code without a spec is guessing. Write the spec first, get it right, then
break it into small ordered tasks, then implement.

Skip this for single-line fixes or changes with obvious, unambiguous scope.

## Phase 1: Spec

Surface assumptions before writing anything:

```
ASSUMPTIONS:
1. ...
2. ...
-> correct now or proceeding with these
```

Write to `docs/spec-<name>.md`:

```markdown
# Spec: <name>

## Objective
What we're building, why, what success looks like.

## Approach
The chosen technical approach and why, versus alternatives considered.

## Interfaces
Module boundaries and their contracts. No file paths, they go stale.
Prefer the existing seam over a new one.

## Testing
What proves this works. Known-good reference values, not code-derived ones.

## Out of scope
What this explicitly does not cover.

## Open questions
Anything unresolved.
```

A capability map first if one requirement bundles several independently
testable pieces (e.g. this take-home's three input tiers): a small table of
module ids, responsibilities, and dependency order, before writing any
per-module spec.

## Phase 2: Plan and tasks

Save to `docs/plan.md` (architecture, risks, sequencing) and `docs/todo.md`
(the task checklist). Never overwrite either if it still has unchecked items
from different work, ask first.

Map the dependency graph, build foundations first. Slice vertically: each
task is a complete path through the layers it touches (data in, transform,
data out) that's independently demoable, not "build all of layer X."

Each task:

```markdown
- [ ] <title>
  - acceptance: <specific testable condition>
  - verify: <test/build command or manual check>
  - depends on: <task or "none">
```

Sizing: a task should fit one focused session, roughly under 5 files touched
and under 3 acceptance bullets. If it needs "and" in the title, it's two
tasks. Put checkpoints after every 2-3 tasks: tests pass, the pipeline still
runs end to end.

A wide mechanical change (rename a shared type, change a schema everywhere)
is the exception to vertical slicing: sequence it as expand (add the new
form alongside the old), migrate (batch by area), contract (delete the old
form), each its own task, so nothing stays broken in between.

## Red flags

Starting to code with no written spec. Task list items that just say
"implement the feature" with no acceptance criteria. All tasks are XL. No
dependency order. Overwriting another in-progress plan silently.
