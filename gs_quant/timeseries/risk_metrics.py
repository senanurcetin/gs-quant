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

# Downside and tail risk analytics for return and price series.
#
# These functions work on plain pandas Series, need no Marquee session and follow the window conventions of the rest
# of :mod:`gs_quant.timeseries`: ``w`` is an int, a relative date such as ``'1m'`` or a :class:`Window`, and the
# default window is the whole series (an expanding calculation).
#
# The module is deliberately *not* star-imported by :mod:`gs_quant.timeseries`, because ``sortino_ratio``,
# ``calmar_ratio``, ``tracking_error``, ``information_ratio``, ``skewness`` and ``kurtosis`` already exist there as
# report-based measures. Import from ``gs_quant.timeseries.risk_metrics`` explicitly.
#
# Unless stated otherwise, results are fractions rather than percentages (0.02 is 2%), and a loss is a negative
# number, as in :func:`gs_quant.timeseries.econometrics.max_drawdown`.

import math
from dataclasses import asdict, dataclass
from enum import Enum, unique
from typing import Callable, Optional, Union

import numpy as np
import pandas as pd
from scipy import special, stats

from gs_quant.errors import MqValueError
from gs_quant.timeseries.econometrics import _get_annualization_factor
from gs_quant.timeseries.helper import Window, apply_ramp, normalize_window

__all__ = [
    'VaRMethod',
    'KupiecTestResult',
    'RiskSummary',
    'drawdown',
    'ulcer_index',
    'downside_deviation',
    'sortino_ratio',
    'omega_ratio',
    'calmar_ratio',
    'value_at_risk',
    'expected_shortfall',
    'tracking_error',
    'information_ratio',
    'var_backtest',
    'risk_summary',
]


@unique
class VaRMethod(Enum):
    """Method used to estimate a return quantile"""

    HISTORICAL = 'historical'  #: Empirical quantile of the observed returns
    PARAMETRIC = 'parametric'  #: Normal distribution fitted to the mean and standard deviation
    CORNISH_FISHER = 'cornish_fisher'  #: Normal quantile adjusted for sample skewness and excess kurtosis


# ----------------------------------------------------------------------------------------------------------------------
# Scalar kernels: each takes the observations of a single window as a 1-d array
# ----------------------------------------------------------------------------------------------------------------------


def _finite(a: np.ndarray) -> np.ndarray:
    a = np.asarray(a, dtype=float)
    return a[~np.isnan(a)]


def _drawdowns(prices: np.ndarray) -> np.ndarray:
    return prices / np.maximum.accumulate(prices) - 1


def _validate_confidence(confidence: float) -> float:
    if not 0 < confidence < 1:
        raise MqValueError(f'confidence must be strictly between 0 and 1, got {confidence}')
    return 1 - confidence


def _cornish_fisher_quantile(z: float, skew: float, excess_kurtosis: float) -> float:
    return z + (z**2 - 1) * skew / 6 + (z**3 - 3 * z) * excess_kurtosis / 24 - (2 * z**3 - 5 * z) * skew**2 / 36


def _var_kernel(a: np.ndarray, alpha: float, method: VaRMethod) -> float:
    a = _finite(a)
    if method == VaRMethod.HISTORICAL:
        return float(np.quantile(a, alpha)) if a.size else math.nan
    if a.size < 2:
        return math.nan
    if a.min() == a.max():  # no dispersion: every quantile is the constant (and skewness is undefined)
        return float(a[0])
    mean, std = a.mean(), a.std(ddof=1)
    z = stats.norm.ppf(alpha)
    if method == VaRMethod.PARAMETRIC:
        return float(mean + z * std)
    if a.size < 4:  # sample skewness and kurtosis are undefined
        return math.nan
    z = _cornish_fisher_quantile(z, stats.skew(a, bias=False), stats.kurtosis(a, bias=False))
    return float(mean + z * std)


def _es_kernel(a: np.ndarray, alpha: float, method: VaRMethod) -> float:
    a = _finite(a)
    if method == VaRMethod.HISTORICAL:
        if not a.size:
            return math.nan
        return float(a[a <= np.quantile(a, alpha)].mean())
    if a.size < 2:
        return math.nan
    z = stats.norm.ppf(alpha)
    return float(a.mean() - a.std(ddof=1) * stats.norm.pdf(z) / alpha)


def _downside_deviation_kernel(a: np.ndarray, mar: float) -> float:
    a = _finite(a)
    if not a.size:
        return math.nan
    return float(math.sqrt(np.mean(np.minimum(a - mar, 0.0) ** 2)))


