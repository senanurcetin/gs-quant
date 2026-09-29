"""
Copyright 2026 Senanur Çetin.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
"""

import datetime as dt
import math
from dataclasses import asdict
from typing import Annotated, Literal, Optional

import numpy as np
import pandas as pd
from fastmcp.exceptions import ToolError

from gs_quant.data import Dataset
from gs_quant.errors import MqError
from gs_quant.mcp.dependencies import depends_user_session
from gs_quant.mcp.tools.registry import mcp_tool
from gs_quant.session import GsSession
from gs_quant.timeseries.helper import Window
from gs_quant.timeseries.risk_metrics import (
    VaRMethod,
    infer_periods_per_year,
    information_ratio,
    risk_summary,
    tracking_error,
    value_at_risk,
    var_backtest,
)

# Analytics that need no Marquee data: an agent supplies the numbers. Bounded so that a single call cannot tie up the
# server: the rolling calculations cost O(observations x window).
MAX_OBSERVATIONS = 20_000
DEFAULT_PERIODS_PER_YEAR = 252

_CONVENTIONS = (
    "Results are fractions (0.02 is 2%). Losses are negative, so a 95% value at risk of -0.02 means a one period "
    "return worse than -2% is expected on 5% of periods."
)


def _series(values: list[float], dates: Optional[list[dt.date]], name: str) -> pd.Series:
    if not values:
        raise ToolError(f"{name} must not be empty")
    if len(values) > MAX_OBSERVATIONS:
        raise ToolError(f"{name} has {len(values)} observations, the maximum is {MAX_OBSERVATIONS}")
    array = np.asarray(values, dtype=float)
    if not np.isfinite(array).all():
        raise ToolError(f"{name} must only contain finite numbers")
    if dates is None:
        return pd.Series(array)
    if len(dates) != len(values):
        raise ToolError(f"dates has {len(dates)} entries but {name} has {len(values)}")
    index = pd.DatetimeIndex(pd.to_datetime(dates))
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ToolError("dates must be strictly increasing, with no duplicates")
    return pd.Series(array, index=index)


def _resolve_periods(explicit: Optional[int], dated: bool, assumptions: list[str]) -> Optional[int]:
    """Explicit value if given, otherwise inferred from dates, otherwise a stated daily default"""
    if explicit is not None:
        return explicit
    if dated:
        assumptions.append("periods_per_year was inferred from the spacing of the dates")
        return None
    assumptions.append(
        f"No dates were given, so periods_per_year was assumed to be {DEFAULT_PERIODS_PER_YEAR} (daily returns)"
    )
    return DEFAULT_PERIODS_PER_YEAR


def _summary(returns: pd.Series, confidence: float, mar: float, periods_per_year: Optional[int]) -> dict:
    try:
        return risk_summary(returns, confidence, mar, periods_per_year).to_dict()
    except (MqError, ValueError) as e:
        raise ToolError(str(e)) from e


@mcp_tool(tags={"analytics"})
def risk_summary_from_returns(
    returns: Annotated[list[float], "Simple periodic returns as fractions, oldest first, e.g. 0.012 for +1.2%"],
    dates: Annotated[
        Optional[list[dt.date]],
        "Optional dates (YYYY-MM-DD), one per return, strictly increasing. Used to infer the data frequency.",
    ] = None,
    confidence: Annotated[float, "Confidence level for value at risk and expected shortfall, e.g. 0.95"] = 0.95,
    minimum_acceptable_return: Annotated[
        float, "Per period return below which a result counts as a shortfall, for Sortino and Omega"
    ] = 0.0,
    periods_per_year: Annotated[
        Optional[int], "Periods per year (252 daily, 52 weekly, 12 monthly). Inferred from dates when omitted."
    ] = None,
) -> dict:
    """
    Computes headline risk statistics for a series of returns supplied by the caller: annualized return and
    volatility, skewness, excess kurtosis, value at risk (historical, parametric and Cornish-Fisher), expected
    shortfall, downside deviation, Sortino, Omega and Calmar ratios, maximum drawdown and ulcer index.
    Needs no market data access. Statistics that are undefined for the data, such as a Sortino ratio when no return
    is below the target, are null.
    """
    assumptions: list[str] = []
    series = _series(returns, dates, "returns")
    factor = _resolve_periods(periods_per_year, dates is not None, assumptions)
    return {
        "summary": _summary(series, confidence, minimum_acceptable_return, factor),
        "conventions": _CONVENTIONS,
        "assumptions": assumptions,
    }


@mcp_tool(tags={"analytics"})
def backtest_value_at_risk(
    returns: Annotated[list[float], "Simple periodic returns as fractions, oldest first"],
    dates: Annotated[
        Optional[list[dt.date]], "Optional dates (YYYY-MM-DD), one per return, strictly increasing"
    ] = None,
    confidence: Annotated[float, "Confidence level of the value at risk model, e.g. 0.99"] = 0.99,
    method: Annotated[
        Literal["historical", "parametric", "cornish_fisher"], "How each day's value at risk is estimated"
    ] = "parametric",
    window: Annotated[int, "Number of past periods used to estimate each forecast"] = 250,
    significance: Annotated[float, "Significance level of the test, e.g. 0.05"] = 0.05,
) -> dict:
    """
    Checks whether a rolling value at risk model is well calibrated, using the Kupiec proportion of failures test.
    Each period is forecast from the previous `window` returns only (no look-ahead) and compared with the return that
    followed. Too many exceedances mean the model understates risk, too few mean it overstates it. `reject` is true if
    the observed exceedance rate is statistically inconsistent with 1 - confidence.
    """
    series = _series(returns, dates, "returns")
    if window < 30:
        raise ToolError("window must be at least 30 periods")
    if len(series) <= window + 1:
        raise ToolError(f"Need more than window + 1 = {window + 1} returns to backtest, got {len(series)}")
    try:
        forecast = value_at_risk(series, confidence, VaRMethod(method), w=Window(window, window - 1)).shift(1)
        result = var_backtest(series, forecast, confidence, significance)
    except (MqError, ValueError) as e:
        raise ToolError(str(e)) from e
    return {
        "result": {**asdict(result), "method": method, "window": window},
        "conventions": _CONVENTIONS,
        "interpretation": (
            "Model rejected: the number of exceedances is unlikely if it were calibrated"
            if result.reject
            else "Model not rejected: the number of exceedances is consistent with the confidence level"
        ),
    }


