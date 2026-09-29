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

import math

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal
from scipy import stats

from gs_quant.errors import MqValueError
from gs_quant.timeseries import measures_reports
from gs_quant.timeseries.helper import Window
from gs_quant.timeseries.risk_metrics import (
    TrafficLightZone,
    VaRMethod,
    calmar_ratio,
    downside_deviation,
    drawdown,
    expected_shortfall,
    infer_periods_per_year,
    information_ratio,
    omega_ratio,
    risk_summary,
    sortino_ratio,
    tracking_error,
    traffic_light_zone,
    ulcer_index,
    value_at_risk,
    var_backtest,
    var_independence_test,
)


def _daily(values, start='2021-01-04') -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


@pytest.fixture(scope='module')
def normal_returns() -> pd.Series:
    """Large iid normal sample with known parameters, for calibration checks

    Integer indexed: 100,000 business days would run past the year 2262, the limit of pandas' nanosecond timestamps.
    """
    return pd.Series(np.random.default_rng(42).normal(0.0004, 0.01, 100_000))


@pytest.fixture(scope='module')
def market_returns() -> pd.Series:
    return _daily(np.random.default_rng(7).normal(0.0005, 0.012, 750))


def _whole_sample(fn, x, *args, **kwargs) -> float:
    """Value of fn over a single window spanning the whole series (avoids computing a huge expanding series)"""
    return fn(x, *args, w=Window(len(x), len(x) - 1), **kwargs).iloc[-1]


SMALL = _daily([0.01, -0.02, 0.03, -0.04, 0.02, 0.005, -0.01, 0.015])


# ----------------------------------------------------------------------------------------------------------------------
# Drawdown family
# ----------------------------------------------------------------------------------------------------------------------


def test_drawdown_matches_hand_calculation():
    prices = _daily([100, 110, 99, 121, 90.75])

    assert drawdown(prices).round(10).tolist() == [0.0, 0.0, -0.1, 0.0, -0.25]


def test_drawdown_is_never_positive():
    prices = _daily(100 * np.cumprod(1 + np.random.default_rng(1).normal(0, 0.02, 300)))

    assert (drawdown(prices) <= 0).all()


def test_ulcer_index_is_root_mean_square_drawdown():
    prices = _daily([100, 110, 99, 121, 90.75])
    dd = np.array([0.0, 0.0, -0.1, 0.0, -0.25])

    assert ulcer_index(prices).iloc[-1] == pytest.approx(math.sqrt(np.mean(dd**2)))


def test_ulcer_index_is_zero_for_a_rising_series():
    assert (ulcer_index(_daily([1, 2, 3, 4])) == 0).all()


def test_ulcer_index_rolling_uses_drawdown_within_the_window():
    prices = _daily([100, 50, 60, 66, 72])

    # last window of 3 is [60, 66, 72]: no drawdown, although the series is far below its earlier peak
    assert ulcer_index(prices, 3).iloc[-1] == 0


# ----------------------------------------------------------------------------------------------------------------------
# Downside measures
# ----------------------------------------------------------------------------------------------------------------------


def test_downside_deviation_matches_hand_calculation():
    r = _daily([0.01, -0.02, 0.03, -0.04])

    result = downside_deviation(r, annualization_factor=1)

    assert result.iloc[-1] == pytest.approx(math.sqrt((0.02**2 + 0.04**2) / 4))


def test_downside_deviation_respects_mar_and_annualization():
    r = _daily([0.01, -0.02, 0.03, -0.04])
    shortfalls = np.minimum(r.to_numpy() - 0.015, 0)

    result = downside_deviation(r, mar=0.015, annualization_factor=252)

    assert result.iloc[-1] == pytest.approx(math.sqrt(np.mean(shortfalls**2)) * math.sqrt(252))


def test_downside_deviation_ignores_gains():
    assert downside_deviation(_daily([0.01, 0.02, 0.5, 0.0]), annualization_factor=1).iloc[-1] == 0


def test_sortino_ratio_matches_definition():
    r = SMALL.to_numpy()
    dd = math.sqrt(np.mean(np.minimum(r, 0) ** 2))

    result = sortino_ratio(SMALL, annualization_factor=252)

    assert result.iloc[-1] == pytest.approx(r.mean() / dd * math.sqrt(252))


def test_sortino_ratio_with_mar():
    r = SMALL.to_numpy()
    dd = math.sqrt(np.mean(np.minimum(r - 0.002, 0) ** 2))

    assert sortino_ratio(SMALL, mar=0.002, annualization_factor=1).iloc[-1] == pytest.approx((r.mean() - 0.002) / dd)