def _sortino_kernel(a: np.ndarray, mar: float) -> float:
    a = _finite(a)
    if not a.size:
        return math.nan
    deviation = _downside_deviation_kernel(a, mar)
    return float((a.mean() - mar) / deviation) if deviation > 0 else math.nan


def _omega_kernel(a: np.ndarray, threshold: float) -> float:
    a = _finite(a)
    if not a.size:
        return math.nan
    losses = np.maximum(threshold - a, 0.0).sum()
    return float(np.maximum(a - threshold, 0.0).sum() / losses) if losses > 0 else math.nan


def _ulcer_kernel(prices: np.ndarray) -> float:
    prices = _finite(prices)
    return float(math.sqrt(np.mean(_drawdowns(prices) ** 2))) if prices.size else math.nan


def _calmar_kernel(prices: np.ndarray, periods_per_year: float) -> float:
    prices = _finite(prices)
    if prices.size < 2 or prices[0] <= 0:
        return math.nan
    worst = _drawdowns(prices).min()
    if worst >= 0:
        return math.nan
    growth = prices[-1] / prices[0]
    if growth <= 0:
        return math.nan
    cagr = growth ** (periods_per_year / (prices.size - 1)) - 1
    return float(cagr / abs(worst))


# ----------------------------------------------------------------------------------------------------------------------
# Windowing helpers
# ----------------------------------------------------------------------------------------------------------------------


def _periods_per_year(x: pd.Series, annualization_factor: Optional[int]) -> float:
    if annualization_factor is not None:
        if annualization_factor <= 0:
            raise MqValueError('annualization_factor must be positive')
        return float(annualization_factor)
    if x.size < 2:
        raise MqValueError('Cannot infer the annualization factor from fewer than two observations')
    try:
        return float(_get_annualization_factor(x))
    except (AttributeError, TypeError) as e:
        raise MqValueError(
            'Cannot infer the annualization factor from a non-date index; pass annualization_factor'
        ) from e


def _rolling(x: pd.Series, w: Union[Window, int, str], kernel: Callable[[np.ndarray], float]) -> pd.Series:
    """Apply a scalar kernel over each window of x, honouring the same window and ramp semantics as the rest of the
    package.

    The kernel is only evaluated for the dates that survive the ramp up, so the cost is that of the windows returned:
    O(n * w) for n dates and windows of w observations."""
    if x.empty:
        return pd.Series(dtype=float)
    w = normalize_window(x, w)
    if isinstance(w.w, pd.DateOffset) and not isinstance(x.index, pd.DatetimeIndex):
        raise TypeError('Please pass in list of dates as index')
    values = x.to_numpy(dtype=float)
    n = len(values)
    # Let apply_ramp decide which dates are kept, so that the result matches the other functions exactly
    kept = apply_ramp(pd.Series(np.arange(n), index=x.index), w)
    if kept.empty:
        return pd.Series(dtype=float)
    first = int(kept.iloc[0])
    if isinstance(w.w, pd.DateOffset):
        starts = x.index.searchsorted(x.index[first:] - w.w, side='right')
    else:
        starts = np.maximum(np.arange(first, n) - w.w + 1, 0)
    return pd.Series(
        [kernel(values[s : i + 1]) for i, s in zip(range(first, n), starts)], index=x.index[first:], dtype=float
    )


def _active_returns(x: pd.Series, benchmark: pd.Series) -> pd.Series:
    x, benchmark = x.align(benchmark, join='inner')
    return x - benchmark


# ----------------------------------------------------------------------------------------------------------------------
# Public series functions
# ----------------------------------------------------------------------------------------------------------------------


def drawdown(x: pd.Series) -> pd.Series:
    """
    Drawdown of a price series: the fall from the running peak, as a ratio

    :param x: time series of prices
    :return: time series of drawdowns, always less than or equal to zero. A 20% fall from the previous peak is -0.2.

    **Usage**

    :math:`D_t = \\frac{P_t}{\\max_{s \\le t} P_s} - 1`

    Use :func:`gs_quant.timeseries.econometrics.max_drawdown` for the worst drawdown over a window.

    **Examples**

    >>> prices = generate_series(100)
    >>> dd = drawdown(prices)
    """
    return x / x.cummax() - 1


