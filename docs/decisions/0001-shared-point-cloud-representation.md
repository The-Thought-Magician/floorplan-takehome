# ADR-0001: one metric y-up point cloud is the interface between tiers and geometry

## Status
Accepted

## Context
Three input tiers with different sensors and different failure modes have to
produce the same floor plan schema. The geometry (floor, walls, rooms, openings)
must not be written three times.

## Decision
Every tier's ingest ends in the same thing: a metric point cloud with y up plus
camera positions, in one world frame. All geometry code consumes only that.
Tier-specific knowledge stays inside ingest (Stray Scanner conventions, ARCore
fill rejection, VGGT scale anchors).

## Alternatives considered
- Per-tier floor plan extractors: three times the geometry code, three sets of
  bugs, no shared tests.
- A mesh (RoomPlan style) as the interface: needs surface reconstruction that
  fails on noisy ARCore clouds and adds nothing the density masks need.

## Consequences
Tiers can only differ in how good their cloud is, which is what the benchmark
measures. Any geometry improvement (multi-room, openings, outer wall face)
lands on all tiers at once. The cost is that a tier with extra information
(ARCore depth per pixel, VGGT per-frame confidence) only carries it through
as a scale anchor or a point filter, not into the geometry stage.