def test_sortino_ratio_is_nan_without_downside():
    assert sortino_ratio(_daily([0.01, 0.02, 0.03]), annualization_factor=1).isna().all()


def test_omega_ratio_matches_hand_calculation():
    r = _daily([0.03, -0.02, 0.01, -0.04])

    assert omega_ratio(r).iloc[-1] == pytest.approx(0.04 / 0.06)
    assert omega_ratio(r, threshold=0.01).iloc[-1] == pytest.approx(0.02 / (0.03 + 0.05))


def test_omega_ratio_is_nan_without_losses():
    assert omega_ratio(_daily([0.01, 0.02])).isna().all()


def test_calmar_ratio_matches_hand_calculation():
    prices = _daily([100, 120, 90, 135])

    cagr = 1.35 ** (4 / 3) - 1

    assert calmar_ratio(prices, annualization_factor=4).iloc[-1] == pytest.approx(cagr / 0.25)


def test_calmar_ratio_is_nan_without_drawdown():
    assert calmar_ratio(_daily([1, 2, 3, 4]), annualization_factor=252).isna().all()


def test_calmar_ratio_is_nan_for_non_positive_prices():
    assert calmar_ratio(_daily([0, 1, 2]), annualization_factor=252).isna().all()


# ----------------------------------------------------------------------------------------------------------------------
# Value at risk
# ----------------------------------------------------------------------------------------------------------------------


def test_historical_var_is_the_empirical_quantile(market_returns):
    assert value_at_risk(market_returns, 0.95).iloc[-1] == pytest.approx(np.quantile(market_returns, 0.05))
    assert value_at_risk(market_returns, 0.99).iloc[-1] == pytest.approx(np.quantile(market_returns, 0.01))


def test_parametric_var_matches_formula(market_returns):
    expected = market_returns.mean() + stats.norm.ppf(0.05) * market_returns.std(ddof=1)

    assert value_at_risk(market_returns, 0.95, VaRMethod.PARAMETRIC).iloc[-1] == pytest.approx(expected)


def test_cornish_fisher_var_matches_formula(market_returns):
    z = stats.norm.ppf(0.01)
    s, k = stats.skew(market_returns, bias=False), stats.kurtosis(market_returns, bias=False)
    z_cf = z + (z**2 - 1) * s / 6 + (z**3 - 3 * z) * k / 24 - (2 * z**3 - 5 * z) * s**2 / 36
    expected = market_returns.mean() + z_cf * market_returns.std(ddof=1)

    assert value_at_risk(market_returns, 0.99, VaRMethod.CORNISH_FISHER).iloc[-1] == pytest.approx(expected)


def test_cornish_fisher_reduces_to_parametric_for_a_normal_sample(normal_returns):
    parametric = _whole_sample(value_at_risk, normal_returns, 0.99, VaRMethod.PARAMETRIC)
    cornish_fisher = _whole_sample(value_at_risk, normal_returns, 0.99, VaRMethod.CORNISH_FISHER)

    assert cornish_fisher == pytest.approx(parametric, abs=2e-4)


def test_cornish_fisher_is_more_conservative_for_negatively_skewed_returns():
    # many small gains and a few large losses: the normal model understates the left tail
    rng = np.random.default_rng(3)
    r = _daily(np.where(rng.random(5000) < 0.03, rng.normal(-0.06, 0.02, 5000), rng.normal(0.004, 0.006, 5000)))

    assert stats.skew(r) < -1
    assert (
        value_at_risk(r, 0.99, VaRMethod.CORNISH_FISHER).iloc[-1]
        < value_at_risk(r, 0.99, VaRMethod.PARAMETRIC).iloc[-1]
    )


@pytest.mark.parametrize('confidence', [0.90, 0.95, 0.99])
def test_var_is_calibrated_on_a_normal_sample(normal_returns, confidence):
    theoretical = 0.0004 + stats.norm.ppf(1 - confidence) * 0.01

    for method in (VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC):
        assert _whole_sample(value_at_risk, normal_returns, confidence, method) == pytest.approx(theoretical, abs=3e-4)
    threshold = _whole_sample(value_at_risk, normal_returns, confidence)
    assert (normal_returns < threshold).mean() == pytest.approx(1 - confidence, abs=2e-3)


