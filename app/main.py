"""FastAPI entry point — iPad-friendly web UI + JSON API."""
from __future__ import annotations

import base64
import secrets

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import PROJECT_ROOT, get_settings
from app.models import ReelRequest
from app.services import character, editor, pipeline

settings = get_settings()
app = FastAPI(title="SEOA Travel AI Video Automation", version="0.1.0")
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional HTTP Basic auth (user: seoa) when APP_PASSWORD is set."""
    pw = settings.app_password.get_secret_value() if settings.app_password else ""
    if pw and request.url.path != "/healthz":
        header = request.headers.get("authorization", "")
        ok = False
        if header.lower().startswith("basic "):
            try:
                user, _, given = base64.b64decode(header[6:]).decode().partition(":")
                ok = secrets.compare_digest(user, "seoa") and secrets.compare_digest(given, pw)
            except Exception:
                ok = False
        if not ok:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="SEOA"'})
    return await call_next(request)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", {"mode": "LIVE" if settings.is_live else "MOCK"})


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/status")
def status():
    return {
        "mode": "live" if settings.is_live else "mock",
        "higgsfield_key_configured": settings.higgsfield_api_key is not None,
        "paid_calls_allowed": settings.allow_paid_api_calls,
        "ffmpeg_available": editor.ffmpeg_available(),
        "cta_text": settings.cta_text,
        "resolution": f"{settings.video_width}x{settings.video_height}",
    }


# --- Character -------------------------------------------------------------
class CharacterUpdate(BaseModel):
    consistency_rules: list[str]
    default_outfit: str | None = None


@app.get("/api/character")
def get_character():
    profile = character.load_profile()
    profile["references"] = [p.name for p in character.list_references()]
    return profile


@app.put("/api/character")
def update_character(body: CharacterUpdate):
    return character.save_overrides(body.consistency_rules, body.default_outfit)


@app.post("/api/character/references")
async def upload_reference(file: UploadFile = File(...)):
    content = await file.read()
    try:
        path = character.save_reference(file.filename or "ref.jpg", content)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"name": path.name}


@app.get("/api/character/references/{name}")
def get_reference(name: str):
    match = [p for p in character.list_references() if p.name == name]
    if not match:
        raise HTTPException(404)
    return FileResponse(match[0])


@app.delete("/api/character/references/{name}")
def remove_reference(name: str):
    if not character.delete_reference(name):
        raise HTTPException(404)
    return {"deleted": name}


# --- Jobs ------------------------------------------------------------------
@app.post("/api/jobs")
def create_job(req: ReelRequest, background: BackgroundTasks):
    try:
        job = pipeline.create_job(req)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    background.add_task(pipeline.run_job, job.id)
    return job


@app.get("/api/jobs")
def list_jobs():
    return pipeline.list_jobs()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = pipeline.load_job(job_id)
    if job is None:
        raise HTTPException(404)
    return job


@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str):
    job = pipeline.load_job(job_id)
    if job is None or not job.output_path:
        raise HTTPException(404)
    return FileResponse(job.output_path, media_type="video/mp4", filename=f"seoa-reel-{job_id}.mp4")
