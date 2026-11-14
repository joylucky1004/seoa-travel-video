"""SEOA character profile + reference image management."""
from __future__ import annotations

import json
import re
import uuid
from pathlib import Path

import yaml

from app.config import PROJECT_ROOT, get_settings

DEFAULT_PROFILE_PATH = PROJECT_ROOT / "config" / "seoa_character.yaml"
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_REFERENCES = 8


def _override_path() -> Path:
    return get_settings().data_path / "character.json"


def load_profile() -> dict:
    profile = yaml.safe_load(DEFAULT_PROFILE_PATH.read_text(encoding="utf-8"))
    override = _override_path()
    if override.exists():
        profile.update(json.loads(override.read_text(encoding="utf-8")))
    return profile


def save_overrides(consistency_rules: list[str], default_outfit: str | None = None) -> dict:
    data = {"consistency_rules": [r.strip() for r in consistency_rules if r.strip()]}
    if default_outfit is not None:
        data["default_outfit"] = default_outfit.strip()
    _override_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_profile()


def list_references() -> list[Path]:
    ref_dir = get_settings().references_path
    return sorted(p for p in ref_dir.iterdir() if p.suffix.lower() in ALLOWED_IMAGE_EXT)


def save_reference(filename: str, content: bytes) -> Path:
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_IMAGE_EXT:
        raise ValueError(f"지원하지 않는 이미지 형식입니다: {ext}")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("이미지가 너무 큽니다 (최대 15MB).")
    if len(list_references()) >= MAX_REFERENCES:
        raise ValueError(f"레퍼런스 이미지는 최대 {MAX_REFERENCES}장까지 등록할 수 있습니다.")
    stem = re.sub(r"[^A-Za-z0-9_-]", "", Path(filename).stem)[:40] or "ref"
    dest = get_settings().references_path / f"{stem}-{uuid.uuid4().hex[:8]}{ext}"
    dest.write_bytes(content)
    return dest


def delete_reference(name: str) -> bool:
    # Only allow plain file names inside the references folder.
    if Path(name).name != name:
        return False
    target = get_settings().references_path / name
    if target.exists() and target.suffix.lower() in ALLOWED_IMAGE_EXT:
        target.unlink()
        return True
    return False
