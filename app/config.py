"""Application settings loaded from environment variables / .env.

Secrets are wrapped in SecretStr so they never show up in logs, reprs,
or API responses.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
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

    # Higgsfield (official API: https://docs.higgsfield.ai)
    higgsfield_mode: Literal["mock", "live"] = "mock"
    allow_paid_api_calls: bool = False
    # Credentials: either HF_API_KEY="KEY_ID:KEY_SECRET" (same format as the official SDK's HF_KEY),
    # or HF_API_KEY_ID + HF_API_KEY_SECRET. Never sent to the browser.
    higgsfield_api_key: SecretStr | None = Field(
        None, validation_alias=AliasChoices("HF_API_KEY", "HF_KEY", "HIGGSFIELD_API_KEY"))
    higgsfield_api_key_id: SecretStr | None = Field(
        None, validation_alias=AliasChoices("HF_API_KEY_ID", "HIGGSFIELD_API_KEY_ID"))
    higgsfield_api_secret: SecretStr | None = Field(
        None, validation_alias=AliasChoices("HF_API_KEY_SECRET", "HF_API_SECRET", "HIGGSFIELD_API_SECRET"))
    higgsfield_base_url: str = "https://api.higgsfield.ai"
    higgsfield_model: str = "bytedance/seedance-2.0/reference-to-video"
    higgsfield_resolution: Literal["480p", "720p", "1080p", "4k"] = "1080p"
    higgsfield_generate_audio: bool = False
    higgsfield_poll_timeout_seconds: int = 900
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
    # Optional override for where SEOA reference images live (e.g. a persistent disk).
    references_dir: Path | None = None

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
        p = self.references_dir or self.character_dir / "references"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def higgsfield_credentials(self) -> str | None:
        """Returns 'KEY_ID:KEY_SECRET' for the Authorization header, or None."""
        key = self.higgsfield_api_key.get_secret_value().strip() if self.higgsfield_api_key else ""
        key_id = self.higgsfield_api_key_id.get_secret_value().strip() if self.higgsfield_api_key_id else ""
        secret = self.higgsfield_api_secret.get_secret_value().strip() if self.higgsfield_api_secret else ""
        if key_id and secret:
            return f"{key_id}:{secret}"
        if key and ":" in key:
            return key
        if key and secret:
            return f"{key}:{secret}"
        return None

    @property
    def credentials_status(self) -> str:
        """Human-readable, secret-free description of the credential setup."""
        if self.higgsfield_credentials():
            return "ok"
        if self.higgsfield_api_key or self.higgsfield_api_key_id:
            return "incomplete"  # key present but the secret part is missing
        return "missing"

    @property
    def is_live(self) -> bool:
        """True only when BOTH safety switches are on."""
        return self.higgsfield_mode == "live" and self.allow_paid_api_calls


@lru_cache
def get_settings() -> Settings:
    return Settings()
