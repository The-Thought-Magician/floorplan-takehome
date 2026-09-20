<!-- sourced from: mattpocock/skills (code-review), addyosmani/agent-skills (code-review-and-quality) -->
---
name: code-review
description: >
  Review changes before they land, whether the changes are since a fixed
  git point (a commit, branch, or merge-base) or a diff about to be
  committed. Use before merging any change, after finishing a feature or
  bug fix, or when asked to review a branch or work-in-progress.
---

# Code Review

Every non-trivial change gets reviewed before it's considered done. Approve a
change when it definitely improves the codebase, even if not perfect,
perfect code doesn't exist. Don't block on "not how I'd have written it."

## Two axes, kept separate

- **Spec**: does the change do what was asked? Missing requirements,
  unrequested scope creep, requirements that look done but are wrong.
- **Standards**: does it follow this repo's own conventions and the smell
  baseline below?

A change can pass one and fail the other, a spec-perfect change that breaks
project conventions is not a clean pass. Report them separately, don't blend
into one score.

For a real review of someone else's PR, spawn one subagent per axis so they
don't pollute each other's findings, then aggregate without reranking across
axes. For a solo self-review, run both passes yourself in sequence.

## The five-axis pass (within Standards + general quality)

1. **Correctness**: matches requirements, edge cases (null, empty, boundary,
   degenerate geometry), error paths not just happy path, tests actually
   test the right thing.
2. **Readability**: names are clear, control flow is straightforward, no
   nested ternaries for their own sake, could this be shorter, are
   abstractions earning their complexity (don't generalize until a third
   use case exists).
3. **Architecture**: fits existing module boundaries, no duplication that
   should be shared, dependencies flow one direction, a "cleaner" refactor
   actually reduces concepts a reader must hold rather than relocating them.
4. **Security**: input validated at boundaries, no secrets in code/logs,
   external data treated as untrusted before use.
5. **Performance**: no accidental O(n^2)/O(n^3) over point clouds or frame
   sequences where a spatial index or vectorized op would do, no unbounded
   loops over unbounded input.

## Fowler smell baseline (when the repo has no documented standard)

Mysterious name, duplicated code, feature envy, data clumps, primitive
obsession, repeated type-switches, shotgun surgery (one change forces edits
scattered everywhere), divergent change (one file changes for many unrelated
reasons), speculative generality, message chains, middle-man pass-through,
refused bequest. Each is a judgement call, not a hard violation, and a
documented repo convention overrides it.

## Severity labels

- **Critical:** blocks merge, security hole, data loss, broken functionality.
- *(no prefix)*: required, must fix before merge.
- **Nit:** optional, style only.
- **Consider:**: suggestion, not required.

Lead with what matters: correctness and security first, then structural
issues, then nits. One real structural problem beats ten nits in importance.

## Dependency discipline

Before adding a dependency: does the existing stack already cover this, is
it maintained, does it have known vulnerabilities, is the license fine.
Prefer stdlib and what's already installed. One dependency change per
commit, never a bulk "bump deps."

## Change descriptions

First line: short, imperative, standalone, explains what changed without
needing the diff open. Reject "fix bug," "wip," "updates."

## Verdict

End every review with either approve, or request changes with the specific
blocking items named. Don't leave it ambiguous.
