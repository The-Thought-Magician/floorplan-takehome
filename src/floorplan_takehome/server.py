"""Local backend: serves the capture page, accepts capture zips, runs the pipeline.

Run with scripts/serve.sh, which also opens a Cloudflare quick tunnel so the phone
gets an https origin (WebXR requires a secure context).
"""

import json
import logging
import re
import shutil
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from floorplan_takehome.pipeline import process_capture_dir, process_image_tiers, run_damage_for_capture

log = logging.getLogger("floorplan")

ROOT = Path(__file__).resolve().parents[2]
WEB_DIR = ROOT / "web-capture"
CAPTURES_DIR = ROOT / "data" / "captures"
MAX_UPLOAD_BYTES = 500 * 1024 * 1024

app = FastAPI(title="floorplan-takehome")
_status: dict[str, dict] = {}
_lock = threading.Lock()
_tier_lock = threading.Lock()


def _set(capture_id: str, **fields) -> None:
    with _lock:
        _status.setdefault(capture_id, {"id": capture_id})
        _status[capture_id].update(fields)


CAPTURE_ID = re.compile(r"^[0-9]{8}-[0-9]{6}-[0-9a-f]{6}$")


def _capture_dir(capture_id: str) -> Path:
    if not CAPTURE_ID.match(capture_id):
        raise HTTPException(404, "unknown capture")
    return CAPTURES_DIR / capture_id


def _safe_extract(zip_path: Path, dest: Path) -> None:
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        members = zf.infolist()
        if sum(m.file_size for m in members) > 4 * MAX_UPLOAD_BYTES:
            raise HTTPException(413, "zip expands too large")
        for member in members:
            if not (dest / member.filename).resolve().is_relative_to(dest):
                raise HTTPException(400, "zip contains unsafe paths")
        if not any(m.filename == "capture.json" for m in members):
            raise HTTPException(400, "zip has no capture.json")
        zf.extractall(dest)


def _run(capture_id: str, capture_dir: Path) -> None:
    _set(capture_id, state="processing", started=time.time())
    try:
        plan = process_capture_dir(capture_dir)
        _set(capture_id, state="done", plan=plan, finished=time.time(), tiers_state="running")
        with _tier_lock:  # one GPU job at a time
            process_image_tiers(capture_dir, plan)
            try:
                run_damage_for_capture(capture_dir, plan)
            except Exception as e:  # noqa: BLE001, damage is reported, never fatal
                log.exception("damage detection failed for %s", capture_id)
                plan["damage"] = {"error": f"{type(e).__name__}: {e}"}
        _set(capture_id, plan=plan, tiers_state="done")
    except Exception as e:  # noqa: BLE001, surfaced to the client
        log.exception("processing failed for %s", capture_id)
        _set(capture_id, state="failed", error=f"{type(e).__name__}: {e}", finished=time.time())


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/captures")
async def upload_capture(file: UploadFile):
    capture_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    capture_dir = CAPTURES_DIR / capture_id
    capture_dir.mkdir(parents=True, exist_ok=True)
    zip_path = capture_dir / "upload.zip"

    size = 0
    with open(zip_path, "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "upload too large")
            out.write(chunk)

    try:
        _safe_extract(zip_path, capture_dir)
    except zipfile.BadZipFile:
        shutil.rmtree(capture_dir, ignore_errors=True)
        raise HTTPException(400, "not a zip file")
    except HTTPException:
        shutil.rmtree(capture_dir, ignore_errors=True)
        raise

    _set(capture_id, state="queued", bytes=size)
    threading.Thread(target=_run, args=(capture_id, capture_dir), daemon=True).start()
    return {"id": capture_id, "state": "queued"}


@app.post("/api/captures/{capture_id}/video")
async def upload_video(capture_id: str, file: UploadFile):
    capture_dir = _capture_dir(capture_id)
    if not capture_dir.is_dir():
        raise HTTPException(404, "unknown capture")
    size = 0
    with open(capture_dir / "video.webm", "wb") as out:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "upload too large")
            out.write(chunk)
    return {"id": capture_id, "video_bytes": size}


@app.get("/api/captures/{capture_id}")
def capture_status(capture_id: str):
    with _lock:
        status = _status.get(capture_id)
    if status is None:
        plan_path = _capture_dir(capture_id) / "plan.json"
        if plan_path.exists():
            return {"id": capture_id, "state": "done", "plan": json.loads(plan_path.read_text())}
        raise HTTPException(404, "unknown capture")
    return JSONResponse(status)


@app.get("/api/captures/{capture_id}/plan.png")
def capture_png(capture_id: str, tier: str = "depth"):
    name = "plan.png" if tier == "depth" else f"plan_{tier}.png"
    if tier not in ("depth", "photos", "video"):
        raise HTTPException(400, "unknown tier")
    png = _capture_dir(capture_id) / name
    if not png.exists():
        raise HTTPException(404, "no plan image yet")
    return FileResponse(png, headers={"Cache-Control": "no-store"})


@app.get("/api/captures")
def list_captures():
    if not CAPTURES_DIR.exists():
        return []
    return sorted(p.name for p in CAPTURES_DIR.iterdir() if p.is_dir())
