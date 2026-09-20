<!-- sourced from: addyosmani/agent-skills (idea-refine), trimmed script/file references not relevant outside its original repo -->
---
name: idea-refine
description: >
  Refine a vague idea into a sharp, actionable concept through divergent
  then convergent thinking. Use when an idea is still fuzzy, or to
  stress-test a plan before committing to it.
---

# Idea Refine

Three phases, don't skip to the end.

## Phase 1: understand and expand

Restate the idea as a crisp problem statement. Ask 3-5 sharpening
questions, no more: who is this for, what does success look like, what are
the real constraints, why now. Then generate 5-8 variations using lenses
like inversion, constraint removal, simplification, combination, 10x scale.
Push past the first three obvious answers.

If inside a codebase, ground variations in what actually exists, reference
real files and constraints rather than ideating in a vacuum.

## Phase 2: evaluate and converge

Cluster the ideas that resonated into 2-3 genuinely distinct directions.
Stress-test each on user value, feasibility, and differentiation. Surface
hidden assumptions explicitly: what's being bet on, what could kill it,
what's being deliberately ignored. Be honest, not supportive, push back on
weak ideas with specifics.

## Phase 3: sharpen and ship

Produce a short markdown one-pager:

```markdown
# <idea name>

## Problem statement
## Recommended direction
## Key assumptions to validate
## MVP scope
## Not doing (and why)
## Open questions
```

The "not doing" list is the most valuable part, it makes trade-offs
explicit instead of leaving them implicit.

## Anti-patterns

Generating 20+ shallow variations instead of a handful of considered ones.
Skipping "who is this for". Jumping to phase 3 without running 1 and 2.
Producing a plan with no assumptions surfaced.
