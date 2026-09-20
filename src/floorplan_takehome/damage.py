"""Per-surface damage regions with class and metric extent, plus concealed-damage flags.

Two detector backends, chosen at runtime:
- "owlv2": google/owlv2-base-patch16-ensemble, open-vocabulary detection run locally
  (Apache 2.0, ~150M params, no network after the first download). Default.
- "claude": Claude vision through the Anthropic SDK when ANTHROPIC_API_KEY (or an
  `ant auth login` profile) is present. Higher quality on subtle stains, needs network.
  Disclosed in the plan output as `detector`.

Metric extent: a detection box in a photo becomes a region on a surface by casting the
box centre and edges along the camera ray onto the wall plane the camera is facing,
using the photo's pose and the room polygon. With a depth frame for the photo (web
capture, Stray Scanner) the depth at the box centre is used instead of the plane hit.
Concealed-damage rules are explicit and named in the output so a reviewer can see
which rule fired.
"""

import base64
import json
import os
import re
from pathlib import Path

import numpy as np

CLASSES = {
    "water_stain": ["water stain on wall", "water damage stain", "damp patch on wall", "brown stain on ceiling"],
    "crack": ["crack in wall", "crack in plaster", "wall crack"],
    "mould": ["black mould on wall", "mold patch", "mildew on wall"],
    "peeling_paint": ["peeling paint", "flaking paint", "blistering paint"],
}

# rule name -> (condition description, flag text). Conditions are evaluated in flag_concealed.
CONCEALED_RULES = {
    "stain_on_ceiling": "water stain on a ceiling: check the floor or roof above for an active leak",
    "stain_low_on_wall": "water stain within 40 cm of the floor: check for rising damp or a leaking pipe behind the wall",
    "mould_present": "mould: moisture source behind the surface is likely, check ventilation and hidden leaks",
    "crack_at_opening": "crack within 50 cm of a door or window: possible lintel or frame movement, check the opening head",
    "crack_long": "crack longer than 1 m: structural review before cosmetic repair",
    "stain_below_window": "stain below a window: check the window seal and sill flashing",
}


def detector_backend() -> str:
    if os.environ.get("FLOORPLAN_DETECTOR"):
        return os.environ["FLOORPLAN_DETECTOR"]
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return "claude"
    return "owlv2"


def detect_owlv2(image_paths: list[str], threshold: float = 0.25) -> dict[str, list[dict]]:
    """Open-vocabulary detection. Returns per image a list of {class, score, box} with box in
    normalized [x0, y0, x1, y1] image coordinates."""
    import torch
    from PIL import Image
    from transformers import Owlv2ForObjectDetection, Owlv2Processor

    device = "cuda" if torch.cuda.is_available() else "cpu"
    processor = Owlv2Processor.from_pretrained("google/owlv2-base-patch16-ensemble")
    model = Owlv2ForObjectDetection.from_pretrained("google/owlv2-base-patch16-ensemble").to(device).eval()
    prompts = [p for ps in CLASSES.values() for p in ps]
    prompt_class = [c for c, ps in CLASSES.items() for _ in ps]

    results = {}
    for path in image_paths:
        image = Image.open(path).convert("RGB")
        inputs = processor(text=[prompts], images=image, return_tensors="pt").to(device)
        with torch.no_grad():
            outputs = model(**inputs)
        # OWLv2 pads to a square: normalize against the padded size, which is max(w, h)
        side = max(image.size)
        target = torch.tensor([[side, side]], device=device)
        det = processor.post_process_grounded_object_detection(outputs, threshold=threshold, target_sizes=target, text_labels=[prompts])[0]
        w, h = image.size
        found = []
        for score, label, box in zip(det["scores"].tolist(), det["labels"].tolist(), det["boxes"].tolist()):
            x0, y0, x1, y1 = box
            found.append(
                {
                    "class": prompt_class[label],
                    "prompt": prompts[label],
                    "score": round(float(score), 3),
                    "box": [round(x0 / w, 4), round(y0 / h, 4), round(min(x1, w) / w, 4), round(min(y1, h) / h, 4)],
                }
            )
        results[path] = _reclassify_crops(_merge_overlaps(found), image, processor, model, prompts, prompt_class, device)
    del model
    if device == "cuda":
        torch.cuda.empty_cache()
    return results


