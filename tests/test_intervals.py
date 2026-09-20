from floorplan_takehome.intervals import add_intervals, interval


def test_lidar_interval_is_tight_and_photo_interval_is_wide():
    lo, hi = interval(400.0, "length", "lidar")
    assert hi - lo < 20
    lo2, hi2 = interval(400.0, "length", "photos", extra_cm=10)
    assert hi2 - lo2 > 100


def test_add_intervals_covers_every_measurement():
    plan = {"rooms": [{"wall_lengths_cm": [300.0, 400.0], "wall_height_cm": 280.0, "area_m2": 12.0, "openings": [{"width_cm": 90.0}]}]}
    add_intervals(plan, "lidar")
    r = plan["rooms"][0]
    assert len(r["wall_lengths_interval_cm"]) == 2
    assert r["wall_height_interval_cm"][0] < 280.0 < r["wall_height_interval_cm"][1]
    assert r["area_interval_m2"][0] < 12.0 < r["area_interval_m2"][1]
    assert r["openings"][0]["width_interval_cm"]
    assert "prior" in plan["interval_basis"]
