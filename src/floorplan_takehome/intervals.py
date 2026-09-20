"""Confidence intervals on every measurement.

Intervals come from a per-tier error model, not from the fit itself, because a plane
fit reports precision, not accuracy. The model is a prior until calibration data
(data/ground_truth/*.json against plan outputs) refits it, and every plan says which
it got. Width = absolute floor + relative part + alignment term for view models.
"""

import json
from pathlib import Path

# 95 percent half-widths. abs in cm, rel as a fraction of the value.
PRIORS = {
    "lidar": {"length": (3.0, 0.01), "height": (3.0, 0.0), "opening": (5.0, 0.0), "area": (0.0, 0.02), "basis": "prior: ARKit LiDAR 1-3 cm published, RoomPlan studies"},
    "depth": {"length": (8.0, 0.03), "height": (10.0, 0.05), "opening": (15.0, 0.0), "area": (0.0, 0.08), "basis": "prior set from one tape-checked room after the outer-face fix: walls within 2 percent, ceiling -11 cm"},
    "video": {"length": (10.0, 0.08), "height": (15.0, 0.05), "opening": (20.0, 0.0), "area": (0.0, 0.15), "basis": "prior, no ground truth yet"},
    "photos": {"length": (10.0, 0.10), "height": (15.0, 0.08), "opening": (25.0, 0.0), "area": (0.0, 0.20), "basis": "prior, no ground truth yet"},
}

CALIBRATION_FILE = Path(__file__).resolve().parents[2] / "data" / "calibration.json"


def _model(tier: str) -> dict:
    model = dict(PRIORS.get(tier, PRIORS["photos"]))
    if CALIBRATION_FILE.exists():
        fitted = json.loads(CALIBRATION_FILE.read_text()).get(tier)
        if fitted:
            model.update({k: tuple(v) if isinstance(v, list) else v for k, v in fitted.items()})
            model["basis"] = fitted.get("basis", "calibrated")
    return model


def interval(value: float | None, kind: str, tier: str, extra_cm: float = 0.0) -> list[float] | None:
    if value is None:
        return None
    abs_cm, rel = _model(tier)[kind]
    half = abs_cm + rel * abs(value) + extra_cm
    return [round(value - half, 1), round(value + half, 1)]


def add_intervals(plan: dict, tier: str, info: dict | None = None) -> dict:
    """Attach `*_interval` fields next to every measurement in the plan, in place."""
    info = info or {}
    # view models: alignment residual widens every length interval
    extra = float(info.get("camera_residual_cm_median") or 0.0) * 0.5 if tier in ("video", "photos") else 0.0
    for room in plan.get("rooms", []):
        lengths = room.get("wall_lengths_cm") or []
        room["wall_lengths_interval_cm"] = [interval(l, "length", tier, extra) for l in lengths]
        room["wall_height_interval_cm"] = interval(room.get("wall_height_cm"), "height", tier, extra)
        area = room.get("area_m2")
        if area is not None:
            _, rel = _model(tier)["area"]
            half = rel * area + 2 * (extra / 100) * (area**0.5)
            room["area_interval_m2"] = [round(area - half, 3), round(area + half, 3)]
        for o in room.get("openings", []):
            o["width_interval_cm"] = interval(o.get("width_cm"), "opening", tier, extra)
    for reg in (plan.get("damage") or {}).get("regions", []) if isinstance(plan.get("damage"), dict) else []:
        reg["width_interval_cm"] = interval(reg.get("width_cm"), "opening", tier, extra)
        reg["height_interval_cm"] = interval(reg.get("height_cm"), "opening", tier, extra)
    plan["interval_basis"] = _model(tier)["basis"]
    return plan