@pytest.mark.parametrize('method', list(VaRMethod))
def test_var_is_monotonic_in_confidence(market_returns, method):
    levels = [0.90, 0.95, 0.975, 0.99]
    values = [value_at_risk(market_returns, c, method).iloc[-1] for c in levels]

    assert values == sorted(values, reverse=True)


@pytest.mark.parametrize('method', [VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC])
def test_var_scales_with_the_returns(market_returns, method):
    assert value_at_risk(market_returns * 3, 0.95, method).iloc[-1] == pytest.approx(
        3 * value_at_risk(market_returns, 0.95, method).iloc[-1]
    )


def test_var_of_a_constant_series_is_the_constant():
    r = _daily([0.01] * 10)

    for method in VaRMethod:
        assert value_at_risk(r, 0.95, method).iloc[-1] == pytest.approx(0.01)


def test_var_accepts_the_method_value(market_returns):
    assert (
        value_at_risk(market_returns, 0.95, 'parametric').iloc[-1]
        == value_at_risk(market_returns, 0.95, VaRMethod.PARAMETRIC).iloc[-1]
    )


@pytest.mark.parametrize('confidence', [0, 1, -0.5, 1.5])
def test_var_rejects_invalid_confidence(market_returns, confidence):
    with pytest.raises(MqValueError, match='confidence'):
        value_at_risk(market_returns, confidence)
    with pytest.raises(MqValueError, match='confidence'):
        expected_shortfall(market_returns, confidence)


# ----------------------------------------------------------------------------------------------------------------------
# Expected shortfall
# ----------------------------------------------------------------------------------------------------------------------


def test_historical_expected_shortfall_is_the_tail_mean(market_returns):
    cutoff = np.quantile(market_returns, 0.05)

    assert expected_shortfall(market_returns, 0.95).iloc[-1] == pytest.approx(
        market_returns[market_returns <= cutoff].mean()
    )


def test_parametric_expected_shortfall_matches_formula(market_returns):
    z = stats.norm.ppf(0.05)
    expected = market_returns.mean() - market_returns.std(ddof=1) * stats.norm.pdf(z) / 0.05

    assert expected_shortfall(market_returns, 0.95, VaRMethod.PARAMETRIC).iloc[-1] == pytest.approx(expected)


def test_parametric_expected_shortfall_agrees_with_the_empirical_tail(normal_returns):
    parametric = _whole_sample(expected_shortfall, normal_returns, 0.975, VaRMethod.PARAMETRIC)
    historical = _whole_sample(expected_shortfall, normal_returns, 0.975, VaRMethod.HISTORICAL)

    assert parametric == pytest.approx(historical, abs=3e-4)


@pytest.mark.parametrize('method', [VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC])
def test_expected_shortfall_is_never_better_than_var(market_returns, method):
    for confidence in (0.9, 0.95, 0.99):
        assert (
            expected_shortfall(market_returns, confidence, method).iloc[-1]
            <= value_at_risk(market_returns, confidence, method).iloc[-1]
        )


def test_expected_shortfall_rejects_cornish_fisher(market_returns):
    with pytest.raises(MqValueError, match='Cornish-Fisher'):
        expected_shortfall(market_returns, 0.95, VaRMethod.CORNISH_FISHER)


# ----------------------------------------------------------------------------------------------------------------------
# Windows
# ----------------------------------------------------------------------------------------------------------------------


def test_default_window_is_expanding(market_returns):
    result = value_at_risk(market_returns[:50], 0.9)

    assert result.iloc[-1] == pytest.approx(np.quantile(market_returns[:50], 0.1))
    assert result.iloc[9] == pytest.approx(np.quantile(market_returns[:10], 0.1))
    assert len(result) == 50


def test_int_window_matches_a_manual_rolling_calculation(market_returns):
    result = value_at_risk(market_returns, 0.95, w=60)

    # an int window also ramps up over that many observations, like the other timeseries functions
    expected = market_returns.rolling(60).apply(lambda a: np.quantile(a, 0.05), raw=True).dropna().iloc[1:]
    assert_series_equal(result, expected, check_freq=False, rtol=1e-12)


def test_window_ramp_drops_the_initial_observations(market_returns):
    assert len(value_at_risk(market_returns, 0.95, w=Window(60, 30))) == len(market_returns) - 30
    assert len(value_at_risk(market_returns, 0.95, w=Window(60, 0))) == len(market_returns)


def test_window_larger_than_the_series():
    # like the rest of the package: an int window is also the ramp up, which cannot exceed the series
    with pytest.raises(MqValueError, match='Ramp'):
        value_at_risk(SMALL, 0.95, w=100)

    assert value_at_risk(SMALL, 0.95, w=Window(100, 0)).empty


