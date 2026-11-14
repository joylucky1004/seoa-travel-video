"""Provider-agnostic interface for reference-to-video generation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# Called with (status, request_id) whenever a remote request changes state.
StatusCallback = Callable[[str, str | None], None]


@dataclass
class GenerationRequest:
    prompt: str
    negative_prompt: str
    reference_urls: list[str]
    duration_seconds: float
    aspect_ratio: str = "9:16"
    extra: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    video_path: Path
    provider: str
    mock: bool
    remote_id: str | None = None


class GenerationError(RuntimeError):
    """A generation that reached a terminal non-success state (failed / nsfw / canceled / timeout)."""

    def __init__(self, message: str, status: str = "failed", request_id: str | None = None):
        super().__init__(message)
        self.status = status
        self.request_id = request_id


class VideoGenerator(ABC):
    name: str = "base"
    mock: bool = True

    @abstractmethod
    def prepare_references(self, paths: list[Path]) -> list[str]:
        """Make reference images usable by the provider; returns their URLs/ids."""

    @abstractmethod
    def estimate_usd(self, req: GenerationRequest) -> float | None:
        """Cost estimate for one clip (no generation, no charge)."""

    @abstractmethod
    def submit(self, req: GenerationRequest, idempotency_key: str) -> str:
        """Submit a generation; returns the provider request id."""

    @abstractmethod
    def wait(self, request_id: str, output_path: Path, on_status: StatusCallback | None = None) -> GenerationResult:
        """Block until the request finishes and write the clip to output_path."""
