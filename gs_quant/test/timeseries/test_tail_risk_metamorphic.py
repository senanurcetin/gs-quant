"""
Copyright 2026 Senanur Çetin.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

"""Numerical metamorphic tests for financial tail risk on synthetic returns."""

import numpy as np
import pandas as pd
import pytest

from gs_quant.timeseries.helper import Window
from gs_quant.timeseries.risk_metrics import VaRMethod, expected_shortfall, value_at_risk


def _returns(values):
    return pd.Series(values, index=pd.bdate_range('2026-01-02', periods=len(values)), dtype=float)


def _last(fn, returns, confidence, method):
    # Compute one final, complete window rather than running an expanding O(n^2) series.
    n = len(returns)
    return fn(returns, confidence, method, w=Window(n, n - 1)).iloc[-1]


@pytest.fixture
def sample():
    # Deterministic, non-normal, both winning and losing returns; no external data access.
    return _returns([-0.075, -0.030, -0.018, -0.01, -0.003,
                     0.0, 0.004, 0.009, 0.018, 0.029, 0.038, 0.061])


@pytest.mark.parametrize('method', list(VaRMethod))
@pytest.mark.parametrize('confidence', [0.90, 0.95, 0.99])
def test_var_translation_equivariance(sample, method, confidence):
    """Adding a fixed return premium must shift VaR by precisely that premium."""
    baseline = _last(value_at_risk, sample, confidence, method)
    shifted = _last(value_at_risk, sample + 0.01, confidence, method)
    assert shifted == pytest.approx(baseline + 0.01, abs=1e-10)


@pytest.mark.parametrize('method', [VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC])
@pytest.mark.parametrize('confidence', [0.90, 0.95, 0.99])
def test_expected_shortfall_translation_equivariance(sample, method, confidence):
    baseline = _last(expected_shortfall, sample, confidence, method)
    shifted = _last(expected_shortfall, sample - 0.01, confidence, method)
    assert shifted == pytest.approx(baseline - 0.01, abs=1e-10)


@pytest.mark.parametrize('method', list(VaRMethod))
def test_var_positive_homogeneity(sample, method):
    baseline = _last(value_at_risk, sample, 0.95, method)
    assert _last(value_at_risk, sample * 2.5, 0.95, method) == pytest.approx(
        baseline * 2.5, abs=1e-10
    )


@pytest.mark.parametrize('method', [VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC])
def test_es_positive_homogeneity(sample, method):
    baseline = _last(expected_shortfall, sample, 0.95, method)
    assert _last(expected_shortfall, sample * 2.5, 0.95, method) == pytest.approx(
        baseline * 2.5, abs=1e-10
    )


@pytest.mark.parametrize('method', list(VaRMethod))
def test_var_is_order_invariant_for_a_complete_window(sample, method):
    """A full-window quantile must not depend on input observation order."""
    reordered = pd.Series(sample.to_numpy()[::-1], index=sample.index)
    assert _last(value_at_risk, sample, 0.95, method) == pytest.approx(
        _last(value_at_risk, reordered, 0.95, method), abs=1e-10
    )


@pytest.mark.parametrize('method', [VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC])
def test_es_is_order_invariant_for_a_complete_window(sample, method):
    reordered = pd.Series(sample.to_numpy()[::-1], index=sample.index)
    assert _last(expected_shortfall, sample, 0.95, method) == pytest.approx(
        _last(expected_shortfall, reordered, 0.95, method), abs=1e-10
    )


@pytest.mark.parametrize('method', [VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC])
def test_nan_observations_are_excluded_from_tail_statistics(sample, method):
    with_missing = pd.concat([sample, pd.Series([np.nan], index=[pd.Timestamp('2026-03-01')])])
    assert _last(value_at_risk, with_missing, 0.95, method) == pytest.approx(
        _last(value_at_risk, sample, 0.95, method), abs=1e-10
    )
    assert _last(expected_shortfall, with_missing, 0.95, method) == pytest.approx(
        _last(expected_shortfall, sample, 0.95, method), abs=1e-10
    )


@pytest.mark.parametrize('method', [VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC])
def test_single_extreme_loss_makes_tail_risk_more_negative(sample, method):
    stressed = sample.copy()
    stressed.iloc[0] = -0.25
    # The worst 5% historical tail includes the extreme event; so does the
    # parametric estimate through increased dispersion and a shifted mean.
    assert _last(value_at_risk, stressed, 0.95, method) < _last(
        value_at_risk, sample, 0.95, method
    )
    assert _last(expected_shortfall, stressed, 0.95, method) < _last(
        expected_shortfall, sample, 0.95, method
    )


def test_zero_length_inputs_return_empty_series():
    empty = pd.Series(dtype=float)
    assert value_at_risk(empty).empty
    assert expected_shortfall(empty).empty