def test_relative_date_window_matches_a_manual_calculation(market_returns):
    result = value_at_risk(market_returns, 0.95, w='3m')

    for idx in (market_returns.index[100], market_returns.index[400], market_returns.index[-1]):
        window = market_returns[(market_returns.index > idx - pd.DateOffset(months=3)) & (market_returns.index <= idx)]
        assert result.loc[idx] == pytest.approx(np.quantile(window, 0.05))


def test_relative_date_window_needs_a_date_index():
    with pytest.raises(TypeError, match='dates'):
        value_at_risk(pd.Series([0.01, -0.02, 0.03]), 0.95, w='1m')


def test_missing_values_are_ignored():
    clean = _daily([0.01, -0.02, 0.03, -0.04, 0.02])
    with_gaps = clean.copy()
    with_gaps.iloc[1] = np.nan

    assert value_at_risk(with_gaps, 0.9).iloc[-1] == pytest.approx(np.quantile(with_gaps.dropna(), 0.1))


def test_empty_input_gives_empty_output():
    assert value_at_risk(pd.Series(dtype=float), 0.95).empty
    assert ulcer_index(pd.Series(dtype=float)).empty


def test_short_windows_give_nan_when_the_estimator_is_undefined():
    r = _daily([0.01, -0.02, 0.03])

    assert np.isnan(value_at_risk(r, 0.95, VaRMethod.PARAMETRIC).iloc[0])  # needs two observations
    assert np.isnan(value_at_risk(r, 0.95, VaRMethod.CORNISH_FISHER).iloc[-1])  # needs four observations


# ----------------------------------------------------------------------------------------------------------------------
# Annualization
# ----------------------------------------------------------------------------------------------------------------------


def test_annualization_is_inferred_from_daily_data():
    assert_series_equal(sortino_ratio(SMALL), sortino_ratio(SMALL, annualization_factor=252))


def test_annualization_is_inferred_from_weekly_data():
    weekly = pd.Series(SMALL.to_numpy(), index=pd.date_range('2021-01-03', periods=len(SMALL), freq='W'))

    assert_series_equal(downside_deviation(weekly), downside_deviation(weekly, annualization_factor=52))


def test_infer_periods_per_year():
    monthly = pd.Series(range(12), index=pd.date_range('2021-01-31', periods=12, freq='ME'))

    assert infer_periods_per_year(SMALL) == 252
    assert infer_periods_per_year(monthly) == 12
    assert infer_periods_per_year(monthly, 4) == 4
    with pytest.raises(MqValueError):
        infer_periods_per_year(pd.Series([1.0, 2.0]))


def test_annualization_needs_a_factor_for_a_non_date_index():
    with pytest.raises(MqValueError, match='annualization_factor'):
        sortino_ratio(pd.Series([0.01, -0.02, 0.03]))

    assert not sortino_ratio(pd.Series([0.01, -0.02, 0.03]), annualization_factor=1).empty


def test_annualization_rejects_a_non_positive_factor():
    with pytest.raises(MqValueError, match='positive'):
        downside_deviation(SMALL, annualization_factor=0)


# ----------------------------------------------------------------------------------------------------------------------
# Relative measures
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def portfolio_and_benchmark():
    rng = np.random.default_rng(11)
    benchmark = _daily(rng.normal(0.0004, 0.01, 500))
    portfolio = benchmark + _daily(rng.normal(0.0002, 0.003, 500))
    return portfolio, benchmark


def test_tracking_error_is_the_annualized_std_of_active_returns(portfolio_and_benchmark):
    portfolio, benchmark = portfolio_and_benchmark
    active = portfolio - benchmark

    assert tracking_error(portfolio, benchmark).iloc[-1] == pytest.approx(active.std(ddof=1) * math.sqrt(252))


def test_information_ratio_is_active_return_per_unit_of_tracking_error(portfolio_and_benchmark):
    portfolio, benchmark = portfolio_and_benchmark
    active = portfolio - benchmark

    expected = active.mean() / active.std(ddof=1) * math.sqrt(252)

    assert information_ratio(portfolio, benchmark).iloc[-1] == pytest.approx(expected)
    assert expected > 0


def test_relative_measures_use_only_common_dates(portfolio_and_benchmark):
    portfolio, benchmark = portfolio_and_benchmark

    trimmed = tracking_error(portfolio, benchmark.iloc[100:])
    expected = tracking_error(portfolio.iloc[100:], benchmark.iloc[100:])

    assert_series_equal(trimmed, expected)


