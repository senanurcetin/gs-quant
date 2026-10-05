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

pytest.importorskip('starlette')
pytest.importorskip('pydantic')

from scipy import stats  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from gs_quant.apps.risk_dashboard import analysis  # noqa: E402
from gs_quant.apps.risk_dashboard.analysis import AnalysisError  # noqa: E402
from gs_quant.apps.risk_dashboard.app import create_app  # noqa: E402
from gs_quant.apps.risk_dashboard.settings import Settings  # noqa: E402
from gs_quant.timeseries.risk_metrics import VaRMethod  # noqa: E402


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(database=tmp_path / 'runs.db')))


def dated(values, start='2024-01-01') -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)))


def random_returns(n=400, seed=1, scale=0.01) -> pd.Series:
    return dated(np.random.default_rng(seed).normal(0, scale, n))


class TestHorizon:
    def test_scales_the_one_period_figures_by_the_square_root_of_time(self):
        result = analysis.analyze(random_returns(), 0.95, VaRMethod.HISTORICAL, 100, horizon=10)

        one_period = analysis.headline_figures(result['summary'], VaRMethod.HISTORICAL)
        assert result['horizon']['periods'] == 10 and result['horizon']['rule'] == 'square_root_of_time'
        assert result['horizon']['var'] == pytest.approx(one_period['var'] * math.sqrt(10), abs=2e-6)
        assert result['horizon']['expected_shortfall'] == pytest.approx(
            one_period['expected_shortfall'] * math.sqrt(10), abs=2e-6
        )
        assert result['settings']['horizon'] == 10

    def test_one_period_equals_the_headline_and_adds_no_assumption(self):
        result = analysis.analyze(random_returns(), 0.95, VaRMethod.PARAMETRIC, 100)

        assert result['horizon']['var'] == analysis.headline(result)['var']
        assert not any('square root' in a for a in result['assumptions'])

    def test_a_longer_horizon_says_how_it_was_scaled(self):
        result = analysis.analyze(random_returns(), 0.95, VaRMethod.HISTORICAL, 100, horizon=5)

        assert any('square root of the horizon' in a and '5-period' in a for a in result['assumptions'])

    def test_a_loss_is_never_more_than_everything(self):
        assert analysis.horizon_risk(60, -0.2, -0.3)['var'] == -1.0
        assert analysis.horizon_risk(4, -0.01, -0.02) == {
            'periods': 4,
            'rule': 'square_root_of_time',
            'var': -0.02,
            'expected_shortfall': -0.04,
        }


class TestEwma:
    def test_follows_the_recursion_by_hand(self):
        returns = pd.Series([0.01, -0.02, 0.03])

        sigma = analysis.ewma_volatility(returns, decay=0.5)

        # s2[0] = r0^2, then s2[t] = decay * s2[t-1] + (1 - decay) * r[t]^2
        second = 0.5 * 1e-4 + 0.5 * 4e-4
        third = 0.5 * second + 0.5 * 9e-4
        assert sigma.tolist() == pytest.approx([0.01, math.sqrt(second), math.sqrt(third)])

    def test_reports_the_current_value_at_risk_and_how_it_did(self):
        returns = random_returns(600, seed=3)
        confidence = 0.95

        result = analysis.analyze(returns, confidence, VaRMethod.HISTORICAL, 250)

        ewma = result['ewma']
        sigma = analysis.ewma_volatility(returns).iloc[-1]
        assert ewma['decay'] == 0.94
        assert ewma['volatility'] == pytest.approx(sigma * math.sqrt(252), abs=1e-6)
        assert ewma['var'] == pytest.approx(stats.norm.ppf(0.05) * sigma, abs=1e-6)
        assert ewma['window_volatility'] == pytest.approx(returns.iloc[-250:].std(ddof=1) * math.sqrt(252), abs=1e-6)
        # judged over the same periods as the rolling window's value at risk: the first full window is not judged
        assert ewma['observations'] == len(returns) - 250
        assert 0 <= ewma['exceedances'] <= ewma['observations']
        assert isinstance(ewma['reject'], bool)

    def test_the_series_starts_where_the_rolling_estimate_does(self):
        result = analysis.analyze(random_returns(400), 0.95, VaRMethod.HISTORICAL, 100)

        ewma_var = result['series']['ewma_var']
        assert len(ewma_var) == 400
        assert all(v is None for v in ewma_var[:99]) and all(v is not None for v in ewma_var[99:])
        assert all(v < 0 for v in ewma_var[99:])

    def test_a_calm_period_after_a_shock_lowers_it_faster_than_a_long_window(self):
        values = [0.0005 * (-1) ** i for i in range(300)] + [-0.08, 0.07] + [0.0005 * (-1) ** i for i in range(40)]
        returns = dated(values)

        result = analysis.analyze(returns, 0.95, VaRMethod.HISTORICAL, 100)

        assert result['ewma']['volatility'] < result['ewma']['window_volatility']


