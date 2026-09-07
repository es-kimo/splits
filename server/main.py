from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import AsyncIterator, Literal, cast

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from .deps import ApiConfig, PinnedRun, RatingSnapshot, ReadOnlyRatingRepository


class Provenance(BaseModel):
    run_id: str
    algo_version: str
    mode: Literal["filtered"]
    calibrator: str


class Freshness(BaseModel):
    data_as_of: date
    stale_days: int


class RatingValue(BaseModel):
    mu: float
    sigma: float
    z_vs_age: float | None


class RatingResponse(BaseModel):
    value: RatingValue | None
    provenance: Provenance
    confidence: Literal["high", "medium", "low"]
    n_games: int
    freshness: Freshness
    message: str | None = None


class TrajectoryPoint(BaseModel):
    as_of: date
    value: RatingValue | None
    confidence: Literal["high", "medium", "low"]
    n_games: int
    message: str | None = None


class TrajectoryResponse(BaseModel):
    points: list[TrajectoryPoint]
    provenance: Provenance
    freshness: Freshness


class CurrentRunResponse(BaseModel):
    run_id: str
    algo_version: str
    created_at: str
    calibrator: str
    freshness: Freshness


def create_app(config: ApiConfig | None = None, *, today: date | None = None) -> FastAPI:
    selected_config = config or ApiConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.repository = ReadOnlyRatingRepository(selected_config, today=today)
        yield

    app = FastAPI(title="splits query API", version="1.0.0", lifespan=lifespan)

    @app.get("/v1/health")
    def health(request: Request) -> dict[str, str]:
        repository = _repository(request)
        return {"status": "ok", "run_id": repository.pinned_run.run_id}

    @app.get("/v1/runs/current", response_model=CurrentRunResponse)
    def current_run(request: Request) -> CurrentRunResponse:
        repository = _repository(request)
        run = repository.pinned_run
        return CurrentRunResponse(
            run_id=run.run_id,
            algo_version=run.algo_version,
            created_at=run.created_at,
            calibrator=run.calibrator,
            freshness=_freshness(repository),
        )

    @app.get("/v1/athletes/{opaque_id}/rating", response_model=RatingResponse)
    def athlete_rating(
        opaque_id: str,
        request: Request,
        as_of: date,
        mode: Literal["filtered"] = "filtered",
    ) -> RatingResponse:
        repository = _repository(request)
        athlete_id = _athlete_id_or_404(repository, opaque_id)
        snapshot = repository.rating_as_of(athlete_id, as_of)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="No rating is available for this date.")
        return _rating_response(repository.pinned_run, repository, snapshot, mode)

    @app.get("/v1/athletes/{opaque_id}/trajectory", response_model=TrajectoryResponse)
    def athlete_trajectory(
        opaque_id: str,
        request: Request,
        mode: Literal["filtered"] = "filtered",
    ) -> TrajectoryResponse:
        repository = _repository(request)
        athlete_id = _athlete_id_or_404(repository, opaque_id)
        points = [
            _trajectory_point(snapshot)
            for snapshot in repository.filtered_trajectory(athlete_id)
        ]
        if not points:
            raise HTTPException(status_code=404, detail="No rating trajectory is available.")
        return TrajectoryResponse(
            points=points,
            provenance=_provenance(repository.pinned_run, mode),
            freshness=_freshness(repository),
        )

    return app


def _repository(request: Request) -> ReadOnlyRatingRepository:
    return cast(ReadOnlyRatingRepository, request.app.state.repository)


def _athlete_id_or_404(repository: ReadOnlyRatingRepository, opaque_id: str) -> str:
    athlete_id = repository.athlete_id_for(opaque_id)
    if athlete_id is None:
        raise HTTPException(status_code=404, detail="Athlete not found.")
    return athlete_id


def _rating_response(
    run: PinnedRun,
    repository: ReadOnlyRatingRepository,
    snapshot: RatingSnapshot,
    mode: Literal["filtered"],
) -> RatingResponse:
    confidence = _confidence(snapshot.n_games)
    return RatingResponse(
        value=_value(snapshot) if confidence != "low" else None,
        provenance=_provenance(run, mode),
        confidence=confidence,
        n_games=snapshot.n_games,
        freshness=_freshness(repository),
        message=_low_confidence_message(snapshot.n_games) if confidence == "low" else None,
    )


def _trajectory_point(snapshot: RatingSnapshot) -> TrajectoryPoint:
    confidence = _confidence(snapshot.n_games)
    return TrajectoryPoint(
        as_of=snapshot.valid_date,
        value=_value(snapshot) if confidence != "low" else None,
        confidence=confidence,
        n_games=snapshot.n_games,
        message=_low_confidence_message(snapshot.n_games) if confidence == "low" else None,
    )


def _value(snapshot: RatingSnapshot) -> RatingValue:
    return RatingValue(mu=snapshot.mu, sigma=snapshot.sigma, z_vs_age=snapshot.z_vs_age)


def _confidence(n_games: int) -> Literal["high", "medium", "low"]:
    return "low" if n_games <= 5 else "high"


def _low_confidence_message(n_games: int) -> str:
    return f"아직 판단하기 이릅니다 (경기 {n_games}회)"


def _provenance(run: PinnedRun, mode: Literal["filtered"]) -> Provenance:
    return Provenance(
        run_id=run.run_id,
        algo_version=run.algo_version,
        mode=mode,
        calibrator=run.calibrator,
    )


def _freshness(repository: ReadOnlyRatingRepository) -> Freshness:
    return Freshness(data_as_of=repository.pinned_run.data_as_of, stale_days=repository.stale_days())


app = create_app()
