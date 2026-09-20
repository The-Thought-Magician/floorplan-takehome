# ADR-0005: damage detection is two local open models, not an API

## Status
Accepted

## Context
The output contract needs damage regions with class and metric extent. A
vision API would do it well but costs money per image, needs a key on the run
machine, and the user declined it. Open task-specific weights cover cracks only.

## Decision
OWLv2 (Apache 2.0) proposes candidate boxes for all four classes at a low
threshold. Qwen3-VL-2B-Instruct (Apache 2.0) looks at each crop and answers
one of crack, water_stain, mould, peeling_paint, none. The answer decides the
class and whether the region survives. Both run locally in under 5 GB.

## Alternatives considered
- Claude vision: wired as an optional backend, off by default (cost, key).
- OWLv2 alone: localizes but confuses classes and fires on shadows.
- Crack-only segmenters (YOLOv8-crack-seg, SegFormer DeepCrack): one class,
  AGPL or unspecified license.
- Qwen2.5-VL-3B: non-commercial license, 7.5 GB, out.

## Consequences
Classification quality is that of a 2B model; tested on one real crack and one
undamaged room only. Every candidate and rejection is written to damage.json
so precision can be audited once more damage images exist.
