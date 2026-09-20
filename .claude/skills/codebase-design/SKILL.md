<!-- sourced from: mattpocock/skills (codebase-design), addyosmani/agent-skills (api-and-interface-design, trimmed to what applies outside REST/idempotency) -->
---
name: codebase-design
description: >
  Vocabulary and principles for designing deep modules and clean interfaces
  between them. Use when designing or improving a module's interface,
  deciding where a seam goes, splitting the pipeline into stages, or making
  code testable.
---

# Codebase Design

Design deep modules: a lot of behavior behind a small interface, placed at a
clean seam, testable through that interface.

## Glossary

- **Module**: anything with an interface and an implementation, scale
  agnostic, a function, class, or a pipeline stage.
- **Interface**: everything a caller must know to use the module correctly,
  types, invariants, ordering, error modes, not just the type signature.
- **Depth**: leverage at the interface. A module is deep when a lot of
  behavior sits behind a small interface, shallow when the interface is
  nearly as complex as what's behind it.
- **Seam**: the place where a module's interface lives, where behavior can
  be swapped without editing the call site.
- **Adapter**: a concrete thing satisfying an interface at a seam.

## Deep vs shallow

Deep: small interface, lots of implementation behind it. Shallow (avoid):
large interface, thin pass-through implementation.

When designing an interface: can the number of methods shrink, can the
parameters simplify, can more complexity move inside.

## Principles

- Depth is a property of the interface, not the implementation. Internal
  helper functions don't need to be part of the public seam.
- The deletion test: imagine removing the module. If complexity vanishes, it
  was a pass-through. If it reappears at every caller, the module earned its
  keep.
- The interface is the test surface, tests cross the same seam callers do.
- One adapter is a hypothetical seam. Two adapters is a real one, don't
  introduce a seam for variation that doesn't exist yet.

For this take-home: the natural seams are capture-in (raw photos/frames/
point cloud in), reconstruct (produces a point cloud or mesh regardless of
input tier), dimension (extracts a room polygon and measurements from
geometry), and export (renders a floor plan). Each input tier is a different
adapter feeding the same reconstruct interface, not three separate
pipelines, so downstream code doesn't care which tier produced the geometry.

## Designing for testability

Accept dependencies as parameters rather than constructing them inside a
function. Return results instead of mutating shared state where practical.
Small surface area means fewer tests needed to cover it fully.

## Contracts at the seam

Define the interface (types in, types out, error modes) before implementing
behind it. Pick one error-handling strategy for the module and use it
consistently, don't mix exceptions and sentinel-value returns across
functions that do the same kind of thing. Validate at the true boundary
(user-supplied input, an external file format, a captured device data
format), trust internal code past that point.