def test_rolling_tracking_error(portfolio_and_benchmark):
    portfolio, benchmark = portfolio_and_benchmark
    active = portfolio - benchmark

    result = tracking_error(portfolio, benchmark, w=60)

    expected = (active.rolling(60).std() * math.sqrt(252)).dropna().iloc[1:]  # the int window is also the ramp up
    assert_series_equal(result, expected, check_freq=False, check_names=False)


def test_a_portfolio_identical_to_its_benchmark_has_no_information_ratio(portfolio_and_benchmark):
    _, benchmark = portfolio_and_benchmark

    assert tracking_error(benchmark, benchmark).iloc[-1] == 0
    assert information_ratio(benchmark, benchmark).isna().all()


# ----------------------------------------------------------------------------------------------------------------------
# Kupiec backtest
# ----------------------------------------------------------------------------------------------------------------------


def _reference_lr(n_obs: int, exceedances: int, p: float) -> float:
    """Independent implementation of the Kupiec likelihood ratio using math.log"""

    def log_likelihood(rate: float) -> float:
        terms = 0.0
        if n_obs - exceedances:
            terms += (n_obs - exceedances) * math.log(1 - rate)
        if exceedances:
            terms += exceedances * math.log(rate)
        return terms

    return -2 * (log_likelihood(p) - log_likelihood(exceedances / n_obs))


@pytest.mark.parametrize('exceedances', [0, 1, 5, 12, 25, 60, 250])
def test_kupiec_statistic_matches_the_reference_implementation(exceedances):
    n_obs = 250
    returns = _daily([-0.02] * exceedances + [0.01] * (n_obs - exceedances))
    forecast = _daily([-0.01] * n_obs)

    result = var_backtest(returns, forecast, confidence=0.95)

    expected_lr = _reference_lr(n_obs, exceedances, 0.05)
    assert result.exceedances == exceedances
    assert result.observations == n_obs
    assert result.lr_statistic == pytest.approx(expected_lr, abs=1e-9)
    assert result.p_value == pytest.approx(stats.chi2.sf(expected_lr, 1))


def test_kupiec_does_not_reject_the_expected_number_of_exceedances():
    returns = _daily([-0.02] * 25 + [0.01] * 475)

    result = var_backtest(returns, _daily([-0.01] * 500), confidence=0.95)

    assert result.observed_rate == pytest.approx(0.05)
    assert result.lr_statistic == pytest.approx(0, abs=1e-9)
    assert result.p_value == pytest.approx(1)
    assert not result.reject


@pytest.mark.parametrize('exceedances', [0, 100])
def test_kupiec_rejects_too_few_and_too_many_exceedances(exceedances):
    returns = _daily([-0.02] * exceedances + [0.01] * (500 - exceedances))

    assert var_backtest(returns, _daily([-0.01] * 500), confidence=0.95).reject


def test_kupiec_accepts_a_well_calibrated_model_and_rejects_a_misspecified_one():
    rng = np.random.default_rng(5)
    returns = _daily(rng.normal(0, 0.01, 2000))
    calibrated = value_at_risk(returns, 0.99, VaRMethod.PARAMETRIC, w=500).shift(1)
    # the same forecast with the volatility understated by 40%
    understated = calibrated * 0.6

    assert not var_backtest(returns, calibrated, 0.99).reject
    assert var_backtest(returns, understated, 0.99).reject


def test_kupiec_significance_controls_rejection():
    returns = _daily([-0.02] * 30 + [0.01] * 470)  # 6% exceedances against 5% expected: p-value is about 0.28

    lenient = var_backtest(returns, _daily([-0.01] * 500), 0.95, significance=0.5)
    strict = var_backtest(returns, _daily([-0.01] * 500), 0.95, significance=0.05)

    assert lenient.reject and not strict.reject


def test_kupiec_counts_only_returns_strictly_worse_than_the_var():
    returns = _daily([-0.01, -0.01, -0.0100001, 0.02])
    forecast = _daily([-0.01] * 4)

    assert var_backtest(returns, forecast).exceedances == 1  # a return equal to the VaR is not a breach


def test_kupiec_ignores_dates_without_a_forecast():
    returns = _daily([-0.02] * 5 + [0.01] * 95)
    forecast = _daily([-0.01] * 100)
    forecast.iloc[:20] = np.nan

    assert var_backtest(returns, forecast, 0.95).observations == 80


