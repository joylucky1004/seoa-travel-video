"""Live Higgsfield client + approval flow, tested against a fake HTTP server (no real calls)."""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.services import character, pipeline
from app.services.higgsfield import (GenerationError, GenerationRequest, LiveHiggsfieldClient,
                                     MockHiggsfieldClient, PaidCallsDisabledError)

KEY = "kid_123:sec_456"


@pytest.fixture
def live_env(monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_MODE", "live")
    monkeypatch.setenv("ALLOW_PAID_API_CALLS", "true")
    monkeypatch.setenv("HF_API_KEY", KEY)
    monkeypatch.setenv("APP_PASSWORD", "pw")
    get_settings.cache_clear()
    return get_settings()


class FakeHiggsfield:
    """Mimics the documented endpoints of api.higgsfield.ai."""

    def __init__(self, final_status="completed", polls_before_done=2):
        self.calls: list[httpx.Request] = []
        self.final_status = final_status
        self.polls_before_done = polls_before_done
        self.polls = 0
        self.submitted_bodies: list[dict] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        url, path = str(req.url), req.url.path
        if req.url.host == "api.higgsfield.ai":
            if req.headers.get("authorization") != f"Key {KEY}":
                return httpx.Response(401, json={"detail": "Invalid credentials"})
            if path == "/files/generate-upload-url":
                ct = json.loads(req.content)["content_type"]
                return httpx.Response(200, json={
                    "public_url": f"https://cdn.test/in/{len(self.calls)}.jpg",
                    "upload_url": "https://storage.test/put", "content_type": ct,
                    "upload_headers": {"Content-Type": ct, "x-amz-tagging": "retention=temporary"}})
            if path.startswith("/estimate/"):
                return httpx.Response(200, json={"usd": "0.40"})
            if path == "/bytedance/seedance-2.0/reference-to-video":
                self.submitted_bodies.append(json.loads(req.content))
                rid = f"00000000-0000-0000-0000-{len(self.submitted_bodies):012d}"
                return httpx.Response(200, json={"status": "queued", "request_id": rid,
                                                 "status_url": f"https://api.higgsfield.ai/requests/{rid}/status"})
            if path.endswith("/status"):
                rid = path.split("/")[2]
                self.polls += 1
                if self.polls <= self.polls_before_done:
                    return httpx.Response(200, json={"status": "in_progress", "request_id": rid})
                body = {"status": self.final_status, "request_id": rid}
                if self.final_status == "completed":
                    body["video"] = {"url": "https://cdn.test/out.mp4"}
                return httpx.Response(200, json=body)
        if url == "https://storage.test/put":
            assert "authorization" not in req.headers  # never send credentials to storage
            return httpx.Response(200)
        if url == "https://cdn.test/out.mp4":
            assert "authorization" not in req.headers
            return httpx.Response(200, content=b"FAKE-MP4")
        return httpx.Response(404, json={"detail": "not found"})


def _client(fake, settings):
    return LiveHiggsfieldClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None)


def test_hf_api_key_alias_and_secret_not_exposed(live_env):
    assert live_env.higgsfield_credentials() == KEY
    assert KEY not in repr(live_env)


def test_key_without_secret_is_incomplete(monkeypatch):
    monkeypatch.setenv("HF_API_KEY", "only-an-id")
    get_settings.cache_clear()
    assert get_settings().credentials_status == "incomplete"


def test_separate_id_and_secret(monkeypatch):
    monkeypatch.setenv("HF_API_KEY_ID", "a")
    monkeypatch.setenv("HF_API_KEY_SECRET", "b")
    get_settings.cache_clear()
    assert get_settings().higgsfield_credentials() == "a:b"


def test_live_blocked_without_paid_switch(monkeypatch):
    monkeypatch.setenv("HIGGSFIELD_MODE", "live")
    monkeypatch.setenv("HF_API_KEY", KEY)
    get_settings.cache_clear()
    with pytest.raises(PaidCallsDisabledError):
        LiveHiggsfieldClient(get_settings())


def test_request_body_matches_documented_schema(live_env, tmp_path):
    fake = FakeHiggsfield()
    c = _client(fake, live_env)
    req = GenerationRequest(prompt="SEOA at the beach\nCamera: slow dolly in", negative_prompt="extra fingers",
                            reference_urls=["https://cdn.test/a.jpg"], duration_seconds=5)
    body = c.build_arguments(req)
    assert set(body) == {"prompt", "image_urls", "duration", "aspect_ratio", "resolution", "generate_audio"}
    assert body["aspect_ratio"] == "9:16" and body["duration"] == 5 and body["resolution"] == "1080p"
    assert "slow dolly in" in body["prompt"] and "Avoid: extra fingers" in body["prompt"]
    assert c.build_arguments(GenerationRequest("p", "", ["u"], 2))["duration"] == 4  # model minimum


