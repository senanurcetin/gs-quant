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
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

from gs_quant.errors import MqError
from gs_quant.timeseries.helper import Window
from gs_quant.timeseries.risk_metrics import (
    VaRMethod,
    drawdown,
    expected_shortfall,
    infer_periods_per_year,
    information_ratio,
    risk_summary,
    tracking_error,
    traffic_light_zone,
    value_at_risk,
    var_backtest,
    var_independence_test,
)

MAX_OBSERVATIONS = 5_000
HISTOGRAM_BINS = 40
HISTOGRAM_TAIL = 0.005  # the histogram spans the 0.5th to 99.5th percentile; a few outliers must not squash it
QQ_MAX_POINTS = 300
STRESS_HORIZONS = (1, 5, 20)  # periods
MAX_SCENARIOS = 5
SERIES_KEY = 'series'  # what a single series is called in a what-if scenario
DEFAULT_PERIODS_PER_YEAR = 252
MAX_HORIZON = 60  # periods
EWMA_DECAY = 0.94  # the RiskMetrics value for daily data
MIN_DECAY, MAX_DECAY = 0.80, 0.99
HORIZON_METHODS = ('square_root', 'filtered_simulation')
SIMULATION_PATHS = 10_000
SIMULATION_SEED = 7  # fixed: the same analysis gives the same figures
SIMULATION_BURN_IN = 20  # the first standardised returns rest on a volatility that has not settled
MIN_HORIZON_BLOCKS = 20  # fewer non-overlapping periods than this say nothing about a model
MIN_BENCHMARK_OBSERVATIONS = 30
MIN_BENCHMARK_VARIANCE = 1e-20


class AnalysisError(ValueError):
    """Input that cannot be analysed, with a message that is safe to show to the user"""


# ----------------------------------------------------------------------------------------------------------------------
# Synthetic data
# ----------------------------------------------------------------------------------------------------------------------

# GARCH(1,1) with Student-t innovations: volatility clusters and the tails are fat, like real market returns.
# daily_mu, daily_vol (long run), alpha, beta, degrees of freedom, and an optional (start, vol multiplier) shock
SCENARIOS: dict[str, dict] = {
    'calm': dict(
        title='Calm market',
        description='Low volatility, close to normally distributed returns',
        mu=0.0005,
        vol=0.006,
        alpha=0.03,
        beta=0.9,
        df=30,
    ),
    'volatile': dict(
        title='Volatile market',
        description='Volatility clustering and fat tails, as in equity index returns',
        mu=0.0004,
        vol=0.011,
        alpha=0.09,
        beta=0.89,
        df=5,
    ),
    'regime_shift': dict(
        title='Regime shift',
        description='A calm market that turns turbulent, so a trailing VaR model lags the change',
        mu=0.0003,
        vol=0.006,
        alpha=0.05,
        beta=0.9,
        df=6,
        shock=(0.75, 3.5),
    ),
}


def simulate_returns(scenario: str, n: int = 1000, seed: int = 7) -> pd.Series:
    """Simulate daily returns for one of the named scenarios, dated on business days ending on a fixed date"""
    if scenario not in SCENARIOS:
        raise AnalysisError(f'Unknown scenario {scenario!r}, choose from {sorted(SCENARIOS)}')
    if not 60 <= n <= MAX_OBSERVATIONS:
        raise AnalysisError(f'n must be between 60 and {MAX_OBSERVATIONS}')
    p = SCENARIOS[scenario]
    rng = np.random.default_rng(seed)
    # standardised Student-t innovations (unit variance)
    scale = math.sqrt((p['df'] - 2) / p['df'])
    shocks = rng.standard_t(p['df'], size=n) * scale
    omega = p['vol'] ** 2 * (1 - p['alpha'] - p['beta'])
    variance = p['vol'] ** 2
    returns = np.empty(n)
    for t in range(n):
        if 'shock' in p and t >= int(n * p['shock'][0]):
            variance = max(variance, (p['vol'] * p['shock'][1]) ** 2)
        returns[t] = p['mu'] + math.sqrt(variance) * shocks[t]
        variance = omega + p['alpha'] * (returns[t] - p['mu']) ** 2 + p['beta'] * variance
    dates = pd.bdate_range(end='2025-12-31', periods=n)
    return pd.Series(returns, index=dates, name='return')


