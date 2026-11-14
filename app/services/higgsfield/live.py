"""Live client for the official Higgsfield REST API.

Implemented from https://docs.higgsfield.ai (checked 2026-11):
  - Base URL           https://api.higgsfield.ai
  - Auth               Authorization: Key {KEY_ID}:{KEY_SECRET}
  - Upload             POST /files/generate-upload-url {"content_type"} → PUT upload_url (+ upload_headers)
                       → use public_url as model input
  - Estimate           POST /estimate/{model_id} (same body as generation, not charged)
  - Generate           POST /{model_id} with Idempotency-Key → {request_id, status_url, cancel_url}
  - Status             GET /requests/{request_id}/status
                       status ∈ queued | in_progress | completed | failed | nsfw | canceled
                       completed video → {"video": {"url": ...}}
  - Models             per-model request bodies live in models.py (cheapest settings only)

Paid calls are guarded twice: HIGGSFIELD_MODE=live AND ALLOW_PAID_API_CALLS=true,
and the pipeline additionally waits for a per-job approval in the UI.
Generation submits are NEVER retried automatically (credit safety); only status polling,
uploads and free estimates are retried on transient errors.
"""
from __future__ import annotations

import hashlib
import json
import random
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from app.config import Settings

from .base import (GenerationError, GenerationRequest, GenerationResult, StatusCallback,
                   VideoGenerator)
from .models import build_arguments, get_profile


class PaidCallsDisabledError(RuntimeError):
    pass


class HiggsfieldAPIError(RuntimeError):
    def __init__(self, status_code: int, detail: str, correlation_id: str | None = None):
        msg = f"Higgsfield API {status_code}: {detail}"
        if correlation_id:
            msg += f" (X-Correlation-ID {correlation_id})"
        super().__init__(msg)
        self.status_code = status_code
        self.detail = detail
        self.correlation_id = correlation_id


TERMINAL = {"completed", "failed", "nsfw", "canceled"}
_CONTENT_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
                  ".webp": "image/webp", ".gif": "image/gif"}
_MAX_REFERENCE_IMAGES = 10
_UPLOAD_CACHE_TTL = 3600  # seconds; reuse uploaded reference URLs instead of re-uploading


def _error_detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail", resp.text)
    except Exception:
        return resp.text[:300]
    if isinstance(detail, dict):
        return str(detail.get("message") or detail.get("code") or detail)
    return str(detail)[:500]


