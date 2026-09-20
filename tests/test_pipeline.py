import json
import zipfile

import numpy as np
import open3d as o3d
from fastapi.testclient import TestClient

from floorplan_takehome import server
from floorplan_takehome.pipeline import reconstruct


def _room_cloud(width=3.0, depth=4.0, height=2.5, n=400):
    rng = np.random.default_rng(0)

    def wall(x_range, z_range, y_range=(0.0, height)):
        return np.stack(
            [rng.uniform(*x_range, n), rng.uniform(*y_range, n), rng.uniform(*z_range, n)], axis=1
        )

    points = np.concatenate(
        [
            wall((0, 0), (0, depth)),
            wall((width, width), (0, depth)),
            wall((0, width), (0, 0)),
            wall((0, width), (depth, depth)),
            wall((0, width), (0, depth), (0, 0)),
            wall((0, width), (0, depth), (height, height)),
        ]
    )
    cloud = o3d.geometry.PointCloud()
    cloud.points = o3d.utility.Vector3dVector(points)
    return cloud


def test_reconstruct_emits_schema_with_dimensions_in_cm():
    plan = reconstruct(_room_cloud(), source_tier="depth")
    room = plan["rooms"][0]
    assert room["source_tier"] == "depth"
    assert len(room["polygon_cm"]) == 4
    assert abs(room["area_m2"] - 12.0) < 0.3
    assert abs(room["wall_height_cm"] - 250) < 10
    assert sorted(round(l / 100) for l in room["wall_lengths_cm"]) == [3, 3, 4, 4]
    assert 0 < room["confidence"] <= 1
    assert plan["diagnostics"]["closed"]


def _capture_zip(tmp_path, grid):
    identity = np.eye(4).flatten(order="F").tolist()
    proj = np.diag([1.0, 1.0, 1.0, 1.0]).flatten(order="F").tolist()
    capture = {
        "captures": [
            {"views": [{"transform_matrix": identity, "projection_matrix": proj, "depth_grid_meters": grid}]}
        ]
    }
    zip_path = tmp_path / "capture.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("capture.json", json.dumps(capture))
        zf.writestr("photos/0000.jpg", b"not really a jpeg")
    return zip_path


def test_server_accepts_zip_and_reports_result(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAPTURES_DIR", tmp_path / "captures")
    client = TestClient(server.app)

    with open(_capture_zip(tmp_path, [[1.0, 2.0], [1.5, 2.5]]), "rb") as f:
        res = client.post("/api/captures", files={"file": ("capture.zip", f, "application/zip")})
    assert res.status_code == 200
    capture_id = res.json()["id"]

    import time

    for _ in range(50):
        status = client.get(f"/api/captures/{capture_id}").json()
        if status["state"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert status["state"] == "done", status
    assert status["plan"]["rooms"][0]["polygon_cm"] == []
    assert status["plan"]["capture"]["photos"] == ["0000.jpg"]
    assert client.get(f"/api/captures/{capture_id}/plan.png").status_code == 200
    assert capture_id in client.get("/api/captures").json()


def test_server_rejects_zip_without_capture_json(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAPTURES_DIR", tmp_path / "captures")
    client = TestClient(server.app)
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("readme.txt", "nope")
    with open(bad, "rb") as f:
        res = client.post("/api/captures", files={"file": ("bad.zip", f, "application/zip")})
    assert res.status_code == 400


def test_index_page_is_served():
    res = TestClient(server.app).get("/")
    assert res.status_code == 200
    assert "immersive-ar" in res.text


def test_video_can_be_uploaded_separately(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "CAPTURES_DIR", tmp_path / "captures")
    client = TestClient(server.app)
    with open(_capture_zip(tmp_path, [[1.0]]), "rb") as f:
        capture_id = client.post("/api/captures", files={"file": ("capture.zip", f, "application/zip")}).json()["id"]
    res = client.post(f"/api/captures/{capture_id}/video", files={"file": ("video.webm", b"webm bytes", "video/webm")})
    assert res.status_code == 200 and res.json()["video_bytes"] == 10
    assert (tmp_path / "captures" / capture_id / "video.webm").read_bytes() == b"webm bytes"
    assert client.post("/api/captures/nope/video", files={"file": ("v.webm", b"x", "video/webm")}).status_code == 404


def test_files_only_upload_gets_an_empty_depth_plan(tmp_path):
    d = tmp_path / "cap"
    (d / "photos" / "kitchen").mkdir(parents=True)
    (d / "capture.json").write_text(json.dumps({"captures": [], "upload": {"kind": "files"}}))
    (d / "photos" / "kitchen" / "0000.jpg").write_bytes(b"x")
    from floorplan_takehome.pipeline import process_capture_dir

    plan = process_capture_dir(d)
    assert plan["rooms"] == [] and plan["capture"]["kind"] == "files"
    assert plan["capture"]["photos"] == ["photos/kitchen/0000.jpg"]
