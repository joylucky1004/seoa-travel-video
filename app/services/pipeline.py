"""Job orchestration: prompts → Higgsfield clips (mock or live) → FFmpeg edit.

Live flow (spends credits only after explicit approval):
    create → estimating (upload refs + free cost estimate) → awaiting_approval
           → [user approves] → generating → editing → done
Mock flow (free):
    create → generating → editing → done
"""
from __future__ import annotations

import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.models import ClipResult, Job, JobStatus, ReelRequest, SceneState

from . import character, editor
from .higgsfield import (GenerationError, GenerationRequest, HiggsfieldAPIError, VideoGenerator,
                         get_generator)
from .prompt_builder import build_negative_prompt, build_scene_prompt

log = logging.getLogger(__name__)
_lock = threading.Lock()
# Replaced in tests to inject a fake generator.
generator_factory = get_generator


class JobStateError(ValueError):
    pass


# --- persistence ----------------------------------------------------------
def _job_dir(job_id: str) -> Path:
    return get_settings().jobs_path / job_id


def save_job(job: Job) -> None:
    job.updated_at = datetime.now(timezone.utc)
    path = _job_dir(job.id) / "job.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        path.write_text(job.model_dump_json(indent=2), encoding="utf-8")


def load_job(job_id: str) -> Job | None:
    if not job_id.isalnum():
        return None
    path = _job_dir(job_id) / "job.json"
    return Job.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def list_jobs(limit: int = 20) -> list[Job]:
    jobs = [load_job(p.name) for p in get_settings().jobs_path.iterdir() if p.is_dir()]
    return sorted((j for j in jobs if j), key=lambda j: j.created_at, reverse=True)[:limit]


def clip_path(job_id: str, index: int) -> Path:
    return _job_dir(job_id) / f"clip_{index:02d}.mp4"


# Reference URLs are kept server-side only (never returned by the API).
def _save_ref_urls(job_id: str, urls: list[str]) -> None:
    (_job_dir(job_id) / "refs.json").write_text(json.dumps(urls), encoding="utf-8")


def _load_ref_urls(job_id: str) -> list[str] | None:
    p = _job_dir(job_id) / "refs.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


# --- lifecycle ------------------------------------------------------------
def create_job(req: ReelRequest) -> Job:
    s = get_settings()
    if s.is_live:
        if len(req.scenes) > s.max_clips_per_job:
            raise JobStateError(f"live 모드에서는 작업당 최대 {s.max_clips_per_job}개 장면만 허용됩니다.")
        if s.credentials_status != "ok":
            raise JobStateError("Higgsfield API 키가 없거나 형식이 맞지 않습니다 (HF_API_KEY=KEY_ID:KEY_SECRET).")
        if not character.list_references():
            raise JobStateError("SEOA 레퍼런스 이미지를 1장 이상 등록해 주세요.")
    job = Job(id=uuid.uuid4().hex[:12], request=req, mode="live" if s.is_live else "mock",
              scenes=[SceneState(index=i) for i in range(len(req.scenes))])
    save_job(job)
    return job


def next_step(job: Job):
    """The background function to run after create/retry."""
    return run_estimate if job.mode == "live" else run_generation


def approve(job_id: str) -> Job:
    job = load_job(job_id)
    if job is None:
        raise JobStateError("작업을 찾을 수 없습니다.")
    if job.status != JobStatus.awaiting_approval:
        raise JobStateError("승인 대기 중인 작업이 아닙니다.")
    job.status, job.message = JobStatus.generating, "승인됨 — 생성 요청 중"
    save_job(job)
    return job


def cancel(job_id: str) -> Job:
    job = load_job(job_id)
    if job is None:
        raise JobStateError("작업을 찾을 수 없습니다.")
    if job.status != JobStatus.awaiting_approval:
        raise JobStateError("승인 전 작업만 취소할 수 있습니다.")
    job.status, job.message = JobStatus.canceled, "취소됨 (과금 없음)"
    save_job(job)
    return job


def prepare_retry(job_id: str) -> Job:
    """Reset failed scenes; completed clips are kept and not regenerated."""
    job = load_job(job_id)
    if job is None:
        raise JobStateError("작업을 찾을 수 없습니다.")
    if job.status != JobStatus.failed:
        raise JobStateError("실패한 작업만 다시 시도할 수 있습니다.")
    for sc in job.scenes:
        if not sc.clip_ready:
            job.scenes[sc.index] = SceneState(index=sc.index)
    job.status, job.message, job.output_path = JobStatus.queued, "다시 시도 준비 중", None
    save_job(job)
    return job


def _pending_scenes(job: Job) -> list[SceneState]:
    return [sc for sc in job.scenes if not sc.clip_ready]


def _gen_request(job: Job, profile: dict, index: int, ref_urls: list[str]) -> GenerationRequest:
    scene = job.request.scenes[index]
    return GenerationRequest(prompt=build_scene_prompt(profile, job.request, scene),
                             negative_prompt=build_negative_prompt(profile), reference_urls=ref_urls,
                             duration_seconds=scene.duration_seconds, aspect_ratio="9:16")


