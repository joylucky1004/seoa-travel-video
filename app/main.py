"""FastAPI entry point — iPad-friendly web UI + JSON API."""
from __future__ import annotations

import base64
import json
import secrets
from datetime import datetime, timezone

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.config import PROJECT_ROOT, get_settings
from app.models import ReelRequest
from app.services import character, editor, pipeline
from app.services.higgsfield import GenerationRequest, LiveHiggsfieldClient
from app.services.higgsfield.models import PROFILES, resolve_resolution


app = FastAPI(title="SEOA Travel AI Video Automation", version="0.1.0")
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "app" / "static"), name="static")
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    """Optional HTTP Basic auth (user: seoa) when APP_PASSWORD is set."""
    pw = get_settings().app_password.get_secret_value() if get_settings().app_password else ""
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
    return templates.TemplateResponse(request, "index.html", {"mode": "LIVE" if get_settings().is_live else "MOCK"})


@app.get("/healthz")
def healthz():
    return {"ok": True}


def _safe_generation_settings() -> dict:
    try:
        return pipeline.generation_settings()
    except ValueError as exc:  # unknown model configured
        return {"model": None, "warning": str(exc)}


def _password_set() -> bool:
    pw = get_settings().app_password
    return bool(pw and pw.get_secret_value())


@app.get("/api/status")
def status():
    # Only secret-free facts. Never return key values.
    return {
        "mode": "live" if get_settings().is_live else "mock",
        "higgsfield_key_configured": get_settings().credentials_status == "ok",
        "higgsfield_credentials": get_settings().credentials_status,  # ok | incomplete | missing
        "paid_calls_allowed": get_settings().allow_paid_api_calls,
        "password_protected": bool(get_settings().app_password and get_settings().app_password.get_secret_value()),
        "generation": _safe_generation_settings(),
        "max_clips_per_job": get_settings().max_clips_per_job,
        "max_usd_per_job": get_settings().max_usd_per_job,
        "ffmpeg_available": editor.ffmpeg_available(),
        "cta_text": get_settings().cta_text,
        "resolution": f"{get_settings().video_width}x{get_settings().video_height}",
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


# --- Models / cost ---------------------------------------------------------
class ModelChoice(BaseModel):
    model: str


@app.get("/api/models")
def list_models():
    """Documented capabilities of the cost-saving model allowlist (no API calls)."""
    return {"selected": pipeline.selected_model(),
            "models": [p.info() for p in PROFILES.values()],
            "last_comparison": _load_comparison()}


def _comparison_file():
    return get_settings().data_path / "model_compare.json"


def _load_comparison():
    try:
        return json.loads(_comparison_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


@app.post("/api/models/compare")
def compare_models():
    """Free cost comparison via POST /estimate/{model}. Generates nothing, spends no credits."""
    s = get_settings()
    if not _password_set():
        raise HTTPException(403, "비용 비교는 Higgsfield 키를 사용하므로 APP_PASSWORD 설정 후 사용할 수 있습니다.")
    if s.credentials_status != "ok":
        raise HTTPException(400, "Higgsfield API 키가 없거나 형식이 맞지 않습니다 (HF_API_KEY=KEY_ID:KEY_SECRET).")
    refs = character.list_references()
    if not refs:
        raise HTTPException(400, "SEOA 레퍼런스 이미지를 1장 이상 등록해 주세요.")
    client = LiveHiggsfieldClient(s, estimate_only=True)
    try:
        ref_urls = client.prepare_references(refs[:1])
    except Exception as exc:
        raise HTTPException(502, f"레퍼런스 업로드 실패: {exc}")
    rows = []
    for prof in PROFILES.values():
        resolution, _ = resolve_resolution(prof, "")
        req = GenerationRequest(model=prof.id, prompt="SEOA, a Korean woman, smiles at a cafe window. 9:16 travel reel.",
                                negative_prompt="", reference_urls=ref_urls,
                                duration=prof.min_duration, resolution=resolution)
        row = {"model": prof.id, "label": prof.label, "duration": prof.min_duration,
               "resolution": resolution, "usd": None, "usd_per_second": None, "error": ""}
        try:
            row["usd"] = client.estimate_usd(req)
            if row["usd"] is not None:
                row["usd_per_second"] = round(row["usd"] / prof.min_duration, 4)
        except Exception as exc:
            row["error"] = str(exc)[:200]
        rows.append(row)
    rows.sort(key=lambda r: (r["usd"] is None, r["usd"] if r["usd"] is not None else 0))
    result = {"checked_at": datetime.now(timezone.utc).isoformat(), "rows": rows,
              "cheapest": next((r["model"] for r in rows if r["usd"] is not None), None)}
    _comparison_file().write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    return result


@app.post("/api/models/select")
def choose_model(body: ModelChoice):
    """Manual model choice only — the app never switches models on its own."""
    try:
        return {"selected": pipeline.select_model(body.model), "settings": pipeline.generation_settings()}
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/preview")
def preview(req: ReelRequest):
    """Free: shows the exact prompts/request bodies and the scene timeline. No API calls."""
    try:
        return pipeline.preview(req)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# --- Jobs ------------------------------------------------------------------
def _require_password_for_live() -> None:
    if get_settings().is_live and not _password_set():
        raise HTTPException(403, "live 모드에서는 크레딧 보호를 위해 APP_PASSWORD 환경변수를 먼저 설정해야 합니다.")


@app.post("/api/jobs")
def create_job(req: ReelRequest, background: BackgroundTasks):
    _require_password_for_live()
    try:
        job = pipeline.create_job(req)
    except pipeline.JobStateError as exc:
        raise HTTPException(400, str(exc))
    background.add_task(pipeline.next_step(job), job.id)
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


@app.post("/api/jobs/{job_id}/approve")
def approve_job(job_id: str, background: BackgroundTasks):
    """The ONLY path that starts paid Higgsfield generation."""
    _require_password_for_live()
    try:
        job = pipeline.approve(job_id)
    except pipeline.JobStateError as exc:
        raise HTTPException(409, str(exc))
    background.add_task(pipeline.run_generation, job.id)
    return job


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    try:
        return pipeline.cancel(job_id)
    except pipeline.JobStateError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/jobs/{job_id}/retry")
def retry_job(job_id: str, background: BackgroundTasks):
    """Re-runs only failed scenes. In live mode this goes back to cost estimate + approval."""
    _require_password_for_live()
    try:
        job = pipeline.prepare_retry(job_id)
    except pipeline.JobStateError as exc:
        raise HTTPException(409, str(exc))
    background.add_task(pipeline.next_step(job), job.id)
    return job


@app.get("/api/jobs/{job_id}/video")
def get_video(job_id: str):
    job = pipeline.load_job(job_id)
    if job is None or not job.output_path:
        raise HTTPException(404)
    return FileResponse(job.output_path, media_type="video/mp4", filename=f"seoa-reel-{job_id}.mp4")


@app.get("/api/jobs/{job_id}/clips/{index}")
def get_clip(job_id: str, index: int):
    job = pipeline.load_job(job_id)
    if job is None or not (0 <= index < len(job.scenes)) or not job.scenes[index].clip_ready:
        raise HTTPException(404)
    return FileResponse(pipeline.clip_path(job_id, index), media_type="video/mp4",
                        filename=f"seoa-{job_id}-scene{index + 1}.mp4")
