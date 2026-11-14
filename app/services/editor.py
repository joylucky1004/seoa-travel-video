"""FFmpeg-based automatic editing for 9:16 Instagram Reels.

Pipeline:
  1. normalize every clip to 1080x1920 / 30fps / H.264 (scale-to-cover + center crop)
  2. append an ending CTA card ("Follow @staypick.kr")
  3. concatenate
  4. burn Korean subtitles + CTA text (ASS via libass) and add a silent stereo track
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import yaml

from app.config import PROJECT_ROOT, get_settings

from .subtitles import Cue, build_ass, wrap_korean


class FFmpegError(RuntimeError):
    pass


def load_presets() -> dict:
    return yaml.safe_load((PROJECT_ROOT / "config" / "video_presets.yaml").read_text(encoding="utf-8"))


def ffmpeg_available() -> bool:
    return shutil.which(get_settings().ffmpeg_binary) is not None


def _run(args: list[str], cwd: Path | None = None) -> None:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(proc.stderr.strip()[-2000:])


def _encode_args(p: dict) -> list[str]:
    return ["-c:v", p["video_codec"], "-preset", p["preset"], "-crf", str(p["crf"]),
            "-pix_fmt", p["pix_fmt"]]


def probe_duration(path: Path) -> float | None:
    s = get_settings()
    proc = subprocess.run([s.ffprobe_binary, "-v", "error", "-show_entries", "format=duration",
                           "-of", "default=nw=1:nk=1", str(path)], capture_output=True, text=True)
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


MAX_SLOWDOWN = 2.0  # stretch short (cheap) clips at most 2x, then hold the last frame


def normalize_clip(src: Path, dst: Path, duration: float) -> None:
    """Scale/crop to 9:16 and fit the clip to the scene length on the server.

    Clips generated at the model's minimum length are slowed down (max 2x) and the last
    frame is held, so short, cheap generations still fill the timeline — no extra API calls."""
    s, p = get_settings(), load_presets()["reels_9x16"]
    w, h = s.video_width, s.video_height
    actual = probe_duration(src)
    stretch = ""
    if actual and actual < duration - 0.05:
        factor = min(duration / actual, MAX_SLOWDOWN)
        hold = max(duration - actual * factor, 0) + 0.1
        stretch = f"setpts={factor:.4f}*PTS,tpad=stop_mode=clone:stop_duration={hold:.3f},"
    vf = (f"{stretch}scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
          f"fps={s.video_fps},setsar=1,format=yuv420p")
    _run([s.ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
          "-t", f"{duration:.3f}", "-vf", vf, "-an", *_encode_args(p), str(dst)])


def make_cta_card(dst: Path) -> None:
    s, presets = get_settings(), load_presets()
    p, bg = presets["reels_9x16"], presets["cta"]["background_color"]
    _run([s.ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
          f"color=c={bg}:s={s.video_width}x{s.video_height}:r={s.video_fps}:d={s.cta_duration_seconds}",
          *_encode_args(p), str(dst)])


def render_reel(clips: list[tuple[Path, float, str]], work_dir: Path, output: Path,
                add_cta: bool = True) -> Path:
    """clips: list of (path, duration_seconds, korean_subtitle)."""
    s, presets = get_settings(), load_presets()
    p = presets["reels_9x16"]
    work_dir.mkdir(parents=True, exist_ok=True)

    parts: list[Path] = []
    cues: list[Cue] = []
    t = 0.0
    for i, (src, dur, sub) in enumerate(clips):
        norm = work_dir / f"norm_{i:02d}.mp4"
        normalize_clip(src, norm, dur)
        parts.append(norm)
        if sub.strip():
            cues.append(Cue(t + 0.1, t + dur - 0.1, wrap_korean(sub)))
        t += dur

    if add_cta:
        cta = work_dir / "cta.mp4"
        make_cta_card(cta)
        parts.append(cta)
        cues.append(Cue(t, t + s.cta_duration_seconds, s.cta_text, style="CTA"))
        t += s.cta_duration_seconds

    (work_dir / "concat.txt").write_text(
        "".join(f"file '{part.name}'\n" for part in parts), encoding="utf-8")
    _run([s.ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error", "-f", "concat",
          "-safe", "0", "-i", "concat.txt", "-c", "copy", "joined.mp4"], cwd=work_dir)

    ass = build_ass(cues, width=s.video_width, height=s.video_height,
                    font_name=s.subtitle_font_name, sub_style=presets["subtitles"],
                    cta_font_size=presets["cta"]["font_size"])
    (work_dir / "subs.ass").write_text(ass, encoding="utf-8")

    fonts_dir = str(s.fonts_path).replace("\\", "/").replace(":", r"\:")
    _run([s.ffmpeg_binary, "-y", "-hide_banner", "-loglevel", "error",
          "-i", "joined.mp4", "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
          "-vf", f"subtitles=subs.ass:fontsdir='{fonts_dir}'",
          *_encode_args(p), "-c:a", p["audio_codec"], "-b:a", p["audio_bitrate"],
          "-t", f"{t:.3f}", "-movflags", "+faststart", str(output.resolve())], cwd=work_dir)
    return output