# ----------------------------------------------------------------------------------------------------------------------
# Analysis
# ----------------------------------------------------------------------------------------------------------------------


def clean(value: float, digits: int = 6) -> Optional[float]:
    return round(float(value), digits) if value is not None and math.isfinite(value) else None


def clean_list(values, digits: int = 6) -> list[Optional[float]]:
    return [clean(v, digits) for v in values]


def build_series(
    values: list[float], dates: Optional[list[dt.date]] = None, kind: str = 'returns'
) -> tuple[pd.Series, list[str]]:
    """Validate raw input and return a series of simple returns, plus the assumptions that were made"""
    assumptions: list[str] = []
    if len(values) > MAX_OBSERVATIONS:
        raise AnalysisError(f'At most {MAX_OBSERVATIONS} observations are supported, got {len(values)}')
    array = np.asarray(values, dtype=float)
    if not np.isfinite(array).all():
        raise AnalysisError('Values must be finite numbers')
    if dates is not None:
        if len(dates) != len(array):
            raise AnalysisError(f'Got {len(dates)} dates for {len(array)} values')
        index = pd.DatetimeIndex(pd.to_datetime(dates))
        if not index.is_monotonic_increasing or index.has_duplicates:
            raise AnalysisError('Dates must be strictly increasing, without duplicates')
    else:
        index = pd.RangeIndex(len(array))
        assumptions.append(f'No dates were given, so {DEFAULT_PERIODS_PER_YEAR} periods per year are assumed')
    series = pd.Series(array, index=index)
    if kind == 'prices':
        if (series <= 0).any():
            raise AnalysisError('Prices must be positive')
        series = series.pct_change().dropna()
        assumptions.append('Returns were calculated as simple returns from the prices')
    elif (series <= -1).any():
        raise AnalysisError('Simple returns must be greater than -100%')
    if len(series) < 60:
        raise AnalysisError('At least 60 returns are needed for a meaningful analysis')
    return series, assumptions


def ewma_volatility(returns: pd.Series, decay: float = EWMA_DECAY) -> pd.Series:
    """Exponentially weighted volatility per period, with zero mean: s2[t] = decay * s2[t-1] + (1 - decay) * r[t]^2

    The recursion starts from the first squared return, so the first values are noisy: the weights of the start fall
    below one in a million after about 230 periods at the default decay.
    """
    return np.sqrt((returns**2).ewm(alpha=1 - decay, adjust=False).mean())


def _ewma(
    returns: pd.Series,
    confidence: float,
    window: int,
    periods: float,
    var: pd.Series,
    summary: dict,
    decay: float = EWMA_DECAY,
) -> tuple:
    """The filtered estimate of risk next to the rolling one: its volatility, a normal value at risk from it, and how
    that value at risk fared against the periods that followed it (over the same periods as the rolling window's)"""
    sigma = ewma_volatility(returns, decay)
    z = float(stats.norm.ppf(1 - confidence))
    forecast = (z * sigma).where(var.notna())  # the same periods as the rolling estimate, so the two are comparable
    backtest = var_backtest(returns, forecast.shift(1), confidence)
    recent = returns.iloc[-window:]
    details = {
        'decay': decay,
        'volatility': clean(float(sigma.iloc[-1]) * math.sqrt(periods), 6),
        'window_volatility': clean(float(recent.std(ddof=1)) * math.sqrt(periods), 6),
        'full_volatility': clean(summary['annualized_volatility'], 6),
        'var': clean(float(z * sigma.iloc[-1]), 6),
        'exceedances': backtest.exceedances,
        'observations': backtest.observations,
        'expected_rate': clean(backtest.expected_rate, 6),
        'p_value': clean(backtest.p_value, 6),
        'reject': bool(backtest.reject),
    }
    return details, forecast


def horizon_risk(periods: int, var: float, es: float) -> dict:
    """Value at risk and expected shortfall over several periods by the square-root-of-time rule: the one-period figure
    times the square root of the horizon. It assumes independent returns and no drift, and it is an approximation,
    never an exact result; it is capped at a loss of 100%."""
    scale = math.sqrt(periods)
    return {
        'periods': periods,
        'method': 'square_root',
        'rule': 'square_root_of_time',
        'var': clean(max(var * scale, -1.0)),
        'expected_shortfall': clean(max(es * scale, -1.0)),
        'backtest': None,
    }


