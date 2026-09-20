<!-- sourced from: mattpocock/skills (domain-modeling), addyosmani/agent-skills (documentation-and-adrs) -->
---
name: documentation-and-decisions
description: >
  Keep a glossary of project terms current and record architecture decisions
  (ADRs) as they're made. Use when discussing or naming a domain concept,
  choosing between competing technical approaches, or making a decision that
  would be expensive to reverse.
---

# Documentation and Decisions

## Glossary (CONTEXT.md)

A glossary, nothing else, no implementation details, no scratch notes. Create
it lazily, the first time a term needs pinning down.

- Challenge conflicting terms immediately: if a word is used two different
  ways in the same conversation, stop and ask which one is meant.
- Sharpen vague terms into a precise canonical one (e.g. "capture" could mean
  a single photo, a video frame, or a full walkthrough session, pick one word
  per concept and use it everywhere).
- Update the glossary inline the moment a term resolves, don't batch it.

## ADRs

Write one only when all three are true: the decision is hard to reverse, it
would look surprising to a future reader without context, and it was a real
trade-off between genuine alternatives. Skip it otherwise, not everything
needs one.

Store at `docs/decisions/NNNN-title.md`, sequential numbering, never
renumbered or deleted, a superseding decision gets a new ADR that references
the old one.

```markdown
# ADR-0001: <decision>

## Status
Accepted

## Context
The constraint or problem that forced a choice.

## Decision
What was chosen.

## Alternatives considered
Each alternative, why it was rejected.

## Consequences
What this commits us to.
```

For this take-home, ADR-worthy calls: choice of point-cloud library
(Open3D vs a hand-rolled approach), how scale is recovered per tier, whether
the pipeline shares one internal geometry representation across all three
tiers or not.

## Inline comments

Comment the why, never the what. Skip comments on self-explanatory code. No
commented-out code, delete it, git has the history. No TODOs left sitting,
either do it now or write it as a task in `docs/todo.md`.

## Documentation for agents

Keep CLAUDE.md and the spec/plan docs current as decisions change, an
outdated one is worse than none because it actively misleads the next
session.
