"""Live client for the official Higgsfield API — SKELETON ONLY.

Nothing in this file performs network calls yet. Before implementing:
  1. Read the official Higgsfield API documentation and confirm the
     endpoints, auth headers, request schema, and job-polling flow.
  2. Fill in `_submit`, `_poll` and `_download` below.
  3. Test with a single short clip and check the credit usage in your dashboard.

Paid calls are guarded twice: HIGGSFIELD_MODE=live AND ALLOW_PAID_API_CALLS=true.
"""
from __future__ import annotations

from pathlib import Path

from app.config import Settings

from .base import GenerationRequest, GenerationResult, VideoGenerator


class PaidCallsDisabledError(RuntimeError):
    pass


class LiveHiggsfieldClient(VideoGenerator):
    name = "higgsfield"

    def __init__(self, settings: Settings) -> None:
        if not settings.is_live:
            raise PaidCallsDisabledError(
                "Live Higgsfield calls are disabled. Set HIGGSFIELD_MODE=live and "
                "ALLOW_PAID_API_CALLS=true to enable (this spends credits)."
            )
        if settings.higgsfield_api_key is None:
            raise PaidCallsDisabledError("HIGGSFIELD_API_KEY is not set.")
        self._settings = settings

    def _auth_headers(self) -> dict[str, str]:
        # TODO: confirm header names against the official docs.
        headers = {"Authorization": f"Bearer {self._settings.higgsfield_api_key.get_secret_value()}"}
        return headers

    def _submit(self, req: GenerationRequest) -> str:
        # TODO: upload reference images, POST the generation job (9:16, duration,
        # prompt, negative prompt, character reference) and return the job id.
        raise NotImplementedError("Live Higgsfield submission is not implemented yet.")

    def _poll(self, job_id: str) -> str:
        # TODO: poll job status with backoff + timeout; return the result video URL.
        raise NotImplementedError

    def _download(self, url: str, output_path: Path) -> None:
        # TODO: stream the result file to output_path.
        raise NotImplementedError

    def generate(self, req: GenerationRequest, output_path: Path) -> GenerationResult:
        job_id = self._submit(req)
        url = self._poll(job_id)
        self._download(url, output_path)
        return GenerationResult(video_path=output_path, provider=self.name, mock=False, remote_id=job_id)
