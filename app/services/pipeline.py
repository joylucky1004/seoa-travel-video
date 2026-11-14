"""Job orchestration: prompts → (mock) Higgsfield clips → FFmpeg edit."""
from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone

from app.config import get_settings
from app.models import ClipResult, Job, JobStatus, ReelRequest

from . import character, editor
from .higgsfield import GenerationRequest, get_generator
from .prompt_builder import build_negative_prompt, build_scene_prompt

log = logging.getLogger(__name__)
_lock = threading.Lock()


def _job_file(job_id: str):
    return get_settings().jobs_path / job_id / "job.json"


def save_job(job: Job) -> None:
    job.updated_at = datetime.now(timezone.utc)
    path = _job_file(job.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        path.write_text(job.model_dump_json(indent=2), encoding="utf-8")


def load_job(job_id: str) -> Job | None:
    if not job_id.isalnum():
        return None
    path = _job_file(job_id)
    return Job.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None


def list_jobs(limit: int = 20) -> list[Job]:
    jobs = [load_job(p.name) for p in get_settings().jobs_path.iterdir() if p.is_dir()]
    return sorted((j for j in jobs if j), key=lambda j: j.created_at, reverse=True)[:limit]


def create_job(req: ReelRequest) -> Job:
    s = get_settings()
    if s.is_live and len(req.scenes) > s.max_clips_per_job:
        raise ValueError(f"live 모드에서는 작업당 최대 {s.max_clips_per_job}개 장면만 허용됩니다.")
    job = Job(id=uuid.uuid4().hex[:12], request=req, mode="live" if s.is_live else "mock")
    save_job(job)
    return job


def run_job(job_id: str) -> None:
    job = load_job(job_id)
    if job is None:
        return
    s = get_settings()
    job_dir = s.jobs_path / job.id
    try:
        profile = character.load_profile()
        refs = character.list_references()
        generator = get_generator(s)
        negative = build_negative_prompt(profile)

        job.status = JobStatus.generating
        clips_for_edit = []
        n = len(job.request.scenes)
        for i, scene in enumerate(job.request.scenes):
            job.message = f"장면 {i + 1}/{n} 생성 중 ({generator.name})"
            save_job(job)
            prompt = build_scene_prompt(profile, job.request, scene)
            out = job_dir / f"clip_{i:02d}.mp4"
            result = generator.generate(
                GenerationRequest(prompt=prompt, negative_prompt=negative, reference_images=refs,
                                  duration_seconds=scene.duration_seconds, aspect_ratio="9:16"),
                out)
            job.clips.append(ClipResult(scene_index=i, prompt=prompt, path=str(result.video_path),
                                        provider=result.provider, mock=result.mock))
            clips_for_edit.append((result.video_path, scene.duration_seconds, scene.subtitle_ko))
            job.progress = 0.7 * (i + 1) / n
            save_job(job)

        job.status = JobStatus.editing
        job.message = "FFmpeg 편집 중 (자막 · CTA)"
        save_job(job)
        output = job_dir / "reel_final.mp4"
        editor.render_reel(clips_for_edit, job_dir / "work", output, add_cta=job.request.add_cta)

        job.output_path = str(output)
        job.status, job.progress, job.message = JobStatus.done, 1.0, "완료"
    except Exception as exc:  # surface any failure to the UI
        log.exception("job %s failed", job.id)
        job.status, job.message = JobStatus.failed, f"실패: {exc}"[:500]
    save_job(job)