@mcp_tool(tags={"analytics"})
def compare_with_benchmark(
    returns: Annotated[list[float], "Simple periodic portfolio returns as fractions, oldest first"],
    benchmark_returns: Annotated[list[float], "Simple periodic benchmark returns, same length and dates as returns"],
    dates: Annotated[
        Optional[list[dt.date]], "Optional dates (YYYY-MM-DD), one per return, strictly increasing"
    ] = None,
    periods_per_year: Annotated[
        Optional[int], "Periods per year (252 daily, 52 weekly, 12 monthly). Inferred from dates when omitted."
    ] = None,
) -> dict:
    """
    Compares a portfolio with a benchmark over the same periods: annualized tracking error, information ratio,
    annualized active return, beta and correlation. Needs no market data access.
    """
    assumptions: list[str] = []
    portfolio = _series(returns, dates, "returns")
    benchmark = _series(benchmark_returns, dates, "benchmark_returns")
    if len(portfolio) != len(benchmark):
        raise ToolError(f"returns has {len(portfolio)} entries but benchmark_returns has {len(benchmark)}")
    if len(portfolio) < 3:
        raise ToolError("At least three observations are required")
    factor = _resolve_periods(periods_per_year, dates is not None, assumptions)
    whole = Window(len(portfolio), len(portfolio) - 1)
    try:
        te = tracking_error(portfolio, benchmark, whole, factor).iloc[-1]
        ir = information_ratio(portfolio, benchmark, whole, factor).iloc[-1]
        periods = int(infer_periods_per_year(portfolio, factor))
    except (MqError, ValueError) as e:
        raise ToolError(str(e)) from e

    active = portfolio.to_numpy() - benchmark.to_numpy()
    benchmark_variance = benchmark.var(ddof=1)
    # Correlation and beta are undefined when either series is constant
    correlation = portfolio.corr(benchmark) if benchmark_variance > 0 and portfolio.var(ddof=1) > 0 else None
    return {
        "observations": len(portfolio),
        "periods_per_year": periods,
        "annualized_active_return": _finite_or_none(active.mean() * periods),
        "tracking_error": _finite_or_none(te),
        "information_ratio": _finite_or_none(ir),
        "beta": _finite_or_none(portfolio.cov(benchmark) / benchmark_variance) if benchmark_variance > 0 else None,
        "correlation": None if correlation is None else _finite_or_none(correlation),
        "conventions": _CONVENTIONS,
        "assumptions": assumptions,
    }


def _finite_or_none(value: float) -> Optional[float]:
    return float(value) if value is not None and math.isfinite(value) else None


@mcp_tool(tags={"analytics", "data"})
def asset_risk_summary(
    dataset_name: Annotated[str, "The name of the dataset to retrieve prices from, e.g. 'EDRVOL_PERCENT_STANDARD'"],
    bbid: Annotated[str, "The BBID (BloombergID) of the asset"],
    start_date: Annotated[dt.date, "Start of the period in YYYY-MM-DD format"],
    end_date: Annotated[dt.date, "End of the period in YYYY-MM-DD format"],
    value_column: Annotated[str, "The dataset column holding the price or level, e.g. 'closePrice'"] = "closePrice",
    confidence: Annotated[float, "Confidence level for value at risk and expected shortfall"] = 0.95,
    minimum_acceptable_return: Annotated[float, "Per period return target for Sortino and Omega"] = 0.0,
    user_session: GsSession = depends_user_session,
) -> dict:
    """
    Retrieves a daily price series for an asset from a Marquee dataset and computes headline risk statistics on its
    simple returns (see risk_summary_from_returns for the statistics). Use get_dataset_coverage to find the columns.
    """
    ds = Dataset(dataset_name)
    with user_session:
        frame = ds.get_data(start_date, end_date, bbid=bbid)
    if frame is None or frame.empty:
        raise ToolError(f"No data returned for {bbid} in {dataset_name} between {start_date} and {end_date}")
    if value_column not in frame.columns:
        raise ToolError(f"Column {value_column!r} not found, available columns: {sorted(map(str, frame.columns))}")

    prices = frame[value_column].dropna().sort_index()
    if prices.index.has_duplicates:
        raise ToolError("The dataset returned several rows per date; narrow the query (for example by bbid)")
    if (prices <= 0).any():
        raise ToolError(f"{value_column} contains non-positive values, so simple returns are not meaningful")
    returns = prices.pct_change().dropna()
    if not isinstance(returns.index, pd.DatetimeIndex):
        returns.index = pd.DatetimeIndex(pd.to_datetime(returns.index))
    return {
        "summary": _summary(returns, confidence, minimum_acceptable_return, None),
        "asset": {"bbid": bbid, "dataset": dataset_name, "column": value_column},
        "period": {"start": str(returns.index[0].date()), "end": str(returns.index[-1].date())},
        "conventions": _CONVENTIONS,
    }
