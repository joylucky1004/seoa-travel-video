"""Provider-agnostic interface for image-to-video generation."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class GenerationRequest:
    prompt: str
    negative_prompt: str
    reference_images: list[Path]
    duration_seconds: float
    aspect_ratio: str = "9:16"
    seed: int | None = None
    extra: dict = field(default_factory=dict)


@dataclass
class GenerationResult:
    video_path: Path
    provider: str
    mock: bool
    remote_id: str | None = None


class VideoGenerator(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, req: GenerationRequest, output_path: Path) -> GenerationResult:
        """Generate one clip and write it to output_path."""
