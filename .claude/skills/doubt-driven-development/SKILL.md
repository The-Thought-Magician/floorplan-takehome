<!-- sourced from: addyosmani/agent-skills (doubt-driven-development), trimmed: cross-model CLI escalation (gemini/codex) kept as an optional offer, not a mandatory ritual, since this is a solo take-home with no team review process -->
---
name: doubt-driven-development
description: >
  Cross-examine a non-trivial decision with a fresh-context adversarial
  review before it stands, while course-correction is still cheap. Use for
  architecture decisions under uncertainty, a claim about correctness or
  scaling, or working in code you don't fully understand. Skip for
  mechanical changes and one-line fixes.
---

# Doubt Driven Development

A confident answer is not a correct one. This is an in-flight check on a
decision, not a final review of a finished artifact.

Non-trivial means at least one of: introduces branching logic, crosses a
module boundary, asserts a property nothing mechanically verifies (thread
safety, a geometric invariant, a unit assumption), or is expensive to
reverse.

## Process

1. **Claim.** State the decision and why it matters in two lines.
   `CLAIM: the plane-fitting threshold is safe for both dense LiDAR and
   sparse SfM point clouds. WHY IT MATTERS: wrong threshold silently drops
   real walls or keeps noise as a wall.`

2. **Extract.** Pull out just the artifact (the function or diff) and the
   contract (what it must satisfy), stripped of your reasoning. Handing over
   your conclusions gets you agreement with your conclusions back.

3. **Doubt.** Spawn a fresh-context reviewer (a subagent with no memory of
   this conversation) with an adversarial prompt: find unstated assumptions,
   edge cases, ways the contract could be violated. Do not pass it the
   claim, only the artifact and contract.

4. **Reconcile.** Classify each finding: contract was unclear (fix the
   contract), real and actionable (fix the artifact), a real trade-off worth
   accepting (document it), or noise (the reviewer lacked context). Don't
   rubber-stamp the reviewer, re-read the artifact against each finding.

5. **Stop.** When the next round only returns trivial or repeated findings,
   or after 3 cycles, whichever comes first. Three unresolved cycles means
   the artifact isn't ready, not a reason to grind a fourth round alone.

## Scope discipline

Don't spawn a reviewer for a one-line rename. Reserve this for the handful
of genuinely load-bearing calls in the pipeline: the scale-recovery approach
per tier, the shared geometry schema, any threshold that silently changes
correctness rather than crashing.
