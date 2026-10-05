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
from typing import Optional

import numpy as np
import pandas as pd

from gs_quant.timeseries.risk_metrics import VaRMethod

from . import analysis
from .analysis import AnalysisError

MAX_ASSETS = 10
MIN_ASSETS = 2
MAX_NAME_LENGTH = 40
WEIGHT_TOLERANCE = 1e-6
MIN_VARIANCE = 1e-20  # a per-period volatility of 1e-10: below this the portfolio is constant up to rounding


def build_frame(
    assets: dict[str, list[float]], dates: Optional[list[dt.date]] = None, kind: str = 'returns'
) -> tuple[pd.DataFrame, list[str]]:
    """Validate the assets and return their simple returns side by side, plus the assumptions that were made"""
    if not MIN_ASSETS <= len(assets) <= MAX_ASSETS:
        raise AnalysisError(f'A portfolio needs between {MIN_ASSETS} and {MAX_ASSETS} assets, got {len(assets)}')
    columns: dict[str, pd.Series] = {}
    assumptions: list[str] = []
    for name, values in assets.items():
        if not name.strip() or len(name) > MAX_NAME_LENGTH:
            raise AnalysisError(f'Asset names must be 1 to {MAX_NAME_LENGTH} characters')
        try:
            series, notes = analysis.build_series(values, dates, kind)
        except AnalysisError as e:
            raise AnalysisError(f'{name}: {e}') from e
        columns[name.strip()] = series
        assumptions += [n for n in notes if n not in assumptions]
    if len(columns) != len(assets):
        raise AnalysisError('Asset names must be unique')
    lengths = {len(s) for s in columns.values()}
    if len(lengths) != 1:
        raise AnalysisError('Every asset needs the same number of observations')
    return pd.DataFrame(columns), assumptions


def resolve_weights(names: list[str], weights: Optional[dict[str, float]]) -> tuple[np.ndarray, list[str]]:
    """The weight vector, in the order of the names. Missing weights mean equal weights; weights are scaled to sum to 1"""
    notes: list[str] = []
    if weights is None:
        notes.append(f'Equal weights ({1 / len(names):.1%} each) were assumed')
        return np.full(len(names), 1 / len(names)), notes
    stripped = {k.strip(): v for k, v in weights.items()}
    if set(stripped) != set(names):
        raise AnalysisError('Weights must be given for exactly the assets, no more and no fewer')
    w = np.array([stripped[n] for n in names], dtype=float)
    if not np.isfinite(w).all():
        raise AnalysisError('Weights must be finite numbers')
    total = float(w.sum())
    if total <= WEIGHT_TOLERANCE:
        raise AnalysisError('Weights must sum to a positive number')
    if abs(total - 1) > WEIGHT_TOLERANCE:
        w = w / total
        notes.append(f'Weights summed to {total:.4g} and were scaled to sum to 1')
    return w, notes


def _decompose(frame: pd.DataFrame, w: np.ndarray, portfolio: pd.Series, confidence: float, periods: float) -> dict:
    """Standalone and contributed risk of each asset in the whole sample

    Volatility contributions are the Euler allocation of portfolio volatility, and the expected shortfall contributions
    are the Euler allocation of the historical expected shortfall: the weight times the asset's mean return on the
    periods when the portfolio was in its tail. Both add up to the portfolio figure exactly.
    """
    cov = frame.cov().to_numpy()
    port_var = float(w @ cov @ w)
    if not port_var > MIN_VARIANCE:
        raise AnalysisError('The portfolio has no variance, so its risk cannot be decomposed')
    vol_share = w * (cov @ w) / port_var

    threshold = float(np.quantile(portfolio, 1 - confidence))
    tail = (portfolio <= threshold).to_numpy()
    es_total = float(portfolio[tail].mean())
    es_part = w * frame[tail].mean().to_numpy()

    sigma = np.sqrt(np.diag(cov))
    annual = math.sqrt(periods)
    corr = frame.corr().to_numpy()
    assets = []
    for i, name in enumerate(frame.columns):
        assets.append(
            {
                'name': name,
                'weight': analysis.clean(w[i], 6),
                'volatility': analysis.clean(sigma[i] * annual, 6),
                'var': analysis.clean(np.quantile(frame[name], 1 - confidence), 6),
                'volatility_contribution': analysis.clean(vol_share[i], 6),
                'es_contribution': analysis.clean(es_part[i] / es_total if es_total else float('nan'), 6),
            }
        )
    return {
        'assets': assets,
        'portfolio_volatility': analysis.clean(math.sqrt(port_var) * annual, 6),
        'diversification_ratio': analysis.clean(float(w @ sigma) / math.sqrt(port_var), 4),
        'tail_periods': int(tail.sum()),
        'correlation': {'names': list(frame.columns), 'matrix': [analysis.clean_list(row, 4) for row in corr]},
    }


def analyze_portfolio(
    assets: dict[str, list[float]],
    weights: Optional[dict[str, float]] = None,
    dates: Optional[list[dt.date]] = None,
    kind: str = 'returns',
    confidence: float = 0.95,
    method: VaRMethod = VaRMethod.HISTORICAL,
    window: int = 250,
    minimum_acceptable_return: float = 0.0,
    periods_per_year: Optional[int] = None,
    horizon: int = 1,
    ewma_decay: float = analysis.EWMA_DECAY,
    horizon_method: str = 'square_root',
    benchmark: Optional[list[float]] = None,
    benchmark_name: str = 'Benchmark',
) -> dict:
    """The dashboard analysis of a portfolio of assets held at constant weights, plus its decomposition by asset"""
    frame, assumptions = build_frame(assets, dates, kind)
    w, notes = resolve_weights(list(frame.columns), weights)
    assumptions += notes
    assumptions.append('The portfolio is rebalanced to its weights every period')
    portfolio = pd.Series(frame.to_numpy() @ w, index=frame.index, name='portfolio')
    if (portfolio <= -1).any():
        raise AnalysisError('The portfolio lost more than 100% in a period, which the analysis cannot handle')
    result = analysis.analyze(
        portfolio,
        confidence,
        method,
        window,
        minimum_acceptable_return,
        periods_per_year,
        assumptions,
        horizon,
        ewma_decay,
        horizon_method,
    )
    result['stress'] = analysis.stress(portfolio, frame)
    result['portfolio'] = _decompose(frame, w, portfolio, confidence, result['settings']['periods_per_year'])
    if benchmark is not None:
        result['benchmark'] = analysis.compare_with_benchmark(
            portfolio, benchmark, dates, kind, benchmark_name, result['settings']['periods_per_year'], window
        )
    return result