def ulcer_index(x: pd.Series, w: Union[Window, int, str] = Window(None, 0)) -> pd.Series:
    """
    Ulcer index: the root mean square drawdown, which captures both the depth and the duration of drawdowns

    :param x: time series of prices
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :return: time series of the rolling ulcer index, as a fraction (0.05 is 5%)

    **Usage**

    :math:`U_t = \\sqrt{\\frac{1}{N} \\sum_{i=t-w+1}^{t} D_i^2}`

    where :math:`D_i` is the drawdown from the running peak *within the window*.
    """
    return _rolling(x, w, _ulcer_kernel)


def downside_deviation(
    x: pd.Series,
    mar: float = 0.0,
    w: Union[Window, int, str] = Window(None, 0),
    annualization_factor: Optional[int] = None,
) -> pd.Series:
    """
    Downside deviation: the root mean square of the returns that fall short of a minimum acceptable return

    :param x: time series of returns
    :param mar: minimum acceptable return per period, in the same units as x
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :param annualization_factor: number of periods per year. If None (default) it is inferred from the frequency of
                                 the data, as in :func:`gs_quant.timeseries.econometrics.volatility`. Pass 1 to leave
                                 the result per period.
    :return: time series of the rolling annualized downside deviation, as a fraction

    **Usage**

    :math:`DD_t = \\sqrt{\\frac{1}{N} \\sum_{i=t-w+1}^{t} \\min(R_i - MAR, 0)^2} \\times \\sqrt{F}`

    The mean is taken over *all* :math:`N` observations in the window, not only the shortfalls, so that windows with
    few losses are not penalised. Unlike standard deviation, only returns below the target contribute.
    """
    factor = _periods_per_year(x, annualization_factor)
    return _rolling(x, w, lambda a: _downside_deviation_kernel(a, mar)) * math.sqrt(factor)


def sortino_ratio(
    x: pd.Series,
    mar: float = 0.0,
    w: Union[Window, int, str] = Window(None, 0),
    annualization_factor: Optional[int] = None,
) -> pd.Series:
    """
    Sortino ratio: excess return over a minimum acceptable return per unit of downside deviation

    :param x: time series of returns
    :param mar: minimum acceptable return per period, in the same units as x
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :param annualization_factor: number of periods per year. If None (default) it is inferred from the frequency of
                                 the data. Pass 1 to leave the ratio per period.
    :return: time series of the rolling annualized Sortino ratio. NaN where the window has no returns below the
             target, as the ratio is then undefined.

    **Usage**

    :math:`S_t = \\frac{\\overline{R} - MAR}{DD} \\times \\sqrt{F}`

    where :math:`DD` is the per period :func:`downside_deviation`.
    """
    factor = _periods_per_year(x, annualization_factor)
    return _rolling(x, w, lambda a: _sortino_kernel(a, mar)) * math.sqrt(factor)


def omega_ratio(x: pd.Series, threshold: float = 0.0, w: Union[Window, int, str] = Window(None, 0)) -> pd.Series:
    """
    Omega ratio: probability weighted gains above a threshold relative to losses below it

    :param x: time series of returns
    :param threshold: return threshold per period, in the same units as x
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :return: time series of the rolling Omega ratio. NaN where no return in the window falls below the threshold.

    **Usage**

    :math:`\\Omega_t = \\frac{\\sum_i \\max(R_i - L, 0)}{\\sum_i \\max(L - R_i, 0)}`

    A value above 1 means gains outweigh losses relative to the threshold :math:`L`. Unlike the Sharpe ratio it uses
    the whole return distribution, not only the first two moments.
    """
    return _rolling(x, w, lambda a: _omega_kernel(a, threshold))


def calmar_ratio(
    x: pd.Series, w: Union[Window, int, str] = Window(None, 0), annualization_factor: Optional[int] = None
) -> pd.Series:
    """
    Calmar ratio: annualized compound return divided by the magnitude of the maximum drawdown

    :param x: time series of prices
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :param annualization_factor: number of periods per year. If None (default) it is inferred from the frequency of
                                 the data.
    :return: time series of the rolling Calmar ratio. NaN where the window has no drawdown, as the ratio is then
             undefined.

    **Usage**

    :math:`C_t = \\frac{(P_t / P_{t-w+1})^{F / (N-1)} - 1}{|\\max\\ drawdown|}`

    where :math:`N` is the number of prices in the window and :math:`F` the annualization factor.
    """
    factor = _periods_per_year(x, annualization_factor)
    return _rolling(x, w, lambda a: _calmar_kernel(a, factor))


