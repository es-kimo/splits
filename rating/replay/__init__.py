"""Deterministic replay orchestration and content-addressed checkpoints."""

from typing import TYPE_CHECKING

from .checkpoint import Checkpoint, CheckpointError, checkpoint_id, find_nearest, load, save

if TYPE_CHECKING:
    from .orchestrator import ReplayParams, ReplayResult, replay

__all__ = [
    "Checkpoint",
    "CheckpointError",
    "ReplayParams",
    "ReplayResult",
    "checkpoint_id",
    "find_nearest",
    "load",
    "replay",
    "save",
]


def __getattr__(name: str):
    if name in {"ReplayParams", "ReplayResult", "replay"}:
        from . import orchestrator

        return getattr(orchestrator, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
