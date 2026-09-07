from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from typing import AsyncIterator, Literal, cast

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .cache import ExpiringLruCache, FixedWindowRateLimiter
from .deps import ApiConfig, ApiDataError, PinnedRun, RatingSnapshot, ReadOnlyRatingRepository
from .simulate import ExplicitRating, HeatResult, HeatSpec, SimBudget, simulate_heat as run_heat_simulation, simulation_cache_key


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


class HeatSimulationRequest(BaseModel):
    athletes: list[str] = Field(min_length=2, max_length=32)
    advance_count: int = Field(ge=1)
    penalty_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    seed: int


class HeatProbability(BaseModel):
    opaque_id: str
    advance_prob: float
    ci: tuple[float, float]


class SimulationProvenance(BaseModel):
    run_id: str
    algo_version: str
    beta: float
    penalty_source: Literal["request", "ledger"]
    calibrated: bool = False


class HeatSimulationResponse(BaseModel):
    probabilities: list[HeatProbability]
    iterations: int
    converged: bool
    cache_hit: bool
    provenance: SimulationProvenance
    freshness: Freshness


_SIMULATION_BUDGET = SimBudget()


def create_app(config: ApiConfig | None = None, *, today: date | None = None) -> FastAPI:
    selected_config = config or ApiConfig.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.repository = ReadOnlyRatingRepository(selected_config, today=today)
        app.state.simulation_cache = ExpiringLruCache[HeatResult](max_entries=256, ttl_seconds=3600)
        app.state.simulation_rate_limiter = FixedWindowRateLimiter(limit=20, window_seconds=60)
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

    @app.post("/v1/simulate/heat", response_model=HeatSimulationResponse)
    def simulate_heat_endpoint(payload: HeatSimulationRequest, request: Request) -> HeatSimulationResponse:
        limiter = cast(FixedWindowRateLimiter, request.app.state.simulation_rate_limiter)
        client_host = request.client.host if request.client is not None else "unknown"
        allowed, retry_after = limiter.allow(client_host)
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Simulation request limit exceeded.",
                headers={"Retry-After": str(retry_after)},
            )

        repository = _repository(request)
        try:
            beta = repository.simulation_beta()
            penalty_rate = payload.penalty_rate
            penalty_source: Literal["request", "ledger"] = "request"
            if penalty_rate is None:
                penalty_rate = repository.default_penalty_rate()
                penalty_source = "ledger"
            resolved = _resolve_simulation_athletes(repository, payload.athletes)
            spec, opaque_ids = _canonical_simulation_spec(
                resolved,
                advance_count=payload.advance_count,
                penalty_rate=penalty_rate,
                seed=payload.seed,
            )
            key = simulation_cache_key(spec, beta=beta, run_id=repository.pinned_run.run_id)
            cache = cast(ExpiringLruCache[HeatResult], request.app.state.simulation_cache)
            lookup = cache.get_or_compute(key, lambda: run_heat_simulation(spec, _SIMULATION_BUDGET, beta=beta))
        except ApiDataError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error

        return HeatSimulationResponse(
            probabilities=[
                HeatProbability(
                    opaque_id=opaque_id,
                    advance_prob=estimate.advance_prob,
                    ci=(estimate.ci_low, estimate.ci_high),
                )
                for opaque_id, estimate in zip(opaque_ids, lookup.value.probabilities)
            ],
            iterations=lookup.value.iterations,
            converged=lookup.value.converged,
            cache_hit=lookup.hit,
            provenance=SimulationProvenance(
                run_id=repository.pinned_run.run_id,
                algo_version=repository.pinned_run.algo_version,
                beta=beta,
                penalty_source=penalty_source,
            ),
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


def _resolve_simulation_athletes(
    repository: ReadOnlyRatingRepository, opaque_ids: list[str]
) -> list[tuple[str, RatingSnapshot]]:
    if len(set(opaque_ids)) != len(opaque_ids):
        raise ValueError("athlete opaque IDs must be unique")
    resolved: list[tuple[str, RatingSnapshot]] = []
    for opaque_id in opaque_ids:
        athlete_id = _athlete_id_or_404(repository, opaque_id)
        snapshot = repository.rating_as_of(athlete_id, repository.pinned_run.data_as_of)
        if snapshot is None:
            raise ValueError("A selected athlete has no current rating.")
        if _confidence(snapshot.n_games) == "low":
            raise ValueError("A selected athlete does not yet have enough races for simulation.")
        resolved.append((opaque_id, snapshot))
    return resolved


def _canonical_simulation_spec(
    resolved: list[tuple[str, RatingSnapshot]],
    *,
    advance_count: int,
    penalty_rate: float,
    seed: int,
) -> tuple[HeatSpec, list[str]]:
    ordered = sorted(resolved, key=lambda item: (item[1].mu, item[1].sigma, item[0]))
    opaque_ids = [opaque_id for opaque_id, _snapshot in ordered]
    ratings = [
        ExplicitRating(athlete_id=f"slot-{index:02d}", mu=snapshot.mu, sigma=snapshot.sigma)
        for index, (_opaque_id, snapshot) in enumerate(ordered)
    ]
    return (
        HeatSpec(
            athletes=ratings,
            advance_count=advance_count,
            penalty_rate=penalty_rate,
            seed=seed,
        ),
        opaque_ids,
    )


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
