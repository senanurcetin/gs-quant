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

import time

import numpy as np
import pandas as pd
import pytest

from gs_quant.timeseries.econometrics import (
    _max_drawdown_date_window,
    _max_drawdown_date_window_reference,
    max_drawdown,
)

WINDOWS = ['5d', '2w', '1m', '3m', '1y']


def _prices(n: int, seed: int, start: str = '2015-01-01') -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.02, n)), index=pd.bdate_range(start, periods=n))


def _assert_same(fast: pd.Series, reference: pd.Series):
    pd.testing.assert_index_equal(fast.index, reference.index)
    np.testing.assert_allclose(fast.to_numpy(), reference.to_numpy(), rtol=1e-12, atol=0, equal_nan=True)


@pytest.mark.parametrize('window', WINDOWS)
@pytest.mark.parametrize('seed', range(5))
def test_matches_the_reference_on_random_prices(window, seed):
    prices = _prices(300, seed)
    offset = {
        '5d': pd.DateOffset(days=5),
        '2w': pd.DateOffset(weeks=2),
        '1m': pd.DateOffset(months=1),
        '3m': pd.DateOffset(months=3),
        '1y': pd.DateOffset(years=1),
    }[window]

    _assert_same(_max_drawdown_date_window(prices, offset), _max_drawdown_date_window_reference(prices, offset))


def test_matches_the_reference_with_missing_values():
    prices = _prices(400, seed=11)
    rng = np.random.default_rng(3)
    prices.iloc[rng.choice(400, 60, replace=False)] = np.nan
    prices.iloc[:5] = np.nan  # a window that is entirely missing

    for months in (1, 3):
        offset = pd.DateOffset(months=months)
        _assert_same(_max_drawdown_date_window(prices, offset), _max_drawdown_date_window_reference(prices, offset))


def test_matches_the_reference_with_zero_and_negative_values():
    values = np.array([0.0, 0.0, 5.0, -3.0, 4.0, 0.0, -1.0, 2.0, 2.0, 0.0] * 20)
    prices = pd.Series(values, index=pd.bdate_range('2020-01-01', periods=len(values)))
    offset = pd.DateOffset(weeks=2)

    _assert_same(_max_drawdown_date_window(prices, offset), _max_drawdown_date_window_reference(prices, offset))


def test_matches_the_reference_on_irregular_dates():
    rng = np.random.default_rng(8)
    dates = pd.to_datetime('2019-01-01') + pd.to_timedelta(np.sort(rng.choice(900, 250, replace=False)), unit='D')
    prices = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.02, 250)), index=dates)

    for offset in (pd.DateOffset(days=30), pd.DateOffset(months=3), pd.DateOffset(years=1)):
        _assert_same(_max_drawdown_date_window(prices, offset), _max_drawdown_date_window_reference(prices, offset))


def test_a_series_that_is_not_sorted_or_unique_uses_the_reference_implementation(monkeypatch):
    prices = _prices(60, seed=1)
    shuffled = prices.iloc[np.random.default_rng(0).permutation(60)]
    calls = []
    original = _max_drawdown_date_window_reference
    monkeypatch.setattr(
        'gs_quant.timeseries.econometrics._max_drawdown_date_window_reference',
        lambda *a: calls.append(1) or original(*a),
    )

    _max_drawdown_date_window(shuffled, pd.DateOffset(months=1))

    assert calls, 'the sorted-index fast path is not valid for an unsorted index'


def test_public_function_is_unchanged_for_relative_date_windows():
    prices = _prices(500, seed=4)

    result = max_drawdown(prices, '3m')

    reference = _max_drawdown_date_window_reference(prices, pd.DateOffset(months=3))
    kept = reference.loc[result.index]
    np.testing.assert_allclose(result.to_numpy(), kept.to_numpy(), equal_nan=True)
    assert (result <= 0).all() and result.index[0] > prices.index[0]  # the ramp up is still applied


def test_hand_calculated_example():
    prices = pd.Series(
        [100, 120, 90, 110], index=pd.to_datetime(['2024-01-01', '2024-01-02', '2024-01-03', '2024-01-04'])
    )

    result = _max_drawdown_date_window(prices, pd.DateOffset(days=10))

    # the peak so far is 120, then 90 is a 25% fall, and it is still the worst in the window afterwards
    assert result.round(6).tolist() == [0.0, 0.0, -0.25, -0.25]


def test_is_linear_not_quadratic_in_the_number_of_dates():
    # the reference took about 1.7s for 4,000 dates; the fast path must stay far below what O(n^2) would need
    prices = _prices(20000, seed=2, start='1990-01-01')

    started = time.perf_counter()
    _max_drawdown_date_window(prices, pd.DateOffset(months=3))
    elapsed = time.perf_counter() - started

    assert elapsed < 5, f'{elapsed:.1f}s for 20,000 dates'