def value_at_risk(
    x: pd.Series,
    confidence: float = 0.95,
    method: VaRMethod = VaRMethod.HISTORICAL,
    w: Union[Window, int, str] = Window(None, 0),
) -> pd.Series:
    """
    Value at risk: the return that is not expected to be breached, at a given confidence level, over one period

    :param x: time series of returns
    :param confidence: confidence level, strictly between 0 and 1. Defaults to 95%.
    :param method: historical, parametric (normal) or Cornish-Fisher. Defaults to historical.
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :return: time series of the rolling value at risk, as a return. A loss is negative, so a 95% VaR of -0.02 means
             the return is expected to be worse than -2% only on 5% of periods.

    **Usage**

    With :math:`\\alpha = 1 - confidence`:

    ==============  ==============================================================================================
    Method          Definition
    ==============  ==============================================================================================
    historical      the :math:`\\alpha` quantile of the observed returns (linear interpolation)
    parametric      :math:`\\mu + z_\\alpha \\sigma`, with :math:`z_\\alpha` the standard normal quantile
    cornish_fisher  :math:`\\mu + z_{CF} \\sigma`, with the normal quantile expanded for skewness :math:`S` and excess
                    kurtosis :math:`K`:
                    :math:`z_{CF} = z + \\frac{z^2-1}{6}S + \\frac{z^3-3z}{24}K - \\frac{2z^3-5z}{36}S^2`
    ==============  ==============================================================================================

    Cornish-Fisher only gives a monotonic, meaningful quantile for moderate skewness and kurtosis, and needs at least
    four observations per window.

    **Examples**

    >>> daily_returns = returns(generate_series(500))
    >>> var_95 = value_at_risk(daily_returns, 0.95, w=250)
    >>> var_99 = value_at_risk(daily_returns, 0.99, VaRMethod.CORNISH_FISHER, w=250)

    **See also**

    :func:`expected_shortfall` :func:`var_backtest`
    """
    alpha = _validate_confidence(confidence)
    return _rolling(x, w, lambda a: _var_kernel(a, alpha, VaRMethod(method)))


def expected_shortfall(
    x: pd.Series,
    confidence: float = 0.95,
    method: VaRMethod = VaRMethod.HISTORICAL,
    w: Union[Window, int, str] = Window(None, 0),
) -> pd.Series:
    """
    Expected shortfall (conditional value at risk): the average return in the worst tail of the distribution

    :param x: time series of returns
    :param confidence: confidence level, strictly between 0 and 1. Defaults to 95%.
    :param method: historical or parametric (normal). Cornish-Fisher is not supported. Defaults to historical.
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :return: time series of the rolling expected shortfall, as a return. It is never better than the value at risk
             at the same confidence.

    **Usage**

    With :math:`\\alpha = 1 - confidence`, the historical estimate is the mean of the returns at or below the
    :math:`\\alpha` quantile. The parametric estimate is :math:`\\mu - \\sigma \\varphi(z_\\alpha) / \\alpha`, where
    :math:`\\varphi` is the standard normal density.

    Unlike value at risk, expected shortfall is a coherent risk measure: it is sub-additive and reflects how bad the
    tail is, not just where it starts.

    **See also**

    :func:`value_at_risk`
    """
    alpha = _validate_confidence(confidence)
    method = VaRMethod(method)
    if method == VaRMethod.CORNISH_FISHER:
        raise MqValueError('Cornish-Fisher is not supported for expected shortfall; use historical or parametric')
    return _rolling(x, w, lambda a: _es_kernel(a, alpha, method))


def tracking_error(
    x: pd.Series,
    benchmark: pd.Series,
    w: Union[Window, int, str] = Window(None, 0),
    annualization_factor: Optional[int] = None,
) -> pd.Series:
    """
    Tracking error: the standard deviation of the return difference between a portfolio and its benchmark

    :param x: time series of portfolio returns
    :param benchmark: time series of benchmark returns. Only dates present in both series are used.
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :param annualization_factor: number of periods per year. If None (default) it is inferred from the frequency of
                                 the data.
    :return: time series of the rolling annualized tracking error, as a fraction

    **Usage**

    :math:`TE_t = \\sigma(R^{p} - R^{b}) \\times \\sqrt{F}`, using the sample standard deviation.
    """
    active = _active_returns(x, benchmark)
    factor = _periods_per_year(active, annualization_factor)
    return _rolling(active, w, lambda a: float(np.std(_finite(a), ddof=1)) if _finite(a).size > 1 else math.nan) * (
        math.sqrt(factor)
    )


