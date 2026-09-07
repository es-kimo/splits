from datetime import date

from rating.eval.temporal import backtest_rating_diagnostics
from rating.query.temporal import FilteredRating, SmoothedRating

filtered = FilteredRating(mu=25.0, sigma=4.0, run_id="0123456789abcdef", as_of=date(2024, 1, 1))
smoothed = SmoothedRating(mu=25.0, sigma=3.0, run_id="0123456789abcdef", valid_date=date(2024, 1, 1))

backtest_rating_diagnostics(filtered)
backtest_rating_diagnostics(smoothed)  # type: ignore[arg-type]