def filtered_simulation(
    returns: pd.Series,
    horizon: int,
    confidence: float,
    decay: float,
    paths: int = SIMULATION_PATHS,
    seed: int = SIMULATION_SEED,
) -> tuple[float, float]:
    """Value at risk and expected shortfall over several periods by filtered historical simulation

    Each return is divided by the EWMA volatility forecast made before it, which leaves returns that are about as
    volatile as each other. Paths are then simulated from today's volatility: each step draws one of those standardised
    returns at random, multiplies it by the current volatility, and moves the volatility on with the EWMA recursion, so
    the paths are as volatile as the market is now and have the fat tails and skew of the history. The figures are the
    quantile and the mean of the worst tail of the compounded returns of the paths. Returns have zero mean, as in the
    EWMA, and the draws come from a fixed seed: the same analysis always gives the same figures.
    """
    sigma = ewma_volatility(returns, decay)
    forecast = sigma.shift(1)  # the volatility each return was judged against: known before it happened
    standardised = (returns / forecast).iloc[SIMULATION_BURN_IN:].to_numpy()
    standardised = standardised[np.isfinite(standardised)]
    if standardised.size < 30:
        raise AnalysisError('Too few returns to simulate from')
    rng = np.random.default_rng(seed)
    draws = rng.choice(standardised, size=(paths, horizon))
    variance = np.full(paths, float(sigma.iloc[-1]) ** 2)
    growth = np.ones(paths)
    for step in range(horizon):
        shock = np.sqrt(variance) * draws[:, step]
        step_return = np.maximum(shock, -0.999999)  # a loss of more than everything is not possible
        growth *= 1 + step_return
        variance = decay * variance + (1 - decay) * step_return**2
    compounded = growth - 1
    threshold = float(np.quantile(compounded, 1 - confidence))
    return threshold, float(compounded[compounded <= threshold].mean())


def horizon_backtest(returns: pd.Series, var: pd.Series, horizon: int, confidence: float) -> Optional[dict]:
    """The square-root-of-time value at risk against what really happened over the same number of periods

    Only non-overlapping stretches are judged: overlapping ones share most of their returns, which breaks the independence
    the Kupiec test relies on. Each stretch is judged against the one-period rolling value at risk known just before it,
    scaled by the square root of the horizon. None if fewer than MIN_HORIZON_BLOCKS stretches can be judged.
    """
    values = returns.to_numpy()
    known = var.to_numpy()
    first = int(np.argmax(np.isfinite(known))) + 1  # the first stretch starts after the first value at risk exists
    ends, realised, forecast = [], [], []
    for start in range(first, len(values) - horizon + 1, horizon):
        if not np.isfinite(known[start - 1]):
            continue
        realised.append(float(np.prod(1 + values[start : start + horizon]) - 1))
        forecast.append(max(float(known[start - 1]) * math.sqrt(horizon), -1.0))
        ends.append(returns.index[start + horizon - 1])
    if len(realised) < MIN_HORIZON_BLOCKS:
        return None
    result = var_backtest(pd.Series(realised, index=range(len(realised))), pd.Series(forecast), confidence)
    return {
        'periods': horizon,
        'observations': result.observations,
        'exceedances': result.exceedances,
        'expected_rate': clean(result.expected_rate, 6),
        'p_value': clean(result.p_value, 6),
        'reject': bool(result.reject),
    }


def versus_benchmark(returns: pd.Series, benchmark: pd.Series, name: str, periods: float) -> dict:
    """How the series moves against a benchmark over the periods both have: beta, tracking error and the rest"""
    joined = pd.concat([returns.rename('r'), benchmark.rename('b')], axis=1, join='inner').dropna()
    if len(joined) < MIN_BENCHMARK_OBSERVATIONS:
        raise AnalysisError(f'At least {MIN_BENCHMARK_OBSERVATIONS} periods in common with the benchmark are needed')
    r, b = joined['r'], joined['b']
    variance = float(b.var(ddof=1))
    if not variance > MIN_BENCHMARK_VARIANCE:
        raise AnalysisError('The benchmark does not vary, so there is nothing to compare against')
    beta = float(r.cov(b)) / variance
    correlation = float(r.corr(b))
    active = r - b
    te = tracking_error(r, b, annualization_factor=int(periods)).dropna()
    ir = information_ratio(r, b, annualization_factor=int(periods)).dropna()
    return {
        'name': name,
        'observations': len(joined),
        'beta': clean(beta, 4),
        'correlation': clean(correlation, 4),
        'r_squared': clean(correlation**2, 4),
        'alpha': clean((float(r.mean()) - beta * float(b.mean())) * periods),
        'active_return': clean(float(active.mean()) * periods),
        'tracking_error': clean(float(te.iloc[-1])) if len(te) else None,
        'information_ratio': clean(float(ir.iloc[-1]), 4) if len(ir) else None,
        'benchmark_volatility': clean(float(b.std(ddof=1)) * math.sqrt(periods)),
        'volatility': clean(float(r.std(ddof=1)) * math.sqrt(periods)),
    }


