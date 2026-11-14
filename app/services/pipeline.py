"""Job orchestration: prompts → Higgsfield clips (mock or live) → FFmpeg edit.

Credit-saving rules enforced here:
  * Live flow:  create → estimating (free) → awaiting_approval → [user approves] → generating
               → editing → done. Nothing is generated without approval.
  * The model, resolution and duration are fixed when the job is created; approval binds to
    exactly those settings, and there is no fallback to another model.
  * Identical scenes (same model, settings, prompt and reference images) reuse the cached clip.
  * Failed scenes are never retried automatically; the user must retry and approve again.
  * Live jobs generate at most MAX_CLIPS_PER_JOB scenes (default 1, for testing).
  * Subtitles, joining and the CTA are done locally with FFmpeg — no extra API calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import get_settings
from app.models import ClipResult, Job, JobStatus, ReelRequest, SceneState

from . import character, editor
from .higgsfield import (GenerationError, GenerationRequest, HiggsfieldAPIError,
                         MockHiggsfieldClient, VideoGenerator, get_generator)
from .higgsfield.models import (build_arguments, get_profile, resolve_duration,
                                resolve_resolution)
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


# --- model selection ------------------------------------------------------
def _choice_file() -> Path:
    return get_settings().data_path / "model_choice.json"


def selected_model() -> str:
    """Model picked in the UI after the free cost comparison, else HIGGSFIELD_MODEL."""
    try:
        return json.loads(_choice_file().read_text(encoding="utf-8"))["model"]
    except (OSError, ValueError, KeyError):
        return get_settings().higgsfield_model


def select_model(model_id: str) -> str:
    get_profile(model_id)  # validates against the cost-saving allowlist
    _choice_file().write_text(json.dumps({"model": model_id}), encoding="utf-8")
    return model_id


def generation_settings() -> dict:
    s = get_settings()
    profile = get_profile(selected_model())
    resolution, warning = resolve_resolution(profile, s.higgsfield_resolution)
    return {"model": profile.id, "label": profile.label, "resolution": resolution,
            "duration_policy": s.higgsfield_duration_policy, "min_duration": profile.min_duration,
            "max_reference_images": profile.max_reference_images, "warning": warning}


# --- clip cache (never pay twice for the same scene) ------------------------
def _cache_dir() -> Path:
    p = get_settings().data_path / "clip_cache"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _reference_fingerprint() -> list[str]:
    return sorted(hashlib.sha256(p.read_bytes()).hexdigest() for p in character.list_references())


def scene_cache_key(model: str, resolution: str | None, duration: int, prompt: str,
                    negative: str, ref_fingerprint: list[str]) -> str:
    payload = json.dumps([model, resolution, duration, prompt, negative, ref_fingerprint],
                         ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _cached_clip(key: str | None) -> Path | None:
    if not key:
        return None
    p = _cache_dir() / f"{key}.mp4"
    return p if p.exists() and p.stat().st_size > 0 else None


def _store_in_cache(key: str | None, clip: Path) -> None:
    if key and clip.exists():
        shutil.copyfile(clip, _cache_dir() / f"{key}.mp4")


# --- planning (pure, no API calls) ----------------------------------------
def _scene_texts(profile_dict: dict, req: ReelRequest, index: int) -> tuple[str, str]:
    return build_scene_prompt(profile_dict, req, req.scenes[index]), build_negative_prompt(profile_dict)


def preview(req: ReelRequest) -> dict:
    """Free validation of prompts and scene layout. Makes no network calls."""
    s = get_settings()
    gs = generation_settings()
    profile = get_profile(gs["model"])
    char = character.load_profile()
    refs = character.list_references()
    fp = _reference_fingerprint()
    placeholder = [f"<SEOA reference {i + 1}>" for i in range(max(1, min(len(refs), profile.max_reference_images)))]
    scenes = []
    selected = _selected_indices(req)
    for i in range(len(req.scenes)):
        prompt, negative = _scene_texts(char, req, i)
        duration = resolve_duration(profile, req.scenes[i].duration_seconds, gs["duration_policy"])
        key = scene_cache_key(gs["model"], gs["resolution"], duration, prompt, negative, fp)
        scenes.append({
            "index": i, "selected": i in selected, "subtitle_ko": req.scenes[i].subtitle_ko,
            "timeline_seconds": req.scenes[i].duration_seconds, "generated_seconds": duration,
            "reusable": _cached_clip(key) is not None,
            "request_body": build_arguments(profile, prompt=prompt, negative_prompt=negative,
                                            reference_urls=placeholder, duration=duration,
                                            resolution=gs["resolution"]),
        })
    return {"settings": gs, "reference_images": len(refs), "max_clips_per_job": s.max_clips_per_job,
            "cta_text": s.cta_text if req.add_cta else None, "scenes": scenes,
            "warnings": [w for w in [gs["warning"],
                                     "" if refs else "레퍼런스 이미지가 없습니다 (실제 생성 불가)."] if w]}


def _selected_indices(req: ReelRequest) -> list[int]:
    if req.scene_indices:
        return sorted({i for i in req.scene_indices if 0 <= i < len(req.scenes)})
    return list(range(len(req.scenes)))


# --- lifecycle ------------------------------------------------------------
def create_job(req: ReelRequest) -> Job:
    s = get_settings()
    selected = _selected_indices(req)
    if not selected:
        raise JobStateError("생성할 장면을 1개 이상 선택하세요.")
    req = req.model_copy(update={"scenes": [req.scenes[i] for i in selected], "scene_indices": None})
    live = s.is_live and not req.dry_run
    gs = generation_settings()
    if live:
        if len(req.scenes) > s.max_clips_per_job:
            raise JobStateError(
                f"실제 생성은 작업당 최대 {s.max_clips_per_job}개 장면만 허용됩니다 (크레딧 절약 테스트 모드). "
                "장면 1개를 선택하거나 MOCK 미리보기를 사용하세요.")
        if s.credentials_status != "ok":
            raise JobStateError("Higgsfield API 키가 없거나 형식이 맞지 않습니다 (HF_API_KEY=KEY_ID:KEY_SECRET).")
        if not character.list_references():
            raise JobStateError("SEOA 레퍼런스 이미지를 1장 이상 등록해 주세요.")
    job = Job(id=uuid.uuid4().hex[:12], request=req, mode="live" if live else "mock",
              model=gs["model"] if live else "mock", resolution=gs["resolution"],
              scenes=[SceneState(index=i) for i in range(len(req.scenes))])
    save_job(job)
    return job


def next_step(job: Job):
    """The background function to run after create/retry."""
    return run_estimate if job.mode == "live" else run_generation


def approve(job_id: str) -> Job:
    s = get_settings()
    job = load_job(job_id)
    if job is None:
        raise JobStateError("작업을 찾을 수 없습니다.")
    if job.status != JobStatus.awaiting_approval:
        raise JobStateError("승인 대기 중인 작업이 아닙니다.")
    if job.estimate_total_usd is None:
        raise JobStateError("예상 비용을 확인하지 못해 승인할 수 없습니다.")
    if job.estimate_total_usd > s.max_usd_per_job:
        raise JobStateError(f"예상 비용 ${job.estimate_total_usd:.2f}가 작업당 한도 ${s.max_usd_per_job:.2f}를 넘습니다.")
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
    """User-initiated only. Resets failed scenes; completed clips are kept.
    If a submit never got a request id, the same Idempotency-Key is kept so a
    generation that actually started is not created (and charged) twice."""
    job = load_job(job_id)
    if job is None:
        raise JobStateError("작업을 찾을 수 없습니다.")
    if job.status != JobStatus.failed:
        raise JobStateError("실패한 작업만 다시 시도할 수 있습니다.")
    for sc in job.scenes:
        if not sc.clip_ready:
            keep_key = sc.idempotency_key if sc.request_id is None else None
            job.scenes[sc.index] = SceneState(index=sc.index, idempotency_key=keep_key)
    job.status, job.message, job.output_path = JobStatus.queued, "다시 시도 준비 중", None
    job.estimate_total_usd = None
    save_job(job)
    return job


def _pending_scenes(job: Job) -> list[SceneState]:
    return [sc for sc in job.scenes if not sc.clip_ready]


def _plan_scene(job: Job, char: dict, sc: SceneState, ref_urls: list[str], fp: list[str],
                mock: bool) -> GenerationRequest:
    s = get_settings()
    prompt, negative = _scene_texts(char, job.request, sc.index)
    if mock:
        # Mirror the live plan (model's clip length) so MOCK previews what live would produce.
        profile = get_profile(selected_model())
        model, resolution = "mock", job.resolution
        duration = resolve_duration(profile, job.request.scenes[sc.index].duration_seconds,
                                    s.higgsfield_duration_policy)
    else:
        profile = get_profile(job.model)  # fixed at creation; never switched
        model, resolution = profile.id, job.resolution
        duration = resolve_duration(profile, job.request.scenes[sc.index].duration_seconds,
                                    s.higgsfield_duration_policy)
        sc.cache_key = scene_cache_key(model, resolution, duration, prompt, negative, fp)
    sc.generated_seconds = duration
    return GenerationRequest(model=model, prompt=prompt, negative_prompt=negative,
                             reference_urls=ref_urls, duration=duration, resolution=resolution)


def _reuse_if_cached(job: Job, sc: SceneState) -> bool:
    cached = _cached_clip(sc.cache_key)
    if cached is None:
        return False
    shutil.copyfile(cached, clip_path(job.id, sc.index))
    sc.status, sc.clip_ready, sc.reused, sc.estimate_usd, sc.error = "completed", True, True, 0.0, ""
    return True


def _fail(job: Job, message: str) -> None:
    job.status, job.message = JobStatus.failed, message[:500]
    save_job(job)


def run_estimate(job_id: str, generator: VideoGenerator | None = None) -> None:
    """Live only: reuse cached clips, upload references and get the free estimate."""
    job = load_job(job_id)
    if job is None:
        return
    s = get_settings()
    try:
        gen = generator or generator_factory(s)
        job.status, job.message = JobStatus.estimating, "기존 결과 확인 · 비용 확인 중 (무료)"
        save_job(job)
        char, fp = character.load_profile(), _reference_fingerprint()
        to_estimate = []
        for sc in _pending_scenes(job):
            _plan_scene(job, char, sc, [], fp, mock=False)
            if not _reuse_if_cached(job, sc):
                to_estimate.append(sc)
        total = 0.0
        if to_estimate:
            refs = gen.prepare_references(character.list_references())
            _save_ref_urls(job.id, refs)
            for sc in to_estimate:
                sc.estimate_usd = gen.estimate_usd(_plan_scene(job, char, sc, refs, fp, mock=False))
                if sc.estimate_usd is None:
                    total = None
                elif total is not None:
                    total += sc.estimate_usd
        job.estimate_total_usd = round(total, 4) if total is not None else None
        reused = sum(1 for sc in job.scenes if sc.reused)
        if not to_estimate:
            job.message = f"모든 장면을 기존 결과로 재사용합니다 ({reused}개, 비용 $0)."
            save_job(job)
            run_generation(job.id, gen)  # nothing to pay for: go straight to editing
            return
        if job.estimate_total_usd is None:
            _fail(job, "예상 비용을 확인하지 못했습니다. 승인 없이 중단합니다.")
            return
        cost = f"예상 비용 ${job.estimate_total_usd:.2f}"
        if job.estimate_total_usd > s.max_usd_per_job:
            _fail(job, f"{cost}가 작업당 한도 ${s.max_usd_per_job:.2f}(MAX_USD_PER_JOB)를 넘어 중단했습니다.")
            return
        extra = f" · 재사용 {reused}개" if reused else ""
        job.status = JobStatus.awaiting_approval
        job.message = f"생성 {len(to_estimate)}개{extra} · {cost} — 승인 대기"
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
        mock = job.mode != "live"
        gen = MockHiggsfieldClient() if mock else (generator or generator_factory(s))
        char, fp = character.load_profile(), _reference_fingerprint()
        pending = _pending_scenes(job)
        ref_urls: list[str] = []
        if pending:
            ref_urls = (gen.prepare_references(character.list_references()) if mock
                        else _load_ref_urls(job.id))
            if ref_urls is None:
                raise JobStateError("레퍼런스 업로드 정보가 없습니다. 다시 시도해 비용을 확인하세요.")

        job.status = JobStatus.generating
        total = len(job.scenes)

        def update_progress():
            done = sum(1 for sc in job.scenes if sc.clip_ready)
            job.progress = 0.85 * done / total
            job.message = f"장면 생성 {done}/{total} 완료 ({gen.name})"
            save_job(job)

        # 1) submit every pending scene once (no automatic retries)
        for sc in pending:
            req = _plan_scene(job, char, sc, ref_urls, fp, mock=mock)
            if not mock and _reuse_if_cached(job, sc):
                save_job(job)
                continue
            sc.idempotency_key = sc.idempotency_key or uuid.uuid4().hex
            try:
                sc.request_id = gen.submit(req, sc.idempotency_key)
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
                if not mock:
                    _store_in_cache(sc.cache_key, clip_path(job.id, sc.index))
            except GenerationError as exc:
                sc.status, sc.error = exc.status, str(exc)[:300]
            except HiggsfieldAPIError as exc:
                sc.status, sc.error = "failed", str(exc)[:300]
            update_progress()

        job.clips = [ClipResult(scene_index=sc.index, prompt=_scene_texts(char, job.request, sc.index)[0],
                                path=str(clip_path(job.id, sc.index)),
                                provider="cache" if sc.reused else gen.name, mock=mock)
                     for sc in job.scenes if sc.clip_ready]

        failed = [sc for sc in job.scenes if not sc.clip_ready]
        if failed:
            nums = ", ".join(f"#{sc.index + 1}" for sc in failed)
            _fail(job, f"장면 {nums} 생성 실패 — 자동 재시도하지 않습니다. 완료된 장면은 보관되며, "
                       "'실패 장면 다시 시도'를 누르면 비용 확인 후 다시 승인을 받습니다.")
            return

        # 3) server-side edit only: 9:16 normalize + Korean subtitles + CTA (no API calls)
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
