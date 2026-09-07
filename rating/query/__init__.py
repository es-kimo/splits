"""Temporal rating query APIs."""

from typing import TYPE_CHECKING

__all__ = ["FilteredRating", "SmoothedRating", "rating_as_of", "rating_retrospective"]

if TYPE_CHECKING:
    from .temporal import FilteredRating, SmoothedRating, rating_as_of, rating_retrospective


def __getattr__(name: str) -> object:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from . import temporal

    return getattr(temporal, name)