def test_upload_estimate_submit_poll_download(live_env, tmp_path):
    fake = FakeHiggsfield()
    c = _client(fake, live_env)
    img = tmp_path / "seoa.png"
    img.write_bytes(b"\x89PNG fake")
    urls = c.prepare_references([img])
    assert urls[0].startswith("https://cdn.test/")
    req = GenerationRequest("prompt", "", urls, 5)
    assert c.estimate_usd(req) == pytest.approx(0.40)
    rid = c.submit(req, "idem-1")
    submit_call = [r for r in fake.calls if r.url.path == "/bytedance/seedance-2.0/reference-to-video"][0]
    assert submit_call.headers["idempotency-key"] == "idem-1"
    seen = []
    out = tmp_path / "clip.mp4"
    res = c.wait(rid, out, lambda st, _rid: seen.append(st))
    assert out.read_bytes() == b"FAKE-MP4" and res.mock is False
    assert seen == ["in_progress", "completed"]


def test_nsfw_is_reported(live_env, tmp_path):
    c = _client(FakeHiggsfield(final_status="nsfw", polls_before_done=0), live_env)
    with pytest.raises(GenerationError) as exc:
        c.wait("00000000-0000-0000-0000-000000000001", tmp_path / "x.mp4")
    assert exc.value.status == "nsfw"


def test_wrong_credentials_surface_401(monkeypatch, live_env):
    monkeypatch.setenv("HF_API_KEY", "bad:key")
    get_settings.cache_clear()
    c = _client(FakeHiggsfield(), get_settings())
    with pytest.raises(Exception) as exc:
        c.estimate_usd(GenerationRequest("p", "", ["u"], 5))
    assert "401" in str(exc.value)


class _FakeLiveGenerator(MockHiggsfieldClient):
    """Mock rendering but behaves like the live client for the pipeline (estimates, refs)."""
    mock = False
    name = "fake-live"

    def __init__(self):
        super().__init__()
        self.submits = 0

    def prepare_references(self, paths):
        assert paths, "references required"
        return [f"https://cdn.test/{p.name}" for p in paths]

    def estimate_usd(self, req):
        return 0.5

    def submit(self, req, key):
        self.submits += 1
        return super().submit(req, key)


def test_live_job_waits_for_approval_then_generates(live_env, monkeypatch):
    character.save_reference("seoa.jpg", b"img")
    gen = _FakeLiveGenerator()
    monkeypatch.setattr(pipeline, "generator_factory", lambda s: gen)
    from app.models import ReelRequest, Scene
    job = pipeline.create_job(ReelRequest(title="t", scenes=[
        Scene(visual_prompt="SEOA walks", subtitle_ko="제주", duration_seconds=2),
        Scene(visual_prompt="SEOA smiles", subtitle_ko="바다", duration_seconds=2)]))
    pipeline.next_step(job)(job.id)
    job = pipeline.load_job(job.id)
    assert job.status == "awaiting_approval" and job.estimate_total_usd == pytest.approx(1.0)
    assert gen.submits == 0  # nothing paid before approval
    pipeline.approve(job.id)
    pipeline.run_generation(job.id)
    job = pipeline.load_job(job.id)
    assert job.status == "done", job.message
    assert gen.submits == 2 and all(sc.clip_ready for sc in job.scenes)


def test_api_requires_password_in_live_and_hides_key(live_env, monkeypatch):
    monkeypatch.setattr(pipeline, "generator_factory", lambda s: _FakeLiveGenerator())
    client = TestClient(__import__("app.main", fromlist=["app"]).app)
    assert client.get("/api/status").status_code == 401
    r = client.get("/api/status", auth=("seoa", "pw"))
    assert r.status_code == 200 and r.json()["mode"] == "live"
    assert "kid_123" not in r.text and "sec_456" not in r.text
    monkeypatch.setenv("APP_PASSWORD", "")
    get_settings.cache_clear()
    r = client.post("/api/jobs", json={"title": "t", "scenes": [{"visual_prompt": "abc"}]})
    assert r.status_code == 403