def test_kupiec_needs_overlapping_data():
    with pytest.raises(MqValueError, match='overlapping'):
        var_backtest(_daily([0.01, 0.02]), _daily([-0.01, -0.01], start='2030-01-01'))


def test_kupiec_rejects_invalid_significance():
    with pytest.raises(MqValueError, match='significance'):
        var_backtest(SMALL, SMALL, significance=1.5)


def test_kupiec_result_is_immutable():
    result = var_backtest(_daily([0.01, -0.02]), _daily([-0.01, -0.01]))

    with pytest.raises(AttributeError):
        result.reject = True


# ----------------------------------------------------------------------------------------------------------------------
# Christoffersen independence and Basel traffic lights
# ----------------------------------------------------------------------------------------------------------------------


def _hits_series(pattern: str) -> tuple[pd.Series, pd.Series]:
    """Returns and a constant VaR forecast that produce exactly the given breach pattern ('x' is a breach)"""
    returns = _daily([-0.02 if c == 'x' else 0.01 for c in pattern])
    return returns, _daily([-0.01] * len(pattern))


def _reference_independence_lr(pattern: str) -> float:
    """Independent implementation with plain math.log, following the textbook formulation"""
    hits = [1 if c == 'x' else 0 for c in pattern]
    n = {(a, b): 0 for a in (0, 1) for b in (0, 1)}
    for a, b in zip(hits[:-1], hits[1:]):
        n[(a, b)] += 1

    def log_likelihood(terms):
        return sum(count * math.log(prob) for count, prob in terms if count > 0)

    pi0 = n[(0, 1)] / (n[(0, 0)] + n[(0, 1)])
    pi1 = n[(1, 1)] / (n[(1, 0)] + n[(1, 1)]) if n[(1, 0)] + n[(1, 1)] else 0.0
    pi = (n[(0, 1)] + n[(1, 1)]) / sum(n.values())
    null = log_likelihood([(n[(0, 0)] + n[(1, 0)], 1 - pi), (n[(0, 1)] + n[(1, 1)], pi)])
    alternative = log_likelihood([(n[(0, 0)], 1 - pi0), (n[(0, 1)], pi0), (n[(1, 0)], 1 - pi1), (n[(1, 1)], pi1)])
    return -2 * (null - alternative)


@pytest.mark.parametrize(
    'pattern',
    [
        '..x..x...x....x..x.....x...x..',  # scattered
        '.........xxxxx.........xxxxx...',  # clustered
        'x.x.x.x.x.x.x.x.x.x.x.x.x.x.x.',  # alternating: exceedances repel each other
        '....xx.....x..xx.....x.xxx.....',
    ],
)
def test_independence_statistic_matches_the_reference_implementation(pattern):
    returns, forecast = _hits_series(pattern)

    result = var_independence_test(returns, forecast, confidence=0.95)

    expected = _reference_independence_lr(pattern)
    assert result.independence_lr == pytest.approx(expected, abs=1e-9)
    assert result.independence_p_value == pytest.approx(stats.chi2.sf(expected, 1))
    assert result.exceedances == pattern.count('x')
    assert result.n00 + result.n01 + result.n10 + result.n11 == len(pattern) - 1


def test_transition_counts():
    returns, forecast = _hits_series('.xx..x.')

    result = var_independence_test(returns, forecast)

    assert (result.n00, result.n01, result.n10, result.n11) == (1, 2, 2, 1)


def _random_hits(rate: float, n: int, seed: int) -> tuple[pd.Series, pd.Series]:
    """Independent exceedances: each period breaches with the given probability"""
    hits = np.random.default_rng(seed).random(n) < rate
    return _hits_series(''.join('x' if h else '.' for h in hits))


def test_clustered_exceedances_are_rejected_but_independent_ones_are_not():
    clustered, forecast = _hits_series(('.' * 45 + 'x' * 5) * 6)
    independent, forecast_independent = _random_hits(0.1, 300, seed=4)

    assert var_independence_test(clustered, forecast, 0.9).independence_reject
    assert not var_independence_test(independent, forecast_independent, 0.9).independence_reject


def test_perfectly_regular_exceedances_are_not_independent_either():
    # every tenth period, never two in a row: as far from independent as clustering, in the other direction
    regular, forecast = _hits_series(('.' * 9 + 'x') * 30)

    assert var_independence_test(regular, forecast, 0.9).independence_reject