def _reclassify_crops(found, image, processor, model, prompts, prompt_class, device, margin: float = 0.15):
    """Whole-frame detection localizes well but confuses classes. Re-score each region on a
    tight crop: the class whose best prompt scores highest on the crop wins, and the crop
    score is kept as the region score when it is higher than the frame score."""
    import torch

    w, h = image.size
    for f in found:
        x0, y0, x1, y1 = f["box"]
        bw, bh = x1 - x0, y1 - y0
        crop = image.crop((int(max(0, x0 - margin * bw) * w), int(max(0, y0 - margin * bh) * h), int(min(1, x1 + margin * bw) * w), int(min(1, y1 + margin * bh) * h)))
        if min(crop.size) < 32:
            continue
        inputs = processor(text=[prompts], images=crop, return_tensors="pt").to(device)
        with torch.no_grad():
            out = model(**inputs)
        # per-prompt best score anywhere in the crop
        scores = torch.sigmoid(out.logits[0]).max(dim=0).values.tolist()
        by_class = {}
        for sc, cls in zip(scores, prompt_class):
            by_class[cls] = max(by_class.get(cls, 0.0), sc)
        best_cls = max(by_class, key=by_class.get)
        f["class_scores"] = {k: round(v, 3) for k, v in by_class.items()}
        f["frame_class"] = f["class"]
        f["class"] = best_cls
        f["score"] = round(max(f["score"], by_class[best_cls]), 3)
    return found


def detect_claude(image_paths: list[str]) -> dict[str, list[dict]]:
    """Claude vision: one request per image, JSON list of regions with normalized boxes."""
    import anthropic

    client = anthropic.Anthropic()
    system = (
        "You inspect interior photos for building damage. Report only visible damage of these classes: "
        + ", ".join(CLASSES)
        + ". Answer with a JSON array only. Each item: {\"class\": <class>, \"score\": 0-1, "
        "\"box\": [x0, y0, x1, y1] as fractions of image width and height, \"note\": short}. "
        "Empty array if there is no damage. Do not report furniture, shadows, wiring or decor."
    )
    results = {}
    for path in image_paths:
        data = base64.standard_b64encode(Path(path).read_bytes()).decode()
        media = "image/png" if path.lower().endswith(".png") else "image/jpeg"
        response = client.messages.create(
            model="claude-opus-5",
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": [{"type": "image", "source": {"type": "base64", "media_type": media, "data": data}}, {"type": "text", "text": "List the damage regions."}]}],
        )
        if response.stop_reason == "refusal":
            results[path] = []
            continue
        text = "".join(b.text for b in response.content if b.type == "text")
        match = re.search(r"\[.*\]", text, re.S)
        try:
            items = json.loads(match.group(0)) if match else []
        except json.JSONDecodeError:
            items = []
        results[path] = [i for i in items if i.get("class") in CLASSES and isinstance(i.get("box"), list) and len(i["box"]) == 4]
    return results


def _merge_overlaps(found: list[dict], iou_threshold: float = 0.5) -> list[dict]:
    """Same-class boxes overlapping strongly are one region, keep the best score."""
    found = sorted(found, key=lambda f: -f["score"])
    kept = []
    for f in found:
        dup = False
        for k in kept:
            if k["class"] != f["class"]:
                continue
            ax0, ay0, ax1, ay1 = f["box"]
            bx0, by0, bx1, by1 = k["box"]
            inter = max(0, min(ax1, bx1) - max(ax0, bx0)) * max(0, min(ay1, by1) - max(ay0, by0))
            union = (ax1 - ax0) * (ay1 - ay0) + (bx1 - bx0) * (by1 - by0) - inter
            if union > 0 and inter / union > iou_threshold:
                dup = True
                break
        if not dup:
            kept.append(f)
    return kept


