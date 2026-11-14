"""Pydantic models shared by the API, pipeline and services."""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field


class Scene(BaseModel):
    visual_prompt: str = Field(..., min_length=3, max_length=1500,
                               description="What happens in this shot (English or Korean).")
    subtitle_ko: str = Field("", max_length=120, description="Korean subtitle burned into this scene.")
    duration_seconds: float = Field(5.0, ge=2.0, le=10.0)
    camera: str = Field("", max_length=200, description="Optional camera move, e.g. 'slow dolly in'.")


class ReelRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)
    location: str = Field("", max_length=100, description="e.g. 'Jeju Aewol cafe street'")
    style_notes: str = Field("", max_length=500)
    extra_consistency_notes: str = Field("", max_length=1000,
                                         description="Per-reel additions to SEOA's consistency rules.")
    scenes: list[Scene] = Field(..., min_length=1, max_length=12)
    add_cta: bool = True
    # Free run with placeholder clips even when the server is in live mode.
    dry_run: bool = False
    # Generate only these scenes (0-based). None = all. Live jobs are capped by MAX_CLIPS_PER_JOB.
    scene_indices: list[int] | None = None


class JobStatus(str, Enum):
    queued = "queued"
    estimating = "estimating"            # live: uploading references + cost estimate (free)
    awaiting_approval = "awaiting_approval"  # live: waiting for the user to approve paid generation
    generating = "generating"
    editing = "editing"
    done = "done"
    failed = "failed"
    canceled = "canceled"


class SceneState(BaseModel):
    index: int
    status: str = "pending"  # pending | submitted | queued | in_progress | completed | failed | nsfw | canceled | timeout
    request_id: str | None = None
    idempotency_key: str | None = None
    estimate_usd: float | None = None
    error: str = ""
    clip_ready: bool = False
    reused: bool = False          # clip taken from the cache, no credits spent
    cache_key: str | None = None
    generated_seconds: int | None = None


class ClipResult(BaseModel):
    scene_index: int
    prompt: str
    path: str
    provider: str
    mock: bool


class Job(BaseModel):
    id: str
    request: ReelRequest
    status: JobStatus = JobStatus.queued
    mode: str = "mock"
    model: str = "mock"           # fixed at creation; approval binds to this model
    resolution: str | None = None
    progress: float = 0.0
    message: str = ""
    scenes: list[SceneState] = []
    estimate_total_usd: float | None = None
    clips: list[ClipResult] = []
    output_path: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