def information_ratio(
    x: pd.Series,
    benchmark: pd.Series,
    w: Union[Window, int, str] = Window(None, 0),
    annualization_factor: Optional[int] = None,
) -> pd.Series:
    """
    Information ratio: annualized active return per unit of tracking error

    :param x: time series of portfolio returns
    :param benchmark: time series of benchmark returns. Only dates present in both series are used.
    :param w: Window, int or str: size of window and ramp up to use. e.g. Window(22, 10) where 22 is the window size
              and 10 the ramp up value. If w is a string, it should be a relative date like '1m', '1d', etc.
              Window size defaults to length of series.
    :param annualization_factor: number of periods per year. If None (default) it is inferred from the frequency of
                                 the data.
    :return: time series of the rolling information ratio. NaN where the active return has no variance.

    **Usage**

    :math:`IR_t = \\frac{\\overline{R^{p} - R^{b}}}{\\sigma(R^{p} - R^{b})} \\times \\sqrt{F}`

    **See also**

    :func:`tracking_error`
    """
    active = _active_returns(x, benchmark)
    factor = _periods_per_year(active, annualization_factor)

    def kernel(a: np.ndarray) -> float:
        a = _finite(a)
        std = np.std(a, ddof=1) if a.size > 1 else 0.0
        return float(a.mean() / std) if std > 0 else math.nan

    return _rolling(active, w, kernel) * math.sqrt(factor)


# ----------------------------------------------------------------------------------------------------------------------
# Model validation
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class KupiecTestResult:
    """Outcome of the Kupiec proportion of failures test"""

    observations: int  #: number of periods tested
    exceedances: int  #: number of periods in which the return was worse than the value at risk
    expected_rate: float  #: exceedance rate implied by the confidence level
    observed_rate: float  #: exceedance rate that was actually observed
    lr_statistic: float  #: likelihood ratio statistic, chi-squared with one degree of freedom under the null
    p_value: float  #: probability of a statistic at least this large if the model were correct
    reject: bool  #: True if the model is rejected at the requested significance level


def var_backtest(
    x: pd.Series, var: pd.Series, confidence: float = 0.95, significance: float = 0.05
) -> KupiecTestResult:
    """
    Backtest a value at risk model with the Kupiec proportion of failures (POF) test

    :param x: time series of realised returns
    :param var: time series of value at risk forecasts, as returns (negative for a loss). Only dates present in both
                series are used.
    :param confidence: confidence level the value at risk was estimated at. Defaults to 95%.
    :param significance: significance level of the test. Defaults to 5%.
    :return: the test result. A low p-value means the observed number of exceedances is inconsistent with the
             confidence level: too many exceedances understate the risk, too few overstate it.

    **Usage**

    An exceedance is a period whose return is below the value at risk. With :math:`T` periods, :math:`N`
    exceedances, expected rate :math:`p = 1 - confidence` and observed rate :math:`\\hat{p} = N / T`:

    :math:`LR = -2 \\ln \\left[ (1-p)^{T-N} p^N \\right] + 2 \\ln \\left[ (1-\\hat{p})^{T-N} \\hat{p}^N \\right]`

    which is asymptotically :math:`\\chi^2` with one degree of freedom under the null hypothesis that the model is
    correctly calibrated.

    ``var`` must be an *ex ante* forecast. A rolling value at risk includes the return of the day it is stamped, so
    lag it before testing to avoid look-ahead bias:

    >>> daily_returns = returns(generate_series(1000))
    >>> forecast = value_at_risk(daily_returns, 0.95, w=250).shift(1)
    >>> result = var_backtest(daily_returns, forecast, 0.95)

    The test checks the *number* of exceedances only, not whether they cluster.
    """
    p = _validate_confidence(confidence)
    if not 0 < significance < 1:
        raise MqValueError(f'significance must be strictly between 0 and 1, got {significance}')
    x, var = x.align(var, join='inner')
    valid = x.notna() & var.notna()
    x, var = x[valid], var[valid]
    n_obs = len(x)
    if n_obs == 0:
        raise MqValueError('No overlapping observations between returns and value at risk')

    exceedances = int((x < var).sum())
    observed = exceedances / n_obs
    # xlogy gives 0 * log(0) = 0, which handles the cases of no exceedances and of all exceedances
    log_null = special.xlogy(n_obs - exceedances, 1 - p) + special.xlogy(exceedances, p)
    log_alternative = special.xlogy(n_obs - exceedances, 1 - observed) + special.xlogy(exceedances, observed)
    lr = max(float(-2 * (log_null - log_alternative)), 0.0)
    p_value = float(stats.chi2.sf(lr, 1))
    return KupiecTestResult(n_obs, exceedances, p, observed, lr, p_value, p_value < significance)