def _ray(box_uv: tuple[float, float], projection: np.ndarray, cam_to_world: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """World-space ray through a normalized image point (u right, v down), WebXR camera axes."""
    fx, fy = projection[0, 0], projection[1, 1]
    ndc_x, ndc_y = box_uv[0] * 2 - 1, 1 - box_uv[1] * 2
    d_cam = np.array([ndc_x / fx, ndc_y / fy, -1.0])
    d_world = cam_to_world[:3, :3] @ d_cam
    return cam_to_world[:3, 3], d_world / np.linalg.norm(d_world)


def _hit_room_surface(origin: np.ndarray, direction: np.ndarray, room: dict, floor_y: float | None, ceiling_y: float | None) -> tuple[str, np.ndarray, float] | None:
    """Nearest hit among the room's wall planes (vertical, through polygon edges), floor and ceiling."""
    best = None
    poly = np.array(room["polygon_cm"], dtype=float) / 100.0
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        edge = b - a
        normal = np.array([-edge[1], 0.0, edge[0]])
        normal /= np.linalg.norm(normal) + 1e-9
        p0 = np.array([a[0], 0.0, a[1]])
        denom = normal @ direction
        if abs(denom) < 1e-6:
            continue
        t = ((p0 - origin) @ normal) / denom
        if t <= 0.05:
            continue
        hit = origin + t * direction
        along = (np.array([hit[0], hit[2]]) - a) @ (edge / (np.linalg.norm(edge) + 1e-9))
        if -0.1 <= along <= np.linalg.norm(edge) + 0.1 and (best is None or t < best[2]):
            best = (f"wall-{i}", hit, t)
    for name, y in (("floor", floor_y), ("ceiling", ceiling_y)):
        if y is None or abs(direction[1]) < 1e-6:
            continue
        t = (y - origin[1]) / direction[1]
        if t > 0.05 and (best is None or t < best[2]):
            best = (name, origin + t * direction, t)
    return best


def localize(detections: dict[str, list[dict]], photo_poses: dict[str, tuple[np.ndarray, np.ndarray]], rooms: list[dict],
             floor_y: float | None, ceiling_y: float | None, depth_lookup=None) -> list[dict]:
    """Detections to surface regions with metric extent.

    photo_poses: path -> (projection 4x4, cam_to_world 4x4). depth_lookup(path, u, v) -> metres or None.
    """
    regions = []
    for path, dets in detections.items():
        if path not in photo_poses:
            continue
        proj, c2w = photo_poses[path]
        for d in dets:
            x0, y0, x1, y1 = d["box"]
            cu, cv = (x0 + x1) / 2, (y0 + y1) / 2
            origin, direction = _ray((cu, cv), proj, c2w)
            hit = None
            for room in rooms:
                h = _hit_room_surface(origin, direction, room, floor_y, ceiling_y)
                if h and (hit is None or h[2] < hit[2]):
                    hit = h + (room["id"],)
            if hit is None:
                continue
            surface, point, dist, room_id = hit
            if depth_lookup is not None:
                depth = depth_lookup(path, cu, cv)
                if depth:
                    dist = float(depth)
                    point = origin + dist * direction
            # extent: box size in radians times distance
            fx, fy = proj[0, 0], proj[1, 1]
            width_m = (x1 - x0) * 2 / fx * dist
            height_m = (y1 - y0) * 2 / fy * dist
            regions.append(
                {
                    "class": d["class"],
                    "score": d.get("score"),
                    "room": room_id,
                    "surface": surface,
                    "centre_xyz_m": [round(float(v), 3) for v in point],
                    "height_above_floor_cm": round((float(point[1]) - floor_y) * 100, 1) if floor_y is not None else None,
                    "width_cm": round(width_m * 100, 1),
                    "height_cm": round(height_m * 100, 1),
                    "area_m2": round(width_m * height_m, 3),
                    "photo": str(path),
                    "box": d["box"],
                }
            )
    return regions


def flag_concealed(regions: list[dict], rooms: list[dict]) -> list[dict]:
    flags = []
    openings_by_room = {r["id"]: r.get("openings", []) for r in rooms}
    for reg in regions:
        fired = []
        h = reg.get("height_above_floor_cm")
        if reg["class"] == "water_stain" and reg["surface"] == "ceiling":
            fired.append("stain_on_ceiling")
        if reg["class"] == "water_stain" and h is not None and h < 40 and reg["surface"].startswith("wall"):
            fired.append("stain_low_on_wall")
        if reg["class"] == "mould":
            fired.append("mould_present")
        if reg["class"] == "crack" and max(reg["width_cm"], reg["height_cm"]) > 100:
            fired.append("crack_long")
        if reg["class"] in ("crack", "water_stain") and reg["surface"].startswith("wall"):
            wall_idx = int(reg["surface"].split("-")[1])
            for o in openings_by_room.get(reg["room"], []):
                if o.get("wall") == wall_idx and o.get("kind") in ("door", "window"):
                    fired.append("crack_at_opening" if reg["class"] == "crack" else "stain_below_window")
                    break
        for rule in dict.fromkeys(fired):
            flags.append({"room": reg["room"], "surface": reg["surface"], "class": reg["class"], "rule": rule, "text": CONCEALED_RULES[rule]})
    return flags


def scope_items(rooms: list[dict], regions: list[dict]) -> list[dict]:
    """Line items keyed to surfaces: areas per surface, plus a repair line per damage region."""
    items = []
    for room in rooms:
        lengths = room.get("wall_lengths_cm") or []
        height = room.get("wall_height_cm")
        for i, length in enumerate(lengths):
            area = round(length / 100 * height / 100, 2) if height else None
            items.append({"room": room["id"], "surface": f"wall-{i}", "item": "wall surface", "quantity_m2": area})
        if room.get("area_m2") is not None:
            items.append({"room": room["id"], "surface": "floor", "item": "floor surface", "quantity_m2": room["area_m2"]})
            items.append({"room": room["id"], "surface": "ceiling", "item": "ceiling surface", "quantity_m2": room["area_m2"]})
    repair = {
        "water_stain": "dry out, stain-block primer and repaint",
        "crack": "rake out, fill, tape and repaint",
        "mould": "treat, seal and repaint after moisture source fixed",
        "peeling_paint": "scrape, prime and repaint",
    }
    for reg in regions:
        items.append({"room": reg["room"], "surface": reg["surface"], "item": repair[reg["class"]], "quantity_m2": max(reg["area_m2"], 0.25), "damage_class": reg["class"]})
    return items


MIN_SCORE = {"owlv2": 0.40, "claude": 0.5}
MIN_SIDE_CM = 8.0  # anything smaller is a speck or a shadow edge, not a damage region


def run_damage(image_paths: list[str], photo_poses, rooms, floor_y, ceiling_y, depth_lookup=None, backend: str | None = None) -> dict:
    backend = backend or detector_backend()
    detections = detect_claude(image_paths) if backend == "claude" else detect_owlv2(image_paths)
    all_regions = localize(detections, photo_poses, rooms, floor_y, ceiling_y, depth_lookup)
    regions, rejected = [], []
    for r in all_regions:
        reasons = []
        if (r.get("score") or 0) < MIN_SCORE.get(backend, 0.3):
            reasons.append("low score")
        if min(r["width_cm"], r["height_cm"]) < MIN_SIDE_CM:
            reasons.append("too small")
        (rejected if reasons else regions).append({**r, "rejected": reasons} if reasons else r)
    return {
        "detector": {"backend": backend, "model": "claude-opus-5" if backend == "claude" else "google/owlv2-base-patch16-ensemble"},
        "raw_detections": {Path(k).name: v for k, v in detections.items()},
        "regions": regions,
        "rejected": rejected,
        "concealed_flags": flag_concealed(regions, rooms),
        "scope_items": scope_items(rooms, regions),
    }
