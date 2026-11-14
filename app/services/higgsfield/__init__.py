from app.config import Settings

from .base import GenerationRequest, GenerationResult, VideoGenerator
from .live import LiveHiggsfieldClient, PaidCallsDisabledError
from .mock import MockHiggsfieldClient


def get_generator(settings: Settings) -> VideoGenerator:
    """Mock unless both safety switches are explicitly turned on."""
    if settings.is_live:
        return LiveHiggsfieldClient(settings)
    return MockHiggsfieldClient()


__all__ = ["GenerationRequest", "GenerationResult", "VideoGenerator", "LiveHiggsfieldClient",
           "MockHiggsfieldClient", "PaidCallsDisabledError", "get_generator"]