def _fail(job: Job, message: str) -> None:
    job.status, job.message = JobStatus.failed, message[:500]
    save_job(job)


def run_estimate(job_id: str, generator: VideoGenerator | None = None) -> None:
    """Live only: upload references and estimate cost. Nothing is charged here."""
    job = load_job(job_id)
    if job is None:
        return
    try:
        gen = generator or generator_factory(get_settings())
        job.status, job.message = JobStatus.estimating, "레퍼런스 업로드 · 비용 확인 중"
        save_job(job)
        refs = gen.prepare_references(character.list_references())
        _save_ref_urls(job.id, refs)
        profile = character.load_profile()
        total, known = 0.0, True
        for sc in _pending_scenes(job):
            sc.estimate_usd = gen.estimate_usd(_gen_request(job, profile, sc.index, refs))
            if sc.estimate_usd is None:
                known = False
            else:
                total += sc.estimate_usd
        job.estimate_total_usd = round(total, 4) if known else None
        n = len(_pending_scenes(job))
        cost = f"예상 비용 ${total:.2f}" if known else "예상 비용 확인 불가"
        job.status, job.message = JobStatus.awaiting_approval, f"{n}개 장면 · {cost} — 승인 대기"
        save_job(job)
    except Exception as exc:
        log.exception("estimate failed for job %s", job_id)
        _fail(job, f"비용 확인 실패: {exc}")


def run_generation(job_id: str, generator: VideoGenerator | None = None) -> None:
    job = load_job(job_id)
    if job is None:
        return
    s = get_settings()
    try:
        gen = generator or generator_factory(s)
        profile = character.load_profile()
        ref_urls = _load_ref_urls(job.id) if not gen.mock else None
        if ref_urls is None:
            ref_urls = gen.prepare_references(character.list_references())
            _save_ref_urls(job.id, ref_urls)

        job.status = JobStatus.generating
        pending = _pending_scenes(job)
        total = len(job.scenes)

        def update_progress():
            done = sum(1 for sc in job.scenes if sc.clip_ready)
            job.progress = 0.85 * done / total
            job.message = f"장면 생성 {done}/{total} 완료 ({gen.name})"
            save_job(job)

        # 1) submit every pending scene (they run concurrently on Higgsfield's side)
        for sc in pending:
            sc.idempotency_key = sc.idempotency_key or uuid.uuid4().hex
            try:
                sc.request_id = gen.submit(_gen_request(job, profile, sc.index, ref_urls), sc.idempotency_key)
                sc.status, sc.error = "submitted", ""
            except (HiggsfieldAPIError, ValueError) as exc:
                sc.status, sc.error = "failed", str(exc)[:300]
            save_job(job)

        # 2) wait for each one and download the clip
        for sc in pending:
            if sc.status != "submitted":
                continue

            def on_status(status: str, request_id: str | None, sc=sc):
                sc.status = status
                save_job(job)

            try:
                gen.wait(sc.request_id, clip_path(job.id, sc.index), on_status)
                sc.status, sc.clip_ready, sc.error = "completed", True, ""
            except GenerationError as exc:
                sc.status, sc.error = exc.status, str(exc)[:300]
            except HiggsfieldAPIError as exc:
                sc.status, sc.error = "failed", str(exc)[:300]
            update_progress()

        job.clips = [ClipResult(scene_index=sc.index, prompt=build_scene_prompt(
                        profile, job.request, job.request.scenes[sc.index]),
                        path=str(clip_path(job.id, sc.index)), provider=gen.name, mock=gen.mock)
                     for sc in job.scenes if sc.clip_ready]

        failed = [sc for sc in job.scenes if not sc.clip_ready]
        if failed:
            nums = ", ".join(f"#{sc.index + 1}" for sc in failed)
            _fail(job, f"장면 {nums} 생성 실패 — 완료된 장면은 보관됩니다. '실패 장면 다시 시도'를 누르세요.")
            return

        # 3) edit: 9:16 normalize + Korean subtitles + CTA
        job.status, job.progress, job.message = JobStatus.editing, 0.9, "FFmpeg 편집 중 (자막 · CTA)"
        save_job(job)
        output = _job_dir(job.id) / "reel_final.mp4"
        clips_for_edit = [(clip_path(job.id, i), sc.duration_seconds, sc.subtitle_ko)
                          for i, sc in enumerate(job.request.scenes)]
        editor.render_reel(clips_for_edit, _job_dir(job.id) / "work", output, add_cta=job.request.add_cta)
        job.output_path = str(output)
        job.status, job.progress, job.message = JobStatus.done, 1.0, "완료"
        save_job(job)
    except Exception as exc:  # surface any failure to the UI
        log.exception("job %s failed", job.id)
        _fail(job, f"실패: {exc}")
