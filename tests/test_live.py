"""Live Higgsfield client, credit-saving rules and approval flow.

Everything runs against a fake HTTP server — no real Higgsfield calls are made.
"""
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models import ReelRequest, Scene
from app.services import character, pipeline
from app.services.higgsfield import (GenerationError, GenerationRequest, LiveHiggsfieldClient,
                                     MockHiggsfieldClient, PaidCallsDisabledError)
from app.services.higgsfield.models import (DEFAULT_MODEL, PROFILES, build_arguments, get_profile,
                                            resolve_resolution)

KEY = "kid_123:sec_456"
PRICES = {m: 0.05 * (i + 1) for i, m in enumerate(PROFILES)}  # fake per-model estimates


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

    def __init__(self, final_status="completed", polls_before_done=2, submit_status=200):
        self.calls: list[httpx.Request] = []
        self.final_status = final_status
        self.polls_before_done = polls_before_done
        self.submit_status = submit_status
        self.polls = 0
        self.uploads = 0
        self.submitted: list[tuple[str, dict]] = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        url, path = str(req.url), req.url.path
        if req.url.host == "api.higgsfield.ai":
            if req.headers.get("authorization") != f"Key {KEY}":
                return httpx.Response(401, json={"detail": "Invalid credentials"})
            if path == "/files/generate-upload-url":
                self.uploads += 1
                ct = json.loads(req.content)["content_type"]
                return httpx.Response(200, json={
                    "public_url": f"https://cdn.test/in/{self.uploads}.jpg",
                    "upload_url": "https://storage.test/put", "content_type": ct,
                    "upload_headers": {"Content-Type": ct, "x-amz-tagging": "retention=temporary"}})
            if path.startswith("/estimate/"):
                return httpx.Response(200, json={"usd": str(PRICES[path[len("/estimate/"):]])})
            if path.lstrip("/") in PROFILES:
                if self.submit_status != 200:
                    self.submitted.append((path.lstrip("/"), {}))
                    return httpx.Response(self.submit_status, json={"detail": "server error"})
                self.submitted.append((path.lstrip("/"), json.loads(req.content)))
                rid = f"00000000-0000-0000-0000-{len(self.submitted):012d}"
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


def _client(fake, settings, **kw):
    return LiveHiggsfieldClient(settings, transport=httpx.MockTransport(fake), sleep=lambda s: None, **kw)


def _req(model=DEFAULT_MODEL, urls=("https://cdn.test/a.jpg",), duration=None, resolution=None, neg=""):
    prof = get_profile(model)
    return GenerationRequest(model=model, prompt="SEOA at the beach\nCamera: slow dolly in",
                             negative_prompt=neg, reference_urls=list(urls),
                             duration=duration or prof.min_duration,
                             resolution=resolution or prof.cheapest_resolution)


# --- credentials / switches --------------------------------------------------
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


def test_estimate_only_client_cannot_submit(monkeypatch):
    monkeypatch.setenv("HF_API_KEY", KEY)  # mock mode
    get_settings.cache_clear()
    fake = FakeHiggsfield()
    c = _client(fake, get_settings(), estimate_only=True)
    assert c.estimate_usd(_req()) == pytest.approx(PRICES[DEFAULT_MODEL])
    with pytest.raises(PaidCallsDisabledError):
        c.submit(_req(), "k")
    assert fake.submitted == []


# --- cheapest settings per documented schema -------------------------------
def test_default_model_uses_cheapest_documented_settings(live_env):
    body = _client(FakeHiggsfield(), live_env).build_arguments(_req(neg="extra fingers"))
    assert set(body) == {"prompt", "image_urls", "duration", "aspect_ratio", "resolution"}
    assert body["duration"] == 1 and body["resolution"] == "480p" and body["aspect_ratio"] == "9:16"
    assert "slow dolly in" in body["prompt"] and "Avoid: extra fingers" in body["prompt"]


@pytest.mark.parametrize("model", list(PROFILES))
def test_every_profile_is_low_cost(model):
    p = get_profile(model)
    body = build_arguments(p, prompt="x", negative_prompt="n", reference_urls=["u"] * 20,
                           duration=p.min_duration, resolution=p.cheapest_resolution)
    assert body["aspect_ratio"] == "9:16" and body["duration"] == p.min_duration
    assert len(body["image_urls"]) <= p.max_reference_images
    assert body.get("generate_audio", False) is False and body.get("sound", "off") == "off"
    res = body.get("resolution")
    assert res in (None, "360p", "480p", "540p", "720p")


