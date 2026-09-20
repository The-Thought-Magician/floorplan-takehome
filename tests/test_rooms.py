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
