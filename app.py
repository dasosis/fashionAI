"""Local web app: upload photos -> 5 picture questions -> swipe deck (taste) + photo analysis (suitability)
-> three looks -> rendered images.

    .\\.venv\\Scripts\\python.exe app.py     then open the printed URL (works from a phone on the same Wi-Fi)

Every paid API call happens only on an explicit action. Re-running a finished call needs force=true,
and the previous output is archived to out/archive/, never silently overwritten. Swiping is free.
"""

import io
import os
import shutil
import socket
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from pydantic import BaseModel

import analysis
import config
import intake
import recommender
import render
import styles
from attributes import label
from common import list_photos, read_json, utc_now, write_json

load_dotenv(config.ROOT / ".env")
try:
    from pillow_heif import register_heif_opener   # iPhone HEIC uploads
    register_heif_opener()
except ImportError:
    pass

app = FastAPI(title="fashion-ai")
for d in (config.LOOKS_DIR, config.CATALOG_IMAGES_DIR, config.UPLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")
app.mount("/looks", StaticFiles(directory=config.LOOKS_DIR), name="looks")
app.mount("/catalog", StaticFiles(directory=config.CATALOG_IMAGES_DIR), name="catalog")

# Long calls run in the threadpool while the user keeps swiping, so session writes are serialized.
session_lock = threading.Lock()
jobs: dict[str, dict[str, Any]] = {"analysis": {"state": "idle"}, "styles": {"state": "idle"}}


# --- State -------------------------------------------------------------------

def new_session() -> dict[str, Any]:
    return {"id": uuid.uuid4().hex[:12], "started_at": utc_now(), "intake_answers": {}, "swipes": [],
            "reference_override": None, "renders": {}}


def load_session() -> dict[str, Any]:
    session = read_json(config.SESSION_PATH)
    if not session or "id" not in session:   # missing or from an older version of the app
        session = new_session()
        write_json(config.SESSION_PATH, session)
    return session


def update_session(change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
    with session_lock:
        session = load_session()
        change(session)
        write_json(config.SESSION_PATH, session)
        return session


def photos_dir(session: dict[str, Any]) -> Path:
    return config.UPLOADS_DIR / session["id"]


def session_photos(session: dict[str, Any]) -> list[Path]:
    return list_photos(photos_dir(session))


def archive(path: Path) -> None:
    """Move a paid output aside instead of deleting it."""
    if path.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        dest = config.OUT_DIR / "archive" / f"{path.stem}_{stamp}{path.suffix}"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(path, dest)


def session_cost(session: dict[str, Any]) -> float:
    entries = read_json(config.RUN_LOG_PATH) or []
    return round(sum(e.get("cost_usd", 0) for e in entries
                     if e["at"] >= session["started_at"] and e["step"] != "catalog_tag"), 4)


def reference_file(session: dict[str, Any], result: dict[str, Any] | None) -> str | None:
    photos = [p.name for p in session_photos(session)]
    if session.get("reference_override") in photos:
        return session["reference_override"]
    if result and result["reference_photo"]["file"] in photos:
        return result["reference_photo"]["file"]
    return photos[0] if len(photos) == 1 else None


def require_key(name: str) -> None:
    if not os.getenv(name):
        raise HTTPException(400, f"{name} is not set; add it to .env and restart")


def card(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"], "name": item["name"], "description": item["description"],
        "image": f"/catalog/{item['image']}", "category": item["category"],
        "tags": [label(s) for s in item["styles"]] + [label(item["color_family"]), label(item["pattern"])],
    }


def invalidate_photo_outputs() -> None:
    """Photos changed: the analysis and looks no longer describe them."""
    if any(j["state"] == "running" for j in jobs.values()):
        raise HTTPException(409, "Wait for the running call to finish before changing photos")
    archive(config.ANALYSIS_PATH)
    archive(config.STYLES_PATH)
    jobs["analysis"] = {"state": "idle"}
    jobs["styles"] = {"state": "idle"}


# --- Pages -------------------------------------------------------------------

@app.get("/")
def index() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "index.html")


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(config.STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/api/state")
def state() -> dict[str, Any]:
    session = load_session()
    result = read_json(config.ANALYSIS_PATH)
    catalog = recommender.load_catalog()
    return {
        "photos": [p.name for p in session_photos(session)],
        "max_photos": config.MAX_UPLOAD_PHOTOS,
        "catalog_size": len(catalog),
        "intake_questions": intake.questions_with_images(catalog),
        "session": {k: v for k, v in session.items() if k != "swipes"} | {"swipe_count": len(session["swipes"])},
        "swipe_target": config.SWIPE_TARGET,
        "swipe_min": config.SWIPE_MIN,
        "analysis": result,
        "styles": read_json(config.STYLES_PATH),
        "jobs": jobs,
        "reference_file": reference_file(session, result),
        "render_models": config.RENDER_MODELS,
        "default_render_models": config.DEFAULT_RENDER_MODELS,
        "session_cost_usd": session_cost(session),
    }


# --- Photos ------------------------------------------------------------------------

@app.get("/api/photos/{name}")
def get_photo(name: str) -> FileResponse:
    path = photos_dir(load_session()) / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "photo not found")
    return FileResponse(path)


@app.post("/api/photos")
async def upload_photos(files: list[UploadFile]) -> dict[str, Any]:
    session = load_session()
    folder = photos_dir(session)
    folder.mkdir(parents=True, exist_ok=True)
    existing = session_photos(session)
    if len(existing) + len(files) > config.MAX_UPLOAD_PHOTOS:
        raise HTTPException(400, f"Up to {config.MAX_UPLOAD_PHOTOS} photos")
    if read_json(config.ANALYSIS_PATH):
        invalidate_photo_outputs()
    saved = []
    for f in files:
        data = await f.read()
        try:
            with Image.open(io.BytesIO(data)) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                img.thumbnail((config.MAX_IMAGE_SIDE, config.MAX_IMAGE_SIDE))
                name = f"photo_{uuid.uuid4().hex[:8]}.jpg"
                img.save(folder / name, format="JPEG", quality=92)
                saved.append(name)
        except Exception:
            raise HTTPException(400, f"{f.filename}: not an image we can read (try JPEG or PNG)")
    return {"saved": saved}


@app.delete("/api/photos/{name}")
def delete_photo(name: str) -> dict[str, Any]:
    session = load_session()
    path = photos_dir(session) / Path(name).name
    if not path.is_file():
        raise HTTPException(404, "photo not found")
    if read_json(config.ANALYSIS_PATH):
        invalidate_photo_outputs()
    path.unlink()   # the user's own upload from this session, removed at their request
    if session.get("reference_override") == path.name:
        update_session(lambda s: s.update(reference_override=None))
    return {"deleted": path.name}


# --- Intake + swipes (free) --------------------------------------------------------

class IntakeRequest(BaseModel):
    answers: dict[str, list[str]]


class SwipeRequest(BaseModel):
    item_id: int
    verdict: Literal["love", "like", "dislike", "skip"]


@app.post("/api/intake")
def save_intake(req: IntakeRequest) -> dict[str, Any]:
    update_session(lambda s: s.update(intake_answers=req.answers))
    return {"saved": True}


@app.get("/api/swipe/next")
def next_swipe() -> dict[str, Any]:
    session = load_session()
    if not recommender.load_catalog():
        raise HTTPException(400, "No catalog yet: run build_catalog.py")
    item = recommender.next_card(session["intake_answers"], session["swipes"], seed=session["id"])
    return {"card": card(item) if item else None, "count": len(session["swipes"])}


@app.post("/api/swipe")
def swipe(req: SwipeRequest) -> dict[str, Any]:
    if req.item_id not in {it["id"] for it in recommender.load_catalog()}:
        raise HTTPException(400, f"unknown item {req.item_id}")

    def add(s: dict[str, Any]) -> None:
        if all(x["item_id"] != req.item_id for x in s["swipes"]):
            s["swipes"].append({"item_id": req.item_id, "verdict": req.verdict, "at": utc_now()})
    session = update_session(add)
    return {"count": len(session["swipes"])}


@app.post("/api/swipe/undo")
def undo_swipe() -> dict[str, Any]:
    session = update_session(lambda s: s["swipes"].pop() if s["swipes"] else None)
    return {"count": len(session["swipes"])}


@app.get("/api/taste")
def taste() -> dict[str, Any]:
    session = load_session()
    profile = recommender.taste_profile(session["intake_answers"], session["swipes"])
    for key in ("loved", "liked", "disliked"):
        profile[key] = [card(it) for it in profile[key]]
    return profile


# --- Paid calls -------------------------------------------------------------------

class ForceRequest(BaseModel):
    force: bool = False


class ReferenceRequest(BaseModel):
    file: str | None


class RenderRequest(BaseModel):
    look: int
    model: str


def run_job(name: str, work: Callable[[], float]) -> dict[str, Any]:
    if jobs[name]["state"] == "running":
        raise HTTPException(409, f"{name} is already running")
    jobs[name] = {"state": "running", "started_at": utc_now()}
    try:
        cost = work()
    except HTTPException as exc:
        jobs[name] = {"state": "error", "error": exc.detail}
        raise
    except RuntimeError as exc:
        jobs[name] = {"state": "error", "error": str(exc)}
        raise HTTPException(502, str(exc))
    jobs[name] = {"state": "done", "cost_usd": round(cost, 4)}
    return jobs[name]


@app.post("/api/analyze")
def analyze(req: ForceRequest) -> dict[str, Any]:
    """Call 1: stylist read of the photos. Can run while the user swipes."""
    if config.ANALYSIS_PATH.exists() and not req.force:
        raise HTTPException(409, "Photos were already analyzed. Regenerate explicitly to pay for a new call.")
    session = load_session()
    if not session_photos(session):
        raise HTTPException(400, "Upload at least one photo first")
    require_key("OPENAI_API_KEY")

    def work() -> float:
        current = load_session()
        result, cost = analysis.run(current["intake_answers"], session_photos(current))
        archive(config.ANALYSIS_PATH)
        write_json(config.ANALYSIS_PATH, result)
        update_session(lambda s: s.update(reference_override=None))
        return cost
    return run_job("analysis", work)


@app.post("/api/styles")
def generate_styles(req: ForceRequest) -> dict[str, Any]:
    """Call 2: three looks from photos + intake + taste profile + analysis."""
    result = read_json(config.ANALYSIS_PATH)
    if result is None:
        raise HTTPException(400, "The photo analysis hasn't finished yet")
    if config.STYLES_PATH.exists() and not req.force:
        raise HTTPException(409, "Looks already exist. Regenerate explicitly to pay for a new call.")
    require_key("OPENAI_API_KEY")

    def work() -> float:
        session = load_session()
        looks, cost = styles.run(result, session, session_photos(session))
        archive(config.STYLES_PATH)
        write_json(config.STYLES_PATH, looks)
        update_session(lambda s: s.update(renders={}))
        return cost
    return run_job("styles", work)


@app.post("/api/reference")
def set_reference(req: ReferenceRequest) -> dict[str, Any]:
    session = load_session()
    if req.file is not None and req.file not in {p.name for p in session_photos(session)}:
        raise HTTPException(400, f"unknown photo {req.file!r}")
    session = update_session(lambda s: s.update(reference_override=req.file))
    return {"reference_file": reference_file(session, read_json(config.ANALYSIS_PATH))}


@app.post("/api/render")
def render_look(req: RenderRequest) -> dict[str, Any]:
    """Call 3 for one look with one model. Failures come back as status=error, not HTTP errors."""
    session = load_session()
    looks = (read_json(config.STYLES_PATH) or {}).get("looks") or []
    if not 1 <= req.look <= len(looks):
        raise HTTPException(400, f"look must be 1..{len(looks)}")
    if req.model not in config.RENDER_MODELS:
        raise HTTPException(400, f"model must be one of {config.RENDER_MODELS}")
    ref = reference_file(session, read_json(config.ANALYSIS_PATH))
    if ref is None:
        raise HTTPException(400, "No reference photo selected")
    require_key("GEMINI_API_KEY")
    result, cost = render.run(req.look, looks[req.look - 1], photos_dir(session) / ref, req.model)
    result |= {"at": utc_now(), "reference": ref, "cost_usd": round(cost, 4)}
    update_session(lambda s: s["renders"].setdefault(str(req.look), {}).__setitem__(req.model, result))
    return result


@app.post("/api/reset")
def reset() -> dict[str, Any]:
    """Start over. Analysis, looks and session are archived and uploads kept on disk; run_log.json is kept."""
    if any(j["state"] == "running" for j in jobs.values()):
        raise HTTPException(409, "Wait for the running call to finish")
    with session_lock:
        for path in (config.ANALYSIS_PATH, config.STYLES_PATH, config.SESSION_PATH, config.LOOKS_DIR):
            archive(path)
        config.LOOKS_DIR.mkdir(parents=True, exist_ok=True)
        write_json(config.SESSION_PATH, new_session())
    for name in jobs:
        jobs[name] = {"state": "idle"}
    return {"reset": True}


# --- Prompt previews (no API calls) ---------------------------------------------

@app.get("/api/preview/analysis")
def preview_analysis() -> dict[str, str]:
    session = load_session()
    return {"prompt": analysis.preview(session["intake_answers"], session_photos(session))}


@app.get("/api/preview/styles")
def preview_styles() -> dict[str, str]:
    result = read_json(config.ANALYSIS_PATH)
    if result is None:
        raise HTTPException(400, "The photo analysis hasn't finished yet")
    session = load_session()
    return {"prompt": styles.preview(result, session, session_photos(session))}


@app.get("/api/preview/render")
def preview_render(look: int, model: str) -> dict[str, str]:
    session = load_session()
    looks = (read_json(config.STYLES_PATH) or {}).get("looks") or []
    if not 1 <= look <= len(looks):
        raise HTTPException(400, f"look must be 1..{len(looks)}")
    ref = reference_file(session, read_json(config.ANALYSIS_PATH)) or "<no reference selected>"
    return {"prompt": render.preview(looks[look - 1], ref, model)}


def lan_ip() -> str | None:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))   # no packets sent; picks the outbound interface
            return s.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8000"))
    print(f"\n  On this computer:  http://127.0.0.1:{port}")
    if host == "0.0.0.0" and (ip := lan_ip()):
        print(f"  On your phone:     http://{ip}:{port}   (same Wi-Fi)\n")
    uvicorn.run(app, host=host, port=port)