def test_resolution_override_above_720p_is_ignored():
    p = get_profile("bytedance/seedance-2.0/reference-to-video")
    res, warning = resolve_resolution(p, "1080p")
    assert res == "480p" and warning
    assert resolve_resolution(p, "720p") == ("720p", "")


def test_unknown_model_is_refused(live_env):
    with pytest.raises(ValueError):
        _client(FakeHiggsfield(), live_env).build_arguments(
            GenerationRequest("veo/expensive", "p", "", ["u"], 8, "1080p"))


# --- API flow ----------------------------------------------------------------
def test_upload_cache_estimate_submit_poll_download(live_env, tmp_path):
    fake = FakeHiggsfield()
    c = _client(fake, live_env)
    img = tmp_path / "seoa.png"
    img.write_bytes(b"\x89PNG fake")
    urls = c.prepare_references([img])
    assert c.prepare_references([img]) == urls and fake.uploads == 1  # reused, not re-uploaded
    req = _req(urls=urls)
    assert c.estimate_usd(req) == pytest.approx(PRICES[DEFAULT_MODEL])
    rid = c.submit(req, "idem-1")
    submit_call = [r for r in fake.calls if r.url.path == f"/{DEFAULT_MODEL}"][0]
    assert submit_call.headers["idempotency-key"] == "idem-1"
    seen = []
    out = tmp_path / "clip.mp4"
    res = c.wait(rid, out, lambda st, _rid: seen.append(st))
    assert out.read_bytes() == b"FAKE-MP4" and res.mock is False
    assert seen == ["in_progress", "completed"]


def test_submit_is_never_retried_automatically(live_env):
    fake = FakeHiggsfield(submit_status=500)
    with pytest.raises(Exception):
        _client(fake, live_env).submit(_req(), "idem")
    assert len(fake.submitted) == 1


def test_nsfw_is_reported(live_env, tmp_path):
    c = _client(FakeHiggsfield(final_status="nsfw", polls_before_done=0), live_env)
    with pytest.raises(GenerationError) as exc:
        c.wait("00000000-0000-0000-0000-000000000001", tmp_path / "x.mp4")
    assert exc.value.status == "nsfw"


def test_wrong_credentials_surface_401(monkeypatch, live_env):
    monkeypatch.setenv("HF_API_KEY", "bad:key")
    get_settings.cache_clear()
    with pytest.raises(Exception) as exc:
        _client(FakeHiggsfield(), get_settings()).estimate_usd(_req())
    assert "401" in str(exc.value)


# --- pipeline rules ------------------------------------------------------------
class _FakeLiveGenerator(MockHiggsfieldClient):
    """Mock rendering, but behaves like the live client toward the pipeline."""
    mock = False
    name = "fake-live"

    def __init__(self, price=0.3, fail=False):
        super().__init__()
        self.submits, self.estimates, self.price, self.fail = 0, 0, price, fail
        self.models = []

    def prepare_references(self, paths):
        assert paths, "references required"
        return [f"https://cdn.test/{p.name}" for p in paths]

    def estimate_usd(self, req):
        self.estimates += 1
        return self.price

    def submit(self, req, key):
        self.submits += 1
        self.models.append(req.model)
        return super().submit(req, key)

    def wait(self, request_id, output_path, on_status=None):
        if self.fail:
            self._pending.pop(request_id)
            raise GenerationError("생성에 실패했습니다 (과금되지 않음).", "failed", request_id)
        return super().wait(request_id, output_path, on_status)


def _reel(n=2, **kw):
    scenes = [Scene(visual_prompt=f"SEOA scene {i}", subtitle_ko=f"자막 {i}", duration_seconds=2) for i in range(n)]
    return ReelRequest(title="t", scenes=scenes, **kw)


def _run(job):
    pipeline.next_step(job)(job.id)
    return pipeline.load_job(job.id)


@pytest.fixture
def gen(live_env, monkeypatch):
    character.save_reference("seoa.jpg", b"img")
    g = _FakeLiveGenerator()
    monkeypatch.setattr(pipeline, "generator_factory", lambda s: g)
    return g


def test_live_job_limited_to_one_scene(gen):
    with pytest.raises(pipeline.JobStateError):
        pipeline.create_job(_reel(2))
    job = pipeline.create_job(_reel(3, scene_indices=[1]))
    assert len(job.request.scenes) == 1 and job.request.scenes[0].visual_prompt == "SEOA scene 1"


def test_approval_required_and_model_fixed(gen):
    job = _run(pipeline.create_job(_reel(1)))
    assert job.status == "awaiting_approval" and job.estimate_total_usd == pytest.approx(0.3)
    assert gen.submits == 0  # nothing paid before approval
    pipeline.approve(job.id)
    pipeline.run_generation(job.id)
    job = pipeline.load_job(job.id)
    assert job.status == "done", job.message
    assert gen.submits == 1 and gen.models == [DEFAULT_MODEL] and job.model == DEFAULT_MODEL
    assert job.scenes[0].generated_seconds == 1


