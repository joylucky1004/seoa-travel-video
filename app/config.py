"""Application settings loaded from environment variables / .env.

Secrets are wrapped in SecretStr so they never show up in logs, reprs,
or API responses.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # App
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    app_password: SecretStr | None = None

    # Higgsfield
    higgsfield_mode: Literal["mock", "live"] = "mock"
    allow_paid_api_calls: bool = False
    higgsfield_api_key: SecretStr | None = None
    higgsfield_api_secret: SecretStr | None = None
    higgsfield_base_url: str = "https://platform.higgsfield.ai"
    max_clips_per_job: int = 6

    # Video
    ffmpeg_binary: str = "ffmpeg"
    video_width: int = 1080
    video_height: int = 1920
    video_fps: int = 30
    cta_text: str = "Follow @staypick.kr"
    cta_duration_seconds: float = 2.5
    subtitle_font_name: str = "Noto Sans KR"

    # Storage
    data_dir: Path = Path("data")

    # Derived paths -------------------------------------------------------
    @property
    def data_path(self) -> Path:
        p = self.data_dir if self.data_dir.is_absolute() else PROJECT_ROOT / self.data_dir
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def jobs_path(self) -> Path:
        p = self.data_path / "jobs"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def fonts_path(self) -> Path:
        return PROJECT_ROOT / "assets" / "fonts"

    @property
    def character_dir(self) -> Path:
        return PROJECT_ROOT / "assets" / "characters" / "seoa"

    @property
    def references_path(self) -> Path:
        p = self.character_dir / "references"
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def is_live(self) -> bool:
        """True only when BOTH safety switches are on."""
        return self.higgsfield_mode == "live" and self.allow_paid_api_calls


@lru_cache
def get_settings() -> Settings:
    return Settings()
