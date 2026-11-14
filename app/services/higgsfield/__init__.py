from app.config import Settings

from .base import (GenerationError, GenerationRequest, GenerationResult, StatusCallback,
                   VideoGenerator)
from .live import HiggsfieldAPIError, LiveHiggsfieldClient, PaidCallsDisabledError
from .mock import MockHiggsfieldClient


def get_generator(settings: Settings) -> VideoGenerator:
    """Mock unless both safety switches are explicitly turned on."""
    if settings.is_live:
        return LiveHiggsfieldClient(settings)
    return MockHiggsfieldClient()


__all__ = ["GenerationError", "GenerationRequest", "GenerationResult", "HiggsfieldAPIError",
           "LiveHiggsfieldClient", "MockHiggsfieldClient", "PaidCallsDisabledError",
           "StatusCallback", "VideoGenerator", "get_generator"]
