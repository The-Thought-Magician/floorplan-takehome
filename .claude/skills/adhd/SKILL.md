<!-- sourced from: UditAkhourii/adhd (adhd), kept close to original -->
---
name: adhd
description: >
  Parallel divergent ideation. Spawns isolated branches under different
  cognitive frames, scores, clusters, prunes traps, and deepens top
  survivors. Use on open-ended design/architecture decisions, e.g. how to
  unify the three input tiers into one schema, or how to recover scale in
  the photo-only tier. Skip for syntax, lookups, or anything with one
  canonical answer.
---

# ADHD

Stop picking the textbook answer. The first three answers are the answers
everyone gives. The interesting ones live past number three.

## Pre-flight gate

Skip this skill (answer directly) unless all three hold:
1. Open-ended: would a senior engineer give multiple viable answers, or is
   there one canonical one? Canonical, abort.
2. High-stakes: architecture decision, a naming choice that's expensive to
   reverse, a fuzzy bug with no known root cause. Not a quick pick, abort.
3. Open phrasing: the user didn't say "quick", "standard", "just", "one-line".

## Phase 1: diverge, no critic

Spawn 5 parallel isolated agent calls, one per chosen cognitive frame (pick
frames biased toward the problem shape, plus at least one wild one:
hardware engineer, regulator, 10-year-old, competitor trying to break it,
biology, logistics, inversion, remove-the-load-bearing-assumption,
speedrunner, 3am on-call). Each gets only the problem and the frame, and is
told: generate 6 short distinct ideas, don't evaluate, don't rank, the
obvious three are banned, output JSON only.

Branches must not see each other's output, isolation is what makes this
work.

## Phase 2: focus, critic on

Score every idea 0-10 on novelty, viability, fit. Flag traps (attractive
but a hidden cost or false economy). Cluster by underlying angle, not
surface keywords, into 3-6 groups. Deepen the top 3 (by weighted score) with
one more agent call each: a short sketch of how it works, the load-bearing
risk, the first concrete step, 3-5 child ideas.

## Output shape

Brief, wide set by cluster, a 2-4 idea shortlist with the non-obvious pick
marked, the deepened top 3, and one provocation question at the end.

## Anti-patterns

Ten variations of one idea is not divergence. A pile of unsorted absurdities
with no convergence is as useless as one safe answer. Always take a
position at the end, "here are 20 ideas, you decide" is a cop-out.