def test_independence_is_blind_to_frequency_but_conditional_coverage_is_not():
    # independent exceedances 30% of the time: far too frequent for a 95% model, yet not clustered
    returns, forecast = _random_hits(0.3, 500, seed=1)

    result = var_independence_test(returns, forecast, 0.95)

    assert not result.independence_reject
    assert result.conditional_coverage_reject
    assert result.conditional_coverage_lr >= result.independence_lr


def _markov_hits(stay: float, enter: float, n: int, seed: int) -> tuple[pd.Series, pd.Series]:
    """Exceedances that cluster: P(breach | breach yesterday) = stay, P(breach | no breach yesterday) = enter"""
    rng = np.random.default_rng(seed)
    hits = [False]
    for _ in range(n - 1):
        hits.append(bool(rng.random() < (stay if hits[-1] else enter)))
    return _hits_series(''.join('x' if h else '.' for h in hits))


def test_independence_test_has_the_right_size_and_power():
    """Over many simulated samples: about 5% false rejections when independent, and it detects clustering"""
    seeds = range(400)

    false_rejections = sum(
        var_independence_test(*_random_hits(0.3, 500, seed), confidence=0.95).independence_reject for seed in seeds
    )
    detections = sum(
        var_independence_test(*_markov_hits(0.6, 0.1, 500, seed), confidence=0.95).independence_reject for seed in seeds
    )

    assert 0.02 <= false_rejections / len(seeds) <= 0.09  # nominal 5%
    assert detections / len(seeds) > 0.95


def test_conditional_coverage_adds_the_kupiec_statistic():
    pattern = '....xx.....x..xx.....x.xxx.....' * 10
    returns, forecast = _hits_series(pattern)

    ind = var_independence_test(returns, forecast, 0.9)
    pof = var_backtest(returns.iloc[1:], forecast.iloc[1:], 0.9)  # the transitions cover all but the first period

    assert ind.conditional_coverage_lr == pytest.approx(ind.independence_lr + pof.lr_statistic, rel=0.02)
    assert ind.conditional_coverage_p_value == pytest.approx(stats.chi2.sf(ind.conditional_coverage_lr, 2))


@pytest.mark.parametrize('pattern', ['.' * 50, 'x' * 50])
def test_independence_is_untestable_without_a_mix_of_states(pattern):
    returns, forecast = _hits_series(pattern)

    result = var_independence_test(returns, forecast, 0.95)

    assert result.independence_lr == 0 and result.independence_p_value == 1 and not result.independence_reject


def test_independence_test_validates_its_input():
    returns, forecast = _hits_series('..x..')

    with pytest.raises(MqValueError, match='confidence'):
        var_independence_test(returns, forecast, confidence=1.2)
    with pytest.raises(MqValueError, match='significance'):
        var_independence_test(returns, forecast, significance=0)
    with pytest.raises(MqValueError, match='overlapping'):
        var_independence_test(returns, _daily([-0.01] * 5, start='2031-01-01'))
    with pytest.raises(MqValueError, match='two'):
        var_independence_test(returns.iloc[:1], forecast.iloc[:1])


def test_a_model_that_reacts_slowly_to_a_volatility_shift_fails_conditional_coverage():
    rng = np.random.default_rng(21)
    calm, turbulent = rng.normal(0, 0.005, 500), rng.normal(0, 0.02, 250)
    returns = _daily(np.concatenate([calm, turbulent]))
    forecast = value_at_risk(returns, 0.95, VaRMethod.PARAMETRIC, w=Window(250, 249)).shift(1)

    result = var_independence_test(returns, forecast, 0.95)

    # what the data show: too many exceedances overall; they are not strongly serially dependent in this sample
    assert result.exceedances > 1.5 * 0.05 * result.observations
    assert result.conditional_coverage_reject


@pytest.mark.parametrize(
    'exceedances, zone',
    [(0, 'green'), (4, 'green'), (5, 'yellow'), (9, 'yellow'), (10, 'red'), (25, 'red')],
)
def test_traffic_light_reproduces_the_basel_table_for_250_days_at_99_percent(exceedances, zone):
    assert traffic_light_zone(exceedances, 250, 0.99).zone == TrafficLightZone(zone)


def test_traffic_light_cumulative_probabilities_match_the_published_values():
    # Basel Committee, "Supervisory framework for the use of backtesting", table 2
    for exceedances, published in [(0, 0.0811), (4, 0.8922), (5, 0.9588), (9, 0.9997), (10, 0.9999)]:
        assert traffic_light_zone(exceedances, 250, 0.99).cumulative_probability == pytest.approx(published, abs=6e-5)


