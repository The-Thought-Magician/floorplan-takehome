import numpy as np

from floorplan_takehome.rooms import _rectilinear_polygon, segment_rooms


def _box_points(x0, x1, z0, z1, floor=0.0, height=2.6, rng=None, n_wall=4000, n_floor=6000):
    rng = rng or np.random.default_rng(0)
    walls = []
    for (xa, xb, za, zb) in ((x0, x0, z0, z1), (x1, x1, z0, z1), (x0, x1, z0, z0), (x0, x1, z1, z1)):
        xs = rng.uniform(xa, xb, n_wall) if xa != xb else np.full(n_wall, xa)
        zs = rng.uniform(za, zb, n_wall) if za != zb else np.full(n_wall, za)
        walls.append(np.stack([xs, floor + rng.uniform(0.05, height - 0.05, n_wall), zs], axis=1))
    floor_pts = np.stack([rng.uniform(x0, x1, n_floor), np.full(n_floor, floor) + rng.normal(0, 0.01, n_floor), rng.uniform(z0, z1, n_floor)], axis=1)
    return np.concatenate(walls + [floor_pts])


def test_two_rooms_joined_by_a_doorway_are_split_and_dimensioned():
    rng = np.random.default_rng(1)
    a = _box_points(0, 4, 0, 3, rng=rng)
    b = _box_points(4, 7, 0, 3, rng=rng)
    pts = np.concatenate([a, b])
    # cut a 90 cm doorway into the shared wall at x=4 and put floor through it
    door = (np.abs(pts[:, 0] - 4) < 0.02) & (pts[:, 2] > 1.0) & (pts[:, 2] < 1.9) & (pts[:, 1] > 0.05)
    pts = pts[~door]

    rooms, info = segment_rooms(pts, floor_y=0.0, ceiling_y=2.6)
    assert info["rooms_found"] == 2
    areas = sorted(r.area_m2 for r in rooms)
    assert abs(areas[0] - 9.0) < 0.6 and abs(areas[1] - 12.0) < 0.7
    for r in rooms:
        assert len(r.corners_xz) == 4
        assert len(r.doorways) == 1
        assert 0.6 < r.doorways[0]["width_m"] < 1.3


def test_rectilinear_polygon_removes_small_notches():
    cell = 0.03
    mask = np.zeros((120, 160), dtype=bool)
    mask[10:110, 10:150] = True
    mask[10:14, 60:66] = False  # a 12 cm by 18 cm notch, smaller than a wall segment
    corners = _rectilinear_polygon(mask, cell, np.zeros(2))
    assert corners is not None and len(corners) == 4
    w = np.ptp(corners[:, 0])
    h = np.ptp(corners[:, 1])
    assert abs(w - 140 * cell) < 0.1 and abs(h - 100 * cell) < 0.1


def test_wall_openings_finds_a_door_and_a_window():
    from floorplan_takehome.rooms import wall_openings

    rng = np.random.default_rng(3)
    pts = _box_points(0, 4, 0, 3, rng=rng, n_wall=20000)
    # door 0.9 m wide on the z=0 wall from x=1.0, floor to 2.1 m
    door = (np.abs(pts[:, 2]) < 0.02) & (pts[:, 0] > 1.0) & (pts[:, 0] < 1.9) & (pts[:, 1] < 2.1)
    # window 1.2 m wide on the x=4 wall from z=0.8, sill 0.9 m to 2.0 m
    window = (np.abs(pts[:, 0] - 4) < 0.02) & (pts[:, 2] > 0.8) & (pts[:, 2] < 2.0) & (pts[:, 1] > 0.9) & (pts[:, 1] < 2.0)
    pts = pts[~door & ~window]
    corners = np.array([[0, 0], [4, 0], [4, 3], [0, 3]], dtype=float)
    found = wall_openings(pts, corners, floor_y=0.0, ceiling_y=2.6)
    kinds = sorted(o["kind"] for o in found)
    assert kinds == ["door", "window"], found
    door_o = next(o for o in found if o["kind"] == "door")
    window_o = next(o for o in found if o["kind"] == "window")
    assert abs(door_o["width_cm"] - 90) <= 10 and abs(window_o["width_cm"] - 120) <= 10


def test_room_heights_rejects_the_top_of_an_unscanned_wall_as_ceiling():
    from floorplan_takehome.rooms import room_heights

    rng = np.random.default_rng(4)
    corners = np.array([[0, 0], [4, 0], [4, 3], [0, 3]], dtype=float)
    # walls scanned only up to 2.1 m, no ceiling points at all
    pts = _box_points(0, 4, 0, 3, height=2.1, rng=rng)
    floor, ceiling = room_heights(pts, corners, floor_hint=0.0)
    assert abs(floor) < 0.03 and ceiling is None
    # now add a real ceiling layer at 2.7 m and walls up to it
    full = _box_points(0, 4, 0, 3, height=2.7, rng=rng)
    ceil_pts = np.stack([rng.uniform(0, 4, 6000), np.full(6000, 2.7) + rng.normal(0, 0.01, 6000), rng.uniform(0, 3, 6000)], axis=1)
    floor, ceiling = room_heights(np.concatenate([full, ceil_pts]), corners, floor_hint=0.0)
    assert ceiling is not None and abs(ceiling - 2.7) < 0.03
