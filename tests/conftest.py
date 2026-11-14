import pytest

from app.config import get_settings


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Every test runs in mock mode with its own data dir; real .env values are ignored."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HIGGSFIELD_MODE", "mock")
    monkeypatch.setenv("ALLOW_PAID_API_CALLS", "false")
    monkeypatch.setenv("APP_PASSWORD", "")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
