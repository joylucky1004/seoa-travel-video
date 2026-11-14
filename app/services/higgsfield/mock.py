"""Mock Higgsfield client: renders a placeholder 9:16 clip locally with FFmpeg.

No network calls, no credits. Lets the whole pipeline (UI → prompts → editing →
subtitles → CTA) be tested end to end for free.
"""
from __future__ import annotations

import subprocess
import uuid
from pathlib import Path

from app.config import get_settings

from .base import GenerationRequest, GenerationResult, StatusCallback, VideoGenerator

_COLORS = ["0x3B6E8F", "0x8F6A3B", "0x4F8F3B", "0x7A3B8F", "0x8F3B4F", "0x3B8F86"]


class MockHiggsfieldClient(VideoGenerator):
    name = "higgsfield-mock"
    mock = True

    def __init__(self) -> None:
        self._pending: dict[str, tuple[int, GenerationRequest]] = {}
        self._counter = 0

    def prepare_references(self, paths: list[Path]) -> list[str]:
        return [f"mock://{p.name}" for p in paths]

    def estimate_usd(self, req: GenerationRequest) -> float | None:
        return 0.0

    def submit(self, req: GenerationRequest, idempotency_key: str) -> str:
        if req.aspect_ratio != "9:16":
            raise ValueError("Only 9:16 is supported")
        self._counter += 1
        request_id = f"mock-{uuid.uuid4().hex[:10]}"
        self._pending[request_id] = (self._counter, req)
        return request_id

    def wait(self, request_id: str, output_path: Path, on_status: StatusCallback | None = None) -> GenerationResult:
        n, req = self._pending.pop(request_id)
        if on_status:
            on_status("in_progress", request_id)
        s = get_settings()
        color = _COLORS[(n - 1) % len(_COLORS)]
        label = f"MOCK SEOA CLIP {n}  refs={len(req.reference_urls)}"
        base = [s.ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error",
                "-f", "lavfi", "-i",
                f"color=c={color}:s={s.video_width}x{s.video_height}:r={s.video_fps}:d={req.duration_seconds}"]
        tail = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(req.duration_seconds), str(output_path)]
        text = (f"drawtext=text='{label}':fontcolor=white@0.85:fontsize=48:"
                "x=(w-text_w)/2:y=h*0.12:box=1:boxcolor=black@0.35:boxborderw=20")
        try:
            subprocess.run(base + ["-vf", text] + tail, check=True, capture_output=True)
        except subprocess.CalledProcessError:
            # drawtext may be unavailable (no fontconfig) — fall back to a plain clip.
            subprocess.run(base + tail, check=True, capture_output=True)
        if on_status:
            on_status("completed", request_id)
        return GenerationResult(video_path=output_path, provider=self.name, mock=True, remote_id=request_id)
