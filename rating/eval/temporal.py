from rating.query.temporal import FilteredRating


def backtest_rating_diagnostics(rating: FilteredRating) -> tuple[float, float]:
    """Return the only temporal rating shape accepted by backtest diagnostics."""

    return rating.mu, rating.sigma