class LiveHiggsfieldClient(VideoGenerator):
    name = "higgsfield"
    mock = False

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, estimate_only: bool = False) -> None:
        """estimate_only=True allows free uploads/estimates without the live switches;
        submit() is then refused."""
        if not settings.is_live and not estimate_only:
            raise PaidCallsDisabledError(
                "Live Higgsfield calls are disabled. Set HIGGSFIELD_MODE=live and "
                "ALLOW_PAID_API_CALLS=true to enable (this spends credits).")
        credentials = settings.higgsfield_credentials()
        if not credentials:
            raise PaidCallsDisabledError(
                "Higgsfield credentials are missing or incomplete. Set HF_API_KEY=KEY_ID:KEY_SECRET "
                "(or HF_API_KEY_ID and HF_API_KEY_SECRET).")
        self._estimate_only = estimate_only or not settings.is_live
        self._s = settings
        self._base = settings.higgsfield_base_url.rstrip("/")
        self._sleep = sleep
        self._api = httpx.Client(base_url=self._base, transport=transport,
                                 headers={"Authorization": f"Key {credentials}"},
                                 timeout=httpx.Timeout(60.0, connect=15.0))
        # Separate client WITHOUT credentials for presigned storage URLs and CDN downloads.
        self._public = httpx.Client(transport=transport, timeout=httpx.Timeout(300.0, connect=15.0),
                                    follow_redirects=True)

    # -- low level ----------------------------------------------------------
    def _call(self, method: str, path: str, *, retries: int = 3, **kwargs) -> dict:
        """Calls the API; retries 429/5xx/network errors with backoff (safe because
        generation submits always carry an Idempotency-Key)."""
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                resp = self._api.request(method, path, **kwargs)
            except httpx.TransportError as exc:
                if attempt == retries:
                    raise HiggsfieldAPIError(0, f"network error: {exc}") from exc
                self._sleep(delay + random.uniform(0, 0.5)); delay = min(delay * 2, 30)
                continue
            if resp.status_code < 400:
                return resp.json()
            retryable = resp.status_code in (429, 500, 502, 503, 504)
            if retryable and attempt < retries:
                wait = float(resp.headers.get("Retry-After", delay))
                self._sleep(min(wait, 60) + random.uniform(0, 0.5)); delay = min(delay * 2, 30)
                continue
            raise HiggsfieldAPIError(resp.status_code, _error_detail(resp),
                                     resp.headers.get("X-Correlation-ID"))
        raise AssertionError("unreachable")

    # -- references ---------------------------------------------------------
    def _upload_one(self, path: Path) -> str:
        ext = path.suffix.lower()
        data_path = path
        tmp = None
        if ext not in _CONTENT_TYPES:  # e.g. HEIC → convert to JPEG with FFmpeg
            tmp = Path(tempfile.mkstemp(suffix=".jpg")[1])
            proc = subprocess.run([self._s.ffmpeg_binary, "-y", "-loglevel", "error", "-i", str(path),
                                   "-frames:v", "1", "-q:v", "2", str(tmp)], capture_output=True)
            if proc.returncode != 0:
                tmp.unlink(missing_ok=True)
                raise ValueError(f"{path.name}: 지원하지 않는 이미지 형식입니다 (JPG/PNG/WEBP로 다시 올려주세요).")
            data_path, ext = tmp, ".jpg"
        content_type = _CONTENT_TYPES[ext]
        try:
            info = self._call("POST", "/files/generate-upload-url", json={"content_type": content_type})
            headers = info.get("upload_headers") or {"Content-Type": content_type}
            put = self._public.put(info["upload_url"], content=data_path.read_bytes(), headers=headers)
            if put.status_code >= 400:
                raise HiggsfieldAPIError(put.status_code, f"reference upload failed for {path.name}")
            return info["public_url"]
        finally:
            if tmp:
                tmp.unlink(missing_ok=True)

    def _cache_file(self) -> Path:
        return self._s.data_path / "ref_upload_cache.json"

    def prepare_references(self, paths: list[Path]) -> list[str]:
        """Uploads reference images, reusing URLs uploaded within the last hour."""
        if not paths:
            raise ValueError("SEOA 레퍼런스 이미지를 1장 이상 등록해야 실제 영상을 만들 수 있습니다.")
        cache_path = self._cache_file()
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cache = {}
        now, urls = time.time(), []
        for p in paths[:_MAX_REFERENCE_IMAGES]:
            digest = hashlib.sha256(p.read_bytes()).hexdigest()
            hit = cache.get(digest)
            if hit and now - hit["ts"] < _UPLOAD_CACHE_TTL:
                urls.append(hit["url"])
                continue
            url = self._upload_one(p)
            cache[digest] = {"url": url, "ts": now}
            urls.append(url)
        cache_path.write_text(json.dumps(cache), encoding="utf-8")
        return urls

    # -- generation ---------------------------------------------------------
    def build_arguments(self, req: GenerationRequest) -> dict:
        if req.aspect_ratio != "9:16":
            raise ValueError("Only 9:16 is supported")
        profile = get_profile(req.model)  # unknown / unapproved models are refused
        return build_arguments(profile, prompt=req.prompt, negative_prompt=req.negative_prompt,
                               reference_urls=req.reference_urls, duration=req.duration,
                               resolution=req.resolution)

    def estimate_usd(self, req: GenerationRequest) -> float | None:
        """Free: POST /estimate/{model}. Nothing is generated."""
        data = self._call("POST", f"/estimate/{req.model}", json=self.build_arguments(req))
        try:
            return float(data["usd"])
        except (KeyError, TypeError, ValueError):
            return None

    def submit(self, req: GenerationRequest, idempotency_key: str) -> str:
        """Paid. Sent exactly once — no automatic retry, never a different model."""
        if self._estimate_only:
            raise PaidCallsDisabledError("This client was created for estimates only.")
        data = self._call("POST", f"/{req.model}", json=self.build_arguments(req),
                          headers={"Idempotency-Key": idempotency_key}, retries=0)
        return data["request_id"]

    def status(self, request_id: str) -> dict:
        return self._call("GET", f"/requests/{request_id}/status")

    def wait(self, request_id: str, output_path: Path, on_status: StatusCallback | None = None) -> GenerationResult:
        deadline = time.monotonic() + self._s.higgsfield_poll_timeout_seconds
        delay, last = 2.0, None
        while True:
            data = self.status(request_id)
            status = data.get("status", "unknown")
            if status != last and on_status:
                on_status(status, request_id)
            last = status
            if status in TERMINAL:
                break
            if time.monotonic() > deadline:
                raise GenerationError("시간 초과: 생성이 끝나지 않았습니다.", "timeout", request_id)
            self._sleep(delay + random.uniform(0, 0.5))
            delay = min(delay * 1.5, 10.0)

        if status != "completed":
            reason = {"nsfw": "콘텐츠 검수에 걸렸습니다 (과금되지 않음).",
                      "canceled": "취소되었습니다.",
                      "failed": "생성에 실패했습니다 (과금되지 않음)."}[status]
            if data.get("error"):
                reason += f" {data['error']}"
            raise GenerationError(reason, status, request_id)

        url = (data.get("video") or {}).get("url")
        if not url:
            raise GenerationError("완료 응답에 영상 URL이 없습니다.", "failed", request_id)
        with self._public.stream("GET", url) as resp:
            if resp.status_code >= 400:
                raise GenerationError(f"영상 다운로드 실패 (HTTP {resp.status_code})", "failed", request_id)
            with output_path.open("wb") as fh:
                for chunk in resp.iter_bytes():
                    fh.write(chunk)
        return GenerationResult(video_path=output_path, provider=self.name, mock=False, remote_id=request_id)
