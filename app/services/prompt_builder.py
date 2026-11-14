"""Builds Higgsfield prompts that carry SEOA's consistency instructions."""
from __future__ import annotations

from app.models import ReelRequest, Scene


def build_scene_prompt(profile: dict, reel: ReelRequest, scene: Scene) -> str:
    parts: list[str] = [
        f"Character: {profile['name']} — " + "; ".join(profile.get("appearance", [])),
        f"Outfit: {profile.get('default_outfit', '')}",
        f"Scene: {scene.visual_prompt.strip()}",
    ]
    if reel.location:
        parts.append(f"Location: {reel.location}")
    if scene.camera:
        parts.append(f"Camera: {scene.camera}")
    parts.append(f"Style: {profile.get('visual_style', '').strip()}")
    if reel.style_notes:
        parts.append(f"Extra style: {reel.style_notes}")

    rules = list(profile.get("consistency_rules", []))
    if reel.extra_consistency_notes:
        rules.append(reel.extra_consistency_notes)
    parts.append("Consistency: " + "; ".join(rules))
    parts.append("Format: vertical 9:16, no on-screen text")
    return "\n".join(p for p in parts if p.split(":", 1)[1].strip())


def build_negative_prompt(profile: dict) -> str:
    return ", ".join(profile.get("negative", []))
