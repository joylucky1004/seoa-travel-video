import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test runs in mock mode with its own data dir; real .env values are ignored."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("REFERENCES_DIR", str(tmp_path / "refs"))
    monkeypatch.setenv("HIGGSFIELD_MODE", "mock")
    monkeypatch.setenv("ALLOW_PAID_API_CALLS", "false")
    monkeypatch.setenv("APP_PASSWORD", "")
    for var in ("HF_API_KEY", "HF_KEY", "HIGGSFIELD_API_KEY", "HF_API_KEY_ID", "HF_API_KEY_SECRET",
                "HF_API_SECRET", "HIGGSFIELD_API_SECRET"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
