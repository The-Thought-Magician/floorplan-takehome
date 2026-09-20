import numpy as np

from floorplan_takehome.damage import (
    _merge_overlaps,
    flag_concealed,
    localize,
    scope_items,
)


def _camera(position, yaw_deg=0.0):
    th = np.radians(yaw_deg)
    m = np.eye(4)
    m[:3, :3] = np.array([[np.cos(th), 0, np.sin(th)], [0, 1, 0], [-np.sin(th), 0, np.cos(th)]])
    m[:3, 3] = position
    return m


ROOM = {"id": "room-1", "polygon_cm": [[0, 0], [400, 0], [400, 300], [0, 300]], "wall_lengths_cm": [400, 300, 400, 300], "area_m2": 12.0, "wall_height_cm": 280.0,
        "openings": [{"wall": 0, "kind": "window", "from_corner_cm": 150, "width_cm": 120}]}


def test_localize_puts_a_centred_box_on_the_facing_wall_with_metric_extent():
    proj = np.diag([2.0, 1.0, 1.0, 1.0])  # fx=2, fy=1
    # camera at the room centre, 1.4 m up, looking down -z toward the z=0 wall (wall-0), 1.5 m away
    c2w = _camera([2.0, 1.4, 1.5])
    dets = {"p.jpg": [{"class": "water_stain", "score": 0.9, "box": [0.4, 0.4, 0.6, 0.6]}]}
    regions = localize(dets, {"p.jpg": (proj, c2w)}, [ROOM], floor_y=0.0, ceiling_y=2.8)
    assert len(regions) == 1
    r = regions[0]
    assert r["surface"] == "wall-0" and r["room"] == "room-1"
    assert abs(r["height_above_floor_cm"] - 140) < 1
    # box is 20 percent of the image: width = 0.2 * 2 / fx * dist = 0.2 * 1.5 = 0.3 m, height = 0.2 * 2 / fy * 1.5 = 0.6 m
    assert abs(r["width_cm"] - 30) < 1 and abs(r["height_cm"] - 60) < 1


def test_concealed_rules_fire_by_name():
    regions = [
        {"class": "water_stain", "surface": "ceiling", "room": "room-1", "height_above_floor_cm": 280, "width_cm": 40, "height_cm": 30},
        {"class": "crack", "surface": "wall-0", "room": "room-1", "height_above_floor_cm": 200, "width_cm": 20, "height_cm": 130},
    ]
    rules = sorted(f["rule"] for f in flag_concealed(regions, [ROOM]))
    assert rules == ["crack_at_opening", "crack_long", "stain_on_ceiling"]


def test_scope_items_key_every_surface_and_each_region():
    regions = [{"class": "crack", "surface": "wall-1", "room": "room-1", "area_m2": 0.1}]
    items = scope_items([ROOM], regions)
    surfaces = {i["surface"] for i in items}
    assert {"wall-0", "wall-1", "wall-2", "wall-3", "floor", "ceiling"} <= surfaces
    repair = [i for i in items if i.get("damage_class")]
    assert len(repair) == 1 and repair[0]["quantity_m2"] == 0.25


def test_merge_overlaps_collapses_duplicates():
    found = [
        {"class": "crack", "score": 0.9, "box": [0.1, 0.1, 0.3, 0.3]},
        {"class": "crack", "score": 0.5, "box": [0.11, 0.1, 0.31, 0.3]},
        {"class": "mould", "score": 0.4, "box": [0.1, 0.1, 0.3, 0.3]},
    ]
    assert len(_merge_overlaps(found)) == 2