def test_identical_scene_is_reused_without_cost(gen):
    job = _run(pipeline.create_job(_reel(1)))
    pipeline.approve(job.id)
    pipeline.run_generation(job.id)
    estimates = gen.estimates
    job2 = _run(pipeline.create_job(_reel(1)))
    assert job2.status == "done", job2.message
    assert job2.scenes[0].reused and gen.submits == 1 and gen.estimates == estimates


def test_estimate_above_cap_is_blocked(gen, monkeypatch):
    monkeypatch.setenv("MAX_USD_PER_JOB", "0.10")
    get_settings.cache_clear()
    job = _run(pipeline.create_job(_reel(1)))
    assert job.status == "failed" and "한도" in job.message
    with pytest.raises(pipeline.JobStateError):
        pipeline.approve(job.id)
    assert gen.submits == 0


def test_failure_is_not_retried_and_retry_needs_new_approval(gen):
    gen.fail = True
    job = _run(pipeline.create_job(_reel(1)))
    pipeline.approve(job.id)
    pipeline.run_generation(job.id)
    job = pipeline.load_job(job.id)
    assert job.status == "failed" and gen.submits == 1  # no automatic retry
    gen.fail = False
    job = pipeline.prepare_retry(job.id)
    job = _run(job)
    assert job.status == "awaiting_approval" and gen.submits == 1


def test_retry_keeps_idempotency_key_when_submit_was_unacknowledged(gen):
    job = pipeline.create_job(_reel(1))
    job.status = pipeline.JobStatus.failed
    job.scenes[0].status, job.scenes[0].idempotency_key = "failed", "keep-me"
    pipeline.save_job(job)
    assert pipeline.prepare_retry(job.id).scenes[0].idempotency_key == "keep-me"


def test_dry_run_on_live_server_is_free(gen):
    job = _run(pipeline.create_job(_reel(3, dry_run=True)))
    assert job.mode == "mock" and job.status == "done", job.message
    assert gen.submits == 0 and gen.estimates == 0


def test_preview_makes_no_calls(gen):
    p = pipeline.preview(_reel(2, scene_indices=[0]))
    assert p["settings"]["model"] == DEFAULT_MODEL and p["settings"]["resolution"] == "480p"
    assert [s["selected"] for s in p["scenes"]] == [True, False]
    assert p["scenes"][0]["request_body"]["duration"] == 1
    assert gen.submits == 0 and gen.estimates == 0


# --- HTTP API ---------------------------------------------------------------
def _app():
    return TestClient(__import__("app.main", fromlist=["app"]).app)


def test_api_requires_password_in_live_and_hides_key(live_env, monkeypatch):
    monkeypatch.setattr(pipeline, "generator_factory", lambda s: _FakeLiveGenerator())
    client = _app()
    assert client.get("/api/status").status_code == 401
    r = client.get("/api/status", auth=("seoa", "pw"))
    assert r.status_code == 200 and r.json()["mode"] == "live"
    assert r.json()["generation"]["resolution"] == "480p"
    assert "kid_123" not in r.text and "sec_456" not in r.text
    monkeypatch.setenv("APP_PASSWORD", "")
    get_settings.cache_clear()
    r = client.post("/api/jobs", json={"title": "t", "scenes": [{"visual_prompt": "abc"}]})
    assert r.status_code == 403


def test_compare_models_uses_only_free_estimates(live_env, monkeypatch):
    import app.main as main
    character.save_reference("seoa.png", b"img")
    fake = FakeHiggsfield()
    monkeypatch.setattr(main, "LiveHiggsfieldClient",
                        lambda s, estimate_only: _client(fake, s, estimate_only=estimate_only))
    r = _app().post("/api/models/compare", auth=("seoa", "pw"))
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["cheapest"] == min(PRICES, key=PRICES.get)
    assert fake.submitted == []  # no generation
    assert all(c.url.path.startswith(("/estimate/", "/files/")) for c in fake.calls
               if c.url.host == "api.higgsfield.ai")
    # selecting is manual and validated
    assert _app().post("/api/models/select", auth=("seoa", "pw"),
                       json={"model": "veo/expensive"}).status_code == 400
    r = _app().post("/api/models/select", auth=("seoa", "pw"), json={"model": "alibaba/wan-3.0/reference-to-video"})
    assert r.json()["settings"]["model"] == "alibaba/wan-3.0/reference-to-video"