def _histogram(returns: pd.Series) -> dict:
    """Histogram over the central 99% of the returns, with the number of outliers outside it"""
    low, high = np.quantile(returns, [HISTOGRAM_TAIL, 1 - HISTOGRAM_TAIL])
    edges = np.linspace(low, high, HISTOGRAM_BINS + 1)
    inside = returns[(returns >= low) & (returns <= high)]
    counts, _ = np.histogram(inside, bins=edges)
    centres = (edges[:-1] + edges[1:]) / 2
    width = edges[1] - edges[0]
    mu, sigma = returns.mean(), returns.std(ddof=1)
    return {
        'centres': clean_list(centres, 6),
        'counts': [int(c) for c in counts],
        'normal_counts': clean_list(stats.norm.pdf(centres, mu, sigma) * width * len(returns), 4),
        'width': clean(width, 8),
        'outliers_below': int((returns < low).sum()),
        'outliers_above': int((returns > high).sum()),
    }


def _qq(returns: pd.Series) -> dict:
    """Standardised sample quantiles against normal quantiles, keeping every point of the tails, where the action is"""
    n = len(returns)
    z = np.sort((returns.to_numpy() - returns.mean()) / returns.std(ddof=1))
    theoretical = stats.norm.ppf((np.arange(1, n + 1) - 0.5) / n)
    tail = max(int(n * 0.05), 1)
    keep = np.zeros(n, dtype=bool)
    keep[:tail] = keep[-tail:] = True
    middle = np.flatnonzero(~keep)
    budget = max(QQ_MAX_POINTS - 2 * tail, 20)
    keep[middle[np.linspace(0, len(middle) - 1, min(budget, len(middle))).astype(int)]] = True
    return {'theoretical': clean_list(theoretical[keep], 4), 'sample': clean_list(z[keep], 4)}


def _worst_drawdown(growth: pd.Series) -> dict:
    """Peak and trough (as positions) of the deepest fall from a running peak, and its depth"""
    values = np.concatenate(([1.0], growth.to_numpy()))
    peaks = np.maximum.accumulate(values)
    depth = values / peaks - 1
    trough = int(np.argmin(depth))
    peak = int(np.argmax(values[: trough + 1]))
    # position 0 is the starting value, before the first return: map back to positions in the returns
    return {'peak': max(peak - 1, 0), 'trough': max(trough - 1, 0), 'depth': clean(depth[trough], 6)}


def stress(returns: pd.Series, assets: Optional[pd.DataFrame] = None) -> list[dict]:
    """The worst stretch of 1, 5 and 20 periods in the data: its compounded return and dates

    With the returns of the assets behind a portfolio, each window also lists what every asset did over the same dates.
    """
    labels = [str(i.date()) if isinstance(i, pd.Timestamp) else str(i) for i in returns.index]
    cumulative = np.concatenate(([0.0], np.cumsum(np.log1p(returns.to_numpy()))))
    windows = []
    for horizon in STRESS_HORIZONS:
        if horizon * 3 > len(returns):  # a window that is a large part of the data says little
            continue
        compounded = np.expm1(cumulative[horizon:] - cumulative[:-horizon])
        end = int(np.argmin(compounded)) + horizon - 1
        start = end - horizon + 1
        window = {'periods': horizon, 'return': clean(compounded.min()), 'start': labels[start], 'end': labels[end]}
        if assets is not None:
            window['assets'] = [
                {'name': name, 'return': clean(np.expm1(np.log1p(assets[name].iloc[start : end + 1]).sum()))}
                for name in assets.columns
            ]
        windows.append(window)
    return windows