# ----------------------------------------------------------------------------------------------------------------------
# Whole sample summary
# ----------------------------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskSummary:
    """Headline risk statistics for a whole return series. Values that cannot be computed are None."""

    observations: int
    periods_per_year: float
    annualized_return: Optional[float]  #: geometric, compounded from the period returns
    annualized_volatility: Optional[float]
    skewness: Optional[float]
    excess_kurtosis: Optional[float]
    best_period: Optional[float]
    worst_period: Optional[float]
    var_historical: Optional[float]
    var_parametric: Optional[float]
    var_cornish_fisher: Optional[float]
    expected_shortfall_historical: Optional[float]
    expected_shortfall_parametric: Optional[float]
    downside_deviation: Optional[float]
    sortino_ratio: Optional[float]
    omega_ratio: Optional[float]
    max_drawdown: Optional[float]
    calmar_ratio: Optional[float]
    ulcer_index: Optional[float]

    def to_dict(self) -> dict:
        return asdict(self)


def _none_if_nan(value: float) -> Optional[float]:
    return None if value is None or not math.isfinite(value) else float(value)


def risk_summary(
    x: pd.Series,
    confidence: float = 0.95,
    mar: float = 0.0,
    annualization_factor: Optional[int] = None,
) -> RiskSummary:
    """
    Headline risk statistics for a whole series of returns

    :param x: time series of simple returns
    :param confidence: confidence level for value at risk and expected shortfall. Defaults to 95%.
    :param mar: minimum acceptable (and Omega threshold) return per period, in the same units as x
    :param annualization_factor: number of periods per year. If None (default) it is inferred from the frequency of
                                 the data.
    :return: a :class:`RiskSummary`. Statistics that are undefined for the data, such as the Sortino ratio of a series
             with no losses, are None.

    **Usage**

    The drawdown statistics (maximum drawdown, Calmar and ulcer index) are computed on the cumulative growth of one
    unit invested, i.e. the compounded returns starting at 1.

    **See also**

    :func:`value_at_risk` :func:`expected_shortfall` :func:`sortino_ratio` :func:`calmar_ratio`
    """
    alpha = _validate_confidence(confidence)
    a = _finite(x.to_numpy(dtype=float))
    if a.size < 2:
        raise MqValueError('At least two returns are required')
    if (a <= -1).any():
        raise MqValueError('Simple returns must be greater than -100%')
    factor = _periods_per_year(x, annualization_factor)

    growth = np.concatenate(([1.0], np.cumprod(1 + a)))
    std = a.std(ddof=1)
    worst_drawdown = float(_drawdowns(growth).min())
    return RiskSummary(
        observations=int(a.size),
        periods_per_year=factor,
        annualized_return=_none_if_nan(growth[-1] ** (factor / a.size) - 1),
        annualized_volatility=_none_if_nan(std * math.sqrt(factor)),
        skewness=_none_if_nan(stats.skew(a, bias=False)) if a.size > 2 else None,
        excess_kurtosis=_none_if_nan(stats.kurtosis(a, bias=False)) if a.size > 3 else None,
        best_period=_none_if_nan(a.max()),
        worst_period=_none_if_nan(a.min()),
        var_historical=_none_if_nan(_var_kernel(a, alpha, VaRMethod.HISTORICAL)),
        var_parametric=_none_if_nan(_var_kernel(a, alpha, VaRMethod.PARAMETRIC)),
        var_cornish_fisher=_none_if_nan(_var_kernel(a, alpha, VaRMethod.CORNISH_FISHER)),
        expected_shortfall_historical=_none_if_nan(_es_kernel(a, alpha, VaRMethod.HISTORICAL)),
        expected_shortfall_parametric=_none_if_nan(_es_kernel(a, alpha, VaRMethod.PARAMETRIC)),
        downside_deviation=_none_if_nan(_downside_deviation_kernel(a, mar) * math.sqrt(factor)),
        sortino_ratio=_none_if_nan(_sortino_kernel(a, mar) * math.sqrt(factor)),
        omega_ratio=_none_if_nan(_omega_kernel(a, mar)),
        max_drawdown=_none_if_nan(worst_drawdown),
        calmar_ratio=_none_if_nan(_calmar_kernel(growth, factor)),
        ulcer_index=_none_if_nan(_ulcer_kernel(growth)),
    )
