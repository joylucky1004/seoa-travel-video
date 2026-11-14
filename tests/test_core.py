import shutil

import pytest

from app.config import get_settings
from app.models import ReelRequest, Scene
from app.services import character
from app.services.higgsfield import (LiveHiggsfieldClient, MockHiggsfieldClient,
                                     PaidCallsDisabledError, get_generator)
from app.services.prompt_builder import build_scene_prompt
from app.services.subtitles import Cue, build_ass, wrap_korean


def _reel():
    return ReelRequest(title="t", location="Jeju", extra_consistency_notes="white dress",
                       scenes=[Scene(visual_prompt="SEOA drinks coffee", subtitle_ko="커피 한 잔")])


def test_prompt_contains_consistency_and_9x16():
    reel = _reel()
    prompt = build_scene_prompt(character.load_profile(), reel, reel.scenes[0])
    assert "SEOA" in prompt and "Jeju" in prompt
    assert "white dress" in prompt and "9:16" in prompt


def test_default_is_mock():
    assert isinstance(get_generator(get_settings()), MockHiggsfieldClient)


def test_live_requires_both_switches(monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_MODE", "live")  # but ALLOW_PAID_API_CALLS=false
    get_settings.cache_clear()
    s = get_settings()
    assert not s.is_live
    assert isinstance(get_generator(s), MockHiggsfieldClient)
    with pytest.raises(PaidCallsDisabledError):
        LiveHiggsfieldClient(s)


def test_secret_not_leaked_in_repr(monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_API_KEY", "super-secret-value")
    get_settings.cache_clear()
    assert "super-secret-value" not in repr(get_settings())


def test_ass_has_korean_and_cta():
    ass = build_ass([Cue(0, 2, "안녕 제주"), Cue(2, 4, "Follow @staypick.kr", style="CTA")],
                    width=1080, height=1920, font_name="Noto Sans KR", sub_style={})
    assert "안녕 제주" in ass and "Follow @staypick.kr" in ass and "PlayResY: 1920" in ass


def test_wrap_korean():
    assert "\n" in wrap_korean("제주 애월 오션뷰 숙소에서 보내는 완벽한 하루", max_chars=10)


def test_reference_rejects_bad_extension():
    with pytest.raises(ValueError):
        character.save_reference("evil.exe", b"x")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_mock_pipeline_end_to_end():
    from app.services import pipeline
    reel = ReelRequest(title="e2e", scenes=[Scene(visual_prompt="SEOA walks", subtitle_ko="제주 도착",
                                                  duration_seconds=2)])
    job = pipeline.create_job(reel)
    pipeline.run_job(job.id)
    done = pipeline.load_job(job.id)
    assert done.status == "done", done.message
    assert done.clips[0].mock is True
    assert done.output_path.endswith(".mp4")
