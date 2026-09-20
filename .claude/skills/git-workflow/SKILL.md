<!-- sourced from: addyosmani/agent-skills (git-workflow-and-versioning), mattpocock/skills (resolving-merge-conflicts). Release/versioning/worktree-parallel-agent sections dropped as not applicable to a solo take-home repo with no consumers. -->
---
name: git-workflow
description: >
  Commit discipline for this repo, atomic commits, message format,
  pre-commit hygiene, and how to resolve an in-progress merge or rebase
  conflict. Use whenever committing, or when a merge/rebase has conflicts.
---

# Git Workflow

## Commit discipline

Commit each working increment, don't accumulate a giant uncommitted diff.
Each commit does one logical thing, tests pass before committing.

```
implement slice -> test -> verify -> commit -> next slice
```

Message format, per the CLAUDE.md rules for this repo: short imperative
summary line, no em dash, plain language, no attribution footer.

```
add plane segmentation for lidar tier

fits walls/floor/ceiling from a point cloud via RANSAC, outputs
a room polygon with dimensions in cm
```

Separate concerns: a refactor and a feature are two commits. Formatting-only
changes never mixed with behavior changes.

## Pre-commit hygiene

Before every commit: check `git diff --staged`, confirm no secrets, run the
test command, run type/lint checks if configured.

## Resolving a merge or rebase conflict

1. See the current state, `git status`, and the conflicting files.
2. Understand why each side changed what it changed, check commit messages
   and history for original intent.
3. Resolve each hunk preserving both intents where possible, pick the side
   matching the overall goal where they conflict, note the trade-off. Never
   invent new behavior to paper over a conflict. Never `--abort` to dodge it.
4. Run tests and any checks, fix anything the merge broke.
5. Stage everything, finish the merge or continue the rebase.

## What to avoid

Committing generated artifacts (`.venv/`, `__pycache__/`, `data/` capture
files). Committing `.env` or any secret. A commit message like "wip" or
"fix stuff". Force-pushing without being asked.