class TestBenchmark:
    def test_a_series_that_is_twice_the_benchmark(self):
        benchmark = random_returns(200, seed=5)
        returns = benchmark * 2

        result = analysis.versus_benchmark(returns, benchmark, 'Index', 252)

        assert result['beta'] == pytest.approx(2.0, abs=1e-4)
        assert result['correlation'] == pytest.approx(1.0, abs=1e-4)
        assert result['r_squared'] == pytest.approx(1.0, abs=1e-4)
        assert result['alpha'] == pytest.approx(0.0, abs=1e-6)
        assert result['name'] == 'Index' and result['observations'] == 200
        # the active return is the benchmark itself: a tracking error of its volatility
        assert result['tracking_error'] == pytest.approx(benchmark.std(ddof=1) * math.sqrt(252), abs=1e-5)

    def test_matches_the_textbook_formulas(self):
        rng = np.random.default_rng(11)
        b = rng.normal(0.0004, 0.01, 300)
        r = 0.0002 + 0.7 * b + rng.normal(0, 0.006, 300)
        returns, benchmark = dated(r), dated(b)

        result = analysis.versus_benchmark(returns, benchmark, 'B', 252)

        slope, intercept = np.polyfit(b, r, 1)
        active = r - b
        assert result['beta'] == pytest.approx(slope, abs=1e-4)
        assert result['alpha'] == pytest.approx(intercept * 252, abs=1e-5)
        assert result['correlation'] == pytest.approx(np.corrcoef(r, b)[0, 1], abs=1e-4)
        assert result['tracking_error'] == pytest.approx(active.std(ddof=1) * math.sqrt(252), abs=1e-6)
        assert result['active_return'] == pytest.approx(active.mean() * 252, abs=1e-6)
        assert result['information_ratio'] == pytest.approx(
            active.mean() / active.std(ddof=1) * math.sqrt(252), abs=1e-4
        )
        assert result['benchmark_volatility'] == pytest.approx(b.std(ddof=1) * math.sqrt(252), abs=1e-6)
        assert result['volatility'] == pytest.approx(r.std(ddof=1) * math.sqrt(252), abs=1e-6)

    def test_uses_the_periods_both_have(self):
        returns, benchmark = random_returns(100, seed=2), random_returns(100, seed=3)

        result = analysis.versus_benchmark(returns, benchmark.iloc[20:], 'B', 252)

        assert result['observations'] == 80

    def test_a_benchmark_that_does_not_vary_is_refused(self):
        with pytest.raises(AnalysisError, match='does not vary'):
            analysis.versus_benchmark(random_returns(100), dated([0.001] * 100), 'Flat', 252)

    def test_too_little_in_common_is_refused(self):
        with pytest.raises(AnalysisError, match='At least 30 periods'):
            analysis.versus_benchmark(random_returns(100), random_returns(100).iloc[:20], 'Short', 252)


def portfolio_body(n=300, **extra) -> dict:
    frames = {
        name: analysis.simulate_returns(scenario, n, seed=i)
        for i, (name, scenario) in enumerate({'A': 'calm', 'B': 'volatile'}.items())
    }
    first = next(iter(frames.values()))
    return {
        'assets': {name: [round(float(v), 6) for v in s] for name, s in frames.items()},
        'dates': [str(d.date()) for d in first.index],
        **extra,
    }