def test_traffic_light_scales_with_the_window_and_confidence():
    expected_at_95 = traffic_light_zone(0, 500, 0.95)

    assert expected_at_95.expected_exceedances == pytest.approx(25)
    assert traffic_light_zone(25, 500, 0.95).zone == TrafficLightZone.GREEN
    assert traffic_light_zone(60, 500, 0.95).zone == TrafficLightZone.RED


def test_traffic_light_validates_its_input():
    with pytest.raises(MqValueError):
        traffic_light_zone(5, 0)
    with pytest.raises(MqValueError):
        traffic_light_zone(11, 10)
    with pytest.raises(MqValueError):
        traffic_light_zone(-1, 10)
    with pytest.raises(MqValueError, match='confidence'):
        traffic_light_zone(1, 10, confidence=1)


# ----------------------------------------------------------------------------------------------------------------------
# Summary
# ----------------------------------------------------------------------------------------------------------------------


def test_risk_summary_is_consistent_with_the_series_functions(market_returns):
    summary = risk_summary(market_returns, confidence=0.95)

    assert summary.observations == len(market_returns)
    assert summary.periods_per_year == 252
    assert summary.var_historical == pytest.approx(value_at_risk(market_returns, 0.95).iloc[-1])
    assert summary.var_parametric == pytest.approx(value_at_risk(market_returns, 0.95, VaRMethod.PARAMETRIC).iloc[-1])
    assert summary.var_cornish_fisher == pytest.approx(
        value_at_risk(market_returns, 0.95, VaRMethod.CORNISH_FISHER).iloc[-1]
    )
    assert summary.expected_shortfall_historical == pytest.approx(expected_shortfall(market_returns, 0.95).iloc[-1])
    assert summary.downside_deviation == pytest.approx(downside_deviation(market_returns).iloc[-1])
    assert summary.sortino_ratio == pytest.approx(sortino_ratio(market_returns).iloc[-1])
    assert summary.omega_ratio == pytest.approx(omega_ratio(market_returns).iloc[-1])
    assert summary.skewness == pytest.approx(stats.skew(market_returns, bias=False))
    assert summary.excess_kurtosis == pytest.approx(stats.kurtosis(market_returns, bias=False))
    assert summary.annualized_volatility == pytest.approx(market_returns.std(ddof=1) * math.sqrt(252))
    assert summary.best_period == market_returns.max() and summary.worst_period == market_returns.min()


def test_risk_summary_drawdown_statistics_use_compounded_growth(market_returns):
    growth = pd.concat(
        [pd.Series([1.0], index=[market_returns.index[0] - pd.Timedelta(days=1)]), (1 + market_returns).cumprod()]
    )

    summary = risk_summary(market_returns)

    assert summary.max_drawdown == pytest.approx(drawdown(growth).min())
    assert summary.ulcer_index == pytest.approx(ulcer_index(growth).iloc[-1])
    assert summary.annualized_return == pytest.approx(growth.iloc[-1] ** (252 / len(market_returns)) - 1)
    assert summary.calmar_ratio == pytest.approx(summary.annualized_return / abs(summary.max_drawdown), rel=0.02)


def test_risk_summary_marks_undefined_statistics_as_none():
    summary = risk_summary(_daily([0.01, 0.02, 0.005, 0.03, 0.01]))

    assert summary.sortino_ratio is None and summary.omega_ratio is None and summary.calmar_ratio is None
    assert summary.max_drawdown == 0
    assert summary.var_historical is not None


def test_risk_summary_to_dict_is_json_friendly(market_returns):
    import json

    payload = risk_summary(market_returns).to_dict()

    assert json.loads(json.dumps(payload, allow_nan=False)) == payload


@pytest.mark.parametrize(
    'series, message',
    [
        (_daily([0.01]), 'two returns'),
        (_daily([0.01, -1.0, 0.02]), '-100%'),
    ],
)
def test_risk_summary_validates_its_input(series, message):
    with pytest.raises(MqValueError, match=message):
        risk_summary(series)


# ----------------------------------------------------------------------------------------------------------------------
# Package hygiene
# ----------------------------------------------------------------------------------------------------------------------


def test_module_does_not_shadow_the_report_based_measures():
    """These names exist in timeseries.measures_reports; the module must not be star-imported over them"""
    import gs_quant.timeseries as ts

    for name in ('sortino_ratio', 'calmar_ratio', 'tracking_error', 'information_ratio'):
        assert getattr(ts, name) is getattr(measures_reports, name)