def analyze(
    returns: pd.Series,
    confidence: float = 0.95,
    method: VaRMethod = VaRMethod.HISTORICAL,
    window: int = 250,
    minimum_acceptable_return: float = 0.0,
    periods_per_year: Optional[int] = None,
    assumptions: Optional[list[str]] = None,
    horizon: int = 1,
    ewma_decay: float = EWMA_DECAY,
    horizon_method: str = 'square_root',
) -> dict:
    """Everything the dashboard shows for a series of simple returns"""
    if horizon_method not in HORIZON_METHODS:
        raise AnalysisError(f'The horizon method must be one of {", ".join(HORIZON_METHODS)}')
    if not MIN_DECAY <= ewma_decay <= MAX_DECAY:
        raise AnalysisError(f'The EWMA decay must be between {MIN_DECAY} and {MAX_DECAY}')
    assumptions = list(assumptions or [])
    dated = isinstance(returns.index, pd.DatetimeIndex)
    factor = periods_per_year if periods_per_year is not None else (None if dated else DEFAULT_PERIODS_PER_YEAR)
    if len(returns) <= window + 1:
        raise AnalysisError(f'The rolling window ({window}) must be shorter than the series ({len(returns)} returns)')
    try:
        summary = risk_summary(returns, confidence, minimum_acceptable_return, factor)
        periods = infer_periods_per_year(returns, factor)

        whole = Window(window, window - 1)  # full windows only
        var = value_at_risk(returns, confidence, method, w=whole)
        es_method = VaRMethod.PARAMETRIC if method == VaRMethod.CORNISH_FISHER else method
        if es_method != method:
            assumptions.append('Expected shortfall uses the parametric method, as Cornish-Fisher is not defined for it')
        es = expected_shortfall(returns, confidence, es_method, w=whole)
        forecast = var.shift(1)  # ex ante: each day is judged against the VaR estimated before it
        backtest = var_backtest(returns, forecast, confidence)
        independence = var_independence_test(returns, forecast, confidence)
        light = traffic_light_zone(backtest.exceedances, backtest.observations, confidence)
        ewma, ewma_var = _ewma(returns, confidence, window, periods, var, summary.to_dict(), ewma_decay)
    except (MqError, ValueError) as e:
        raise AnalysisError(str(e)) from e

    risk = headline_figures(summary.to_dict(), method)
    horizon_details = horizon_risk(horizon, risk['var'], risk['expected_shortfall'])
    if horizon > 1 and horizon_method == 'filtered_simulation':
        simulated_var, simulated_es = filtered_simulation(returns, horizon, confidence, ewma_decay)
        horizon_details = {
            'periods': horizon,
            'method': 'filtered_simulation',
            'rule': 'filtered_historical_simulation',
            'var': clean(max(simulated_var, -1.0)),
            'expected_shortfall': clean(max(simulated_es, -1.0)),
            'paths': SIMULATION_PATHS,
            'backtest': None,
        }
        assumptions.append(
            f'The {horizon}-period figures come from a filtered historical simulation: {SIMULATION_PATHS:,} paths from the '
            f'current EWMA volatility (decay {ewma_decay}), drawing the history\'s standardised returns, with zero mean'
        )
    elif horizon > 1:
        horizon_details['backtest'] = horizon_backtest(returns, var.reindex(returns.index), horizon, confidence)
        assumptions.append(
            f'The {horizon}-period figures scale the one-period value at risk and expected shortfall by the square '
            'root of the horizon, which assumes independent returns and no drift'
        )

    growth = (1 + returns).cumprod()
    dd = drawdown(pd.concat([pd.Series([1.0]), growth.reset_index(drop=True)]))[1:]
    dd.index = returns.index
    aligned = pd.concat([returns.rename('r'), forecast.rename('f')], axis=1)
    breaches = aligned['r'] < aligned['f']

    labels = [str(i.date()) if isinstance(i, pd.Timestamp) else str(i) for i in returns.index]

    return {
        'summary': summary.to_dict(),
        'backtest': {
            **asdict(backtest),
            'independence': asdict(independence),
            'traffic_light': {
                'zone': light.zone.value,
                'cumulative_probability': clean(light.cumulative_probability, 6),
                'expected_exceedances': clean(light.expected_exceedances, 4),
            },
        },
        'settings': {
            'confidence': confidence,
            'method': method.value,
            'window': window,
            'minimum_acceptable_return': minimum_acceptable_return,
            'periods_per_year': periods,
            'horizon': horizon,
            'horizon_method': horizon_method,
            'ewma_decay': ewma_decay,
        },
        'horizon': horizon_details,
        'ewma': ewma,
        'series': {
            'dates': labels,
            'returns': clean_list(returns, 6),
            'growth': clean_list(growth, 6),
            'drawdown': clean_list(dd, 6),
            'var': clean_list(var.reindex(returns.index), 6),
            'expected_shortfall': clean_list(es.reindex(returns.index), 6),
            'ewma_var': clean_list(ewma_var.reindex(returns.index), 6),
            'breach': [bool(b) for b in breaches.reindex(returns.index).fillna(False)],
        },
        'histogram': _histogram(returns),
        'qq': _qq(returns),
        'worst_drawdown': _worst_drawdown(growth),
        'stress': stress(returns),
        'assumptions': assumptions,
        'conventions': 'Results are fractions (0.02 is 2%). Losses are negative.',
    }