class TestApi:
    def test_horizon_in_a_single_analysis(self, client):
        sample = client.get('/api/sample', params={'scenario': 'volatile'}).json()

        body = client.post('/api/analyze', json={'returns': sample['returns'], 'dates': sample['dates'], 'horizon': 10})

        assert body.status_code == 200
        result = body.json()
        assert result['horizon']['periods'] == 10 and result['settings']['horizon'] == 10
        assert result['ewma']['decay'] == 0.94

    @pytest.mark.parametrize('horizon', [0, -1, 61, 1.5, 'ten'])
    def test_a_horizon_out_of_range_is_refused(self, client, horizon):
        sample = client.get('/api/sample', params={'scenario': 'volatile'}).json()

        response = client.post('/api/analyze', json={'returns': sample['returns'], 'horizon': horizon})

        assert response.status_code == 422

    def test_a_portfolio_against_a_benchmark(self, client):
        n = 300
        benchmark = analysis.simulate_returns('regime_shift', n, seed=9)
        body = portfolio_body(
            n, benchmark=[round(float(v), 6) for v in benchmark], benchmark_name='XU100.IS', horizon=5
        )

        response = client.post('/api/portfolio', json=body)

        assert response.status_code == 200
        versus = response.json()['benchmark']
        assert versus['name'] == 'XU100.IS' and versus['observations'] == n
        assert set(versus) >= {'beta', 'alpha', 'tracking_error', 'information_ratio', 'correlation', 'r_squared'}
        assert response.json()['horizon']['periods'] == 5

    def test_without_a_benchmark_there_is_none(self, client):
        assert 'benchmark' not in client.post('/api/portfolio', json=portfolio_body()).json()

    def test_a_benchmark_with_the_wrong_number_of_dates_is_refused(self, client):
        body = portfolio_body(300, benchmark=[0.001 * (-1) ** i for i in range(250)])

        response = client.post('/api/portfolio', json=body)

        assert response.status_code == 422 and 'Benchmark: Got 300 dates for 250 values' in response.json()['error']

    def test_a_benchmark_of_another_length_is_refused_without_dates(self, client):
        body = portfolio_body(300, benchmark=[0.001 * (-1) ** i for i in range(250)])
        del body['dates']

        response = client.post('/api/portfolio', json=body)

        assert response.status_code == 422 and 'same number of observations' in response.json()['error']

    def test_benchmark_prices_are_turned_into_returns_like_the_assets(self, client):
        n = 300
        rng = np.random.default_rng(4)
        prices = {name: list(100 * np.cumprod(1 + rng.normal(0, 0.01, n))) for name in ('A', 'B', 'IDX')}
        dates = [str(d.date()) for d in pd.bdate_range('2023-01-02', periods=n)]

        response = client.post(
            '/api/portfolio',
            json={
                'assets': {k: prices[k] for k in ('A', 'B')},
                'kind': 'prices',
                'dates': dates,
                'benchmark': prices['IDX'],
                'benchmark_name': 'IDX',
            },
        )

        assert response.status_code == 200
        assert response.json()['benchmark']['observations'] == n - 1

    def test_the_new_settings_survive_being_saved(self, client):
        saved = client.post(
            '/api/runs',
            json={'name': 'Deep', 'kind': 'portfolio', 'request': portfolio_body(horizon=10, benchmark_name='Idx')},
        )
        assert saved.status_code == 201

        opened = client.get(f'/api/runs/{saved.json()["id"]}').json()

        assert opened['result']['horizon']['periods'] == 10

    def test_a_named_portfolio_keeps_its_benchmark(self, client):
        saved = client.post(
            '/api/portfolios',
            json={'name': 'Book', 'symbols': ['A', 'B'], 'weights': {'A': 1, 'B': 1}, 'benchmark': ' xu100.is '},
        )

        assert saved.json()['benchmark'] == 'XU100.IS'
        opened = client.get(f'/api/portfolios/{saved.json()["id"]}').json()
        assert opened['definition']['benchmark'] == 'XU100.IS'

    def test_a_benchmark_symbol_must_be_a_symbol(self, client):
        response = client.post(
            '/api/portfolios',
            json={'name': 'Book', 'symbols': ['A', 'B'], 'weights': {'A': 1, 'B': 1}, 'benchmark': '../x'},
        )

        assert response.status_code == 422
