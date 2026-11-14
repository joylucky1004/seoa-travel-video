"""Cost-focused profiles for Higgsfield reference-to-video models.

Every profile was built from that model's request schema on https://docs.higgsfield.ai
(checked 2026-11-14). Only models that accept SEOA reference images (`image_urls`) AND a
9:16 aspect ratio are listed. Each profile pins the cheapest options its schema allows:
the lowest resolution (never above 720p), the minimum duration, and audio off.

The docs publish no per-model prices. Use the free estimate endpoint
(`POST /estimate/{model}`, see /api/models/compare) to compare real costs for your account.
"""
from __future__ import annotations

from dataclasses import dataclass, field

RESOLUTION_ORDER = ["360p", "480p", "540p", "720p", "1080p", "2k", "4k"]
MAX_RESOLUTION = "720p"


@dataclass(frozen=True)
class ModelProfile:
    id: str                    # endpoint id, e.g. "xai/grok-imagine-video/v1.5/reference-to-video"
    label: str
    min_duration: int          # seconds, from the schema
    max_duration: int
    max_reference_images: int
    resolution_field: str | None      # "resolution" | "mode" | None
    resolutions: tuple[str, ...]      # allowed values, cheapest first
    extra: dict = field(default_factory=dict)  # fixed cost-saving fields (audio off, etc.)
    negative_prompt_field: bool = False
    max_prompt_chars: int | None = None
    notes: str = ""

    @property
    def cheapest_resolution(self) -> str | None:
        return self.resolutions[0] if self.resolutions else None

    def allowed_resolutions(self) -> list[str]:
        """Resolutions at or below 720p (std mode counts as the low tier for Kling)."""
        out = []
        for r in self.resolutions:
            if r in RESOLUTION_ORDER and RESOLUTION_ORDER.index(r) > RESOLUTION_ORDER.index(MAX_RESOLUTION):
                continue
            out.append(r)
        return out

    def info(self) -> dict:
        return {"id": self.id, "label": self.label, "min_duration": self.min_duration,
                "max_duration": self.max_duration, "max_reference_images": self.max_reference_images,
                "cheapest_resolution": self.cheapest_resolution,
                "allowed_resolutions": self.allowed_resolutions(), "notes": self.notes}


PROFILES: dict[str, ModelProfile] = {p.id: p for p in [
    ModelProfile("xai/grok-imagine-video/v1.5/reference-to-video", "Grok Imagine Video 1.5 · Reference",
                 1, 15, 7, "resolution", ("480p", "720p"),
                 notes="최소 1초, 480p, 레퍼런스 최대 7장. 문서상 가장 짧고 낮은 설정."),
    ModelProfile("alibaba/wan-3.0/reference-to-video", "Wan 3.0 · Reference",
                 2, 30, 10, "resolution", ("480p", "720p"), extra={"generate_audio": False},
                 notes="최소 2초, 480p, 레퍼런스 최대 10장."),
    ModelProfile("alibaba/wan-3.0-prime/reference-to-video", "Wan 3.0 Prime · Reference",
                 2, 30, 10, "resolution", ("480p", "720p"), extra={"generate_audio": False},
                 notes="Wan 3.0 상위 버전 (보통 더 비쌈)."),
    ModelProfile("wan/v2.7/reference-to-video", "Wan 2.7 · Reference",
                 2, 10, 5, "resolution", ("720p",), negative_prompt_field=True,
                 notes="최소 2초, 최저 720p, 레퍼런스 최대 5장."),
    ModelProfile("kling-video/o3/image-reference", "Kling O3 · Image reference (std)",
                 3, 15, 4, "mode", ("std",), extra={"sound": "off", "multi_shots": False},
                 notes="최소 3초, std 모드, 사운드 끔."),
    ModelProfile("kling-video/omni/image-reference", "Kling Omni · Image reference (std)",
                 3, 10, 4, "mode", ("std",), max_prompt_chars=2500,
                 notes="최소 3초, std 모드."),
    ModelProfile("bytedance/seedance-2.0/reference-to-video", "Seedance 2.0 · Reference",
                 4, 15, 9, "resolution", ("480p", "720p"), extra={"generate_audio": False},
                 notes="최소 4초, 480p, 레퍼런스 최대 9장."),
    ModelProfile("bytedance/seedance-2.5/reference-to-video", "Seedance 2.5 · Reference",
                 4, 30, 9, "resolution", ("480p", "720p"),
                 extra={"generate_audio": False, "bitrate_mode": "standard"},
                 notes="최소 4초, 480p, 표준 비트레이트."),
    ModelProfile("higgsfield/cinema-studio/4.0", "Cinema Studio 4.0",
                 4, 30, 9, "resolution", ("480p", "720p"), extra={"generate_audio": False},
                 notes="최소 4초, 480p, 카메라·스타일 옵션 (자동)."),
]}

# Provisional default until the free estimate comparison confirms the cheapest model for
# this account: lowest documented resolution (480p) and shortest minimum duration (1 s).
DEFAULT_MODEL = "xai/grok-imagine-video/v1.5/reference-to-video"


def get_profile(model_id: str) -> ModelProfile:
    try:
        return PROFILES[model_id]
    except KeyError:
        raise ValueError(f"지원 목록에 없는 모델입니다: {model_id}. 허용: {', '.join(PROFILES)}") from None


def resolve_resolution(profile: ModelProfile, override: str = "") -> tuple[str | None, str]:
    """Returns (resolution, warning). Never above 720p; falls back to the cheapest tier."""
    allowed = profile.allowed_resolutions()
    if override:
        if override in allowed:
            return override, ""
        return profile.cheapest_resolution, (
            f"HIGGSFIELD_RESOLUTION={override} 은(는) 이 모델에서 허용되지 않거나 720p를 넘어 "
            f"{profile.cheapest_resolution}(으)로 고정했습니다.")
    return profile.cheapest_resolution, ""


def resolve_duration(profile: ModelProfile, scene_seconds: float, policy: str) -> int:
    import math
    if policy == "minimum":
        return profile.min_duration
    return min(max(math.ceil(scene_seconds), profile.min_duration), profile.max_duration)


def build_arguments(profile: ModelProfile, *, prompt: str, negative_prompt: str,
                    reference_urls: list[str], duration: int, resolution: str | None) -> dict:
    """Request body that matches the model's documented schema exactly."""
    if not reference_urls:
        raise ValueError("레퍼런스 이미지가 필요합니다.")
    text = prompt
    body: dict = {}
    if negative_prompt:
        if profile.negative_prompt_field:
            body["negative_prompt"] = negative_prompt
        else:
            text += f"\nAvoid: {negative_prompt}"
    if profile.max_prompt_chars:
        text = text[:profile.max_prompt_chars]
    body.update({
        "prompt": text,
        "image_urls": reference_urls[:profile.max_reference_images],
        "duration": int(duration),
        "aspect_ratio": "9:16",
    })
    if profile.resolution_field and resolution:
        body[profile.resolution_field] = resolution
    body.update(profile.extra)
    return body