def headline_figures(summary: dict, method: VaRMethod) -> dict:
    """The one-period value at risk and expected shortfall that the chosen method gives"""
    es_method = 'historical' if method == VaRMethod.HISTORICAL else 'parametric'
    return {
        'var': clean(summary[f'var_{method.value}']),
        'expected_shortfall': clean(summary[f'expected_shortfall_{es_method}']),
    }


def headline(result: dict) -> dict:
    """The few figures that identify a result in a list: its VaR and expected shortfall, the Basel zone and the size"""
    summary, method = result['summary'], VaRMethod(result['settings']['method'])
    return {
        'confidence': result['settings']['confidence'],
        'method': method.value,
        'observations': summary['observations'],
        **headline_figures(summary, method),
        'volatility': clean(summary['annualized_volatility']),
        'zone': result['backtest']['traffic_light']['zone'],
    }


def comparison_metrics(result: dict) -> dict:
    """The figures that are compared across saved analyses, one flat dict per result"""
    summary, test = result['summary'], result['backtest']
    metrics = {
        **headline(result),
        'annualized_return': clean(summary['annualized_return']),
        'max_drawdown': clean(summary['max_drawdown']),
        'sortino_ratio': clean(summary['sortino_ratio']),
        'calmar_ratio': clean(summary['calmar_ratio']),
        'worst_period': clean(summary['worst_period']),
        'exceedances': test['exceedances'],
        'expected_exceedances': clean(test['expected_rate'] * test['observations'], 2),
        'kupiec_p_value': clean(test['p_value'], 4),
        'diversification_ratio': None,
    }
    if 'portfolio' in result:
        metrics['diversification_ratio'] = result['portfolio']['diversification_ratio']
    return metrics


def what_if(
    scenarios: list[tuple[str, dict[str, float]]], weights: dict[str, float], var: Optional[float], es: Optional[float]
) -> list[dict]:
    """The immediate effect of shocks the user chose, on a portfolio held at the given weights

    A scenario says how much each asset moves at once, as a fraction (-0.1 is a fall of 10%); an asset it does not name does
    not move. The effect on the portfolio is the weighted sum, and a loss is also given as a multiple of the VaR and the
    expected shortfall, to say how it compares with what the model considers an ordinary bad period.
    """
    results = []
    for name, shocks in scenarios:
        unknown = [asset for asset in shocks if asset not in weights]
        if unknown:
            raise AnalysisError(f'Scenario "{name}": unknown asset "{unknown[0]}"')
        contributions = {asset: weight * shocks.get(asset, 0.0) for asset, weight in weights.items()}
        loss = sum(contributions.values())

        def multiple(risk: Optional[float]) -> Optional[float]:
            return clean(loss / risk, 3) if risk is not None and risk < 0 and loss < 0 else None

        results.append(
            {
                'name': name,
                'loss': clean(loss),
                'var_multiple': multiple(var),
                'es_multiple': multiple(es),
                'assets': [
                    {
                        'name': asset,
                        'weight': clean(weight),
                        'shock': clean(shocks.get(asset, 0.0)),
                        'contribution': clean(contributions[asset]),
                    }
                    for asset, weight in weights.items()
                ],
            }
        )
    return results
