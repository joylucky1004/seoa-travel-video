"""Korean subtitle + CTA generation in ASS format (rendered by libass in FFmpeg)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Cue:
    start: float
    end: float
    text: str
    style: str = "Sub"


def _ts(seconds: float) -> str:
    cs = int(round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _escape(text: str) -> str:
    # ASS uses {} for override tags and \N for line breaks.
    text = text.replace("\\", "＼").replace("{", "(").replace("}", ")")
    return text.replace("\r", "").replace("\n", r"\N")


def wrap_korean(text: str, max_chars: int = 16) -> str:
    """Break long Korean lines at spaces so each line fits the 9:16 frame."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) > max_chars and current:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return "\n".join(lines[:3])


def build_ass(cues: list[Cue], *, width: int, height: int, font_name: str,
              sub_style: dict, cta_font_size: int = 84) -> str:
    fs = sub_style.get("font_size", 64)
    outline = sub_style.get("outline", 4)
    shadow = sub_style.get("shadow", 1)
    margin_v = sub_style.get("margin_v", 360)
    primary = sub_style.get("primary_color", "&H00FFFFFF")
    outline_c = sub_style.get("outline_color", "&H00000000")

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{font_name},{fs},{primary},&H000000FF,{outline_c},&H64000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},2,80,80,{margin_v},1
Style: CTA,{font_name},{cta_font_size},&H00FFFFFF,&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,60,60,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for c in cues:
        if not c.text.strip():
            continue
        fade = r"{\fad(150,150)}" if c.style == "Sub" else r"{\fad(300,0)}"
        events.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},{c.style},,0,0,0,,{fade}{_escape(c.text)}")
    return header + "\n".join(events) + "\n"
