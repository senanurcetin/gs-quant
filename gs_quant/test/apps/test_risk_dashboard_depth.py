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
            'method': 'square_root',
            'rule': 'square_root_of_time',
            'var': -0.02,
            'expected_shortfall': -0.04,
            'backtest': None,
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


class TestHorizonBacktest:
    def test_judges_non_overlapping_stretches_against_the_scaled_value_at_risk(self):
        values = np.zeros(62)
        for k in (3, 7, 11):  # the stretches starting at 1 + 2k lose 5%: more than the forecast of 1% x sqrt(2)
            values[1 + 2 * k] = -0.05
        returns = dated(values)
        var = dated(np.full(62, -0.01))

        result = analysis.horizon_backtest(returns, var, 2, 0.95)

        # stretches start at 1, 3, ..., 59: thirty of them, three of which breach
        assert (result['observations'], result['exceedances'], result['periods']) == (30, 3, 2)
        assert result['expected_rate'] == pytest.approx(0.05)

    def test_a_stretch_is_judged_by_its_compounded_return(self):
        values = np.zeros(62)
        values[1], values[2] = -0.01, -0.01  # together a fall of 1.99%, which is past 1% x sqrt(2) = 1.41%
        returns, var = dated(values), dated(np.full(62, -0.01))

        assert analysis.horizon_backtest(returns, var, 2, 0.95)['exceedances'] == 1

    def test_the_forecast_is_the_value_at_risk_known_before_the_stretch(self):
        values = np.zeros(62)
        values[1] = -0.05
        known = np.full(62, -0.10)  # wide enough to cover a fall of 5%...
        known[0] = -0.01  # ...except the one known just before the first stretch, which is tight
        returns, var = dated(values), dated(known)

        assert analysis.horizon_backtest(returns, var, 2, 0.95)['exceedances'] == 1

    def test_too_few_stretches_say_nothing(self):
        assert analysis.horizon_backtest(random_returns(60), random_returns(60) * 0 - 0.01, 10, 0.95) is None

    def test_it_comes_with_the_square_root_figures_and_only_with_them(self):
        returns = analysis.simulate_returns('regime_shift', 1000, 7)

        root = analysis.analyze(returns, 0.95, VaRMethod.HISTORICAL, 250, horizon=10)['horizon']
        simulated = analysis.analyze(
            returns, 0.95, VaRMethod.HISTORICAL, 250, horizon=10, horizon_method='filtered_simulation'
        )
        single = analysis.analyze(returns, 0.95, VaRMethod.HISTORICAL, 250)['horizon']

        assert root['backtest']['observations'] == 75 and root['backtest']['exceedances'] == 8
        assert simulated['horizon']['backtest'] is None and single['backtest'] is None


class TestFilteredSimulation:
    def test_gives_the_same_figures_every_time(self):
        returns = random_returns(500, seed=4)

        assert analysis.filtered_simulation(returns, 10, 0.95, 0.94) == analysis.filtered_simulation(
            returns, 10, 0.95, 0.94
        )

    def test_for_returns_that_are_normal_and_constant_in_volatility_it_agrees_with_theory(self):
        sigma = 0.01
        returns = random_returns(3000, seed=8, scale=sigma)

        var, es = analysis.filtered_simulation(returns, 10, 0.95, 0.97)

        # about -1.645 x 0.01 x sqrt(10) = -5.2% for the value at risk, and -6.5% for the shortfall
        assert var == pytest.approx(-1.645 * sigma * math.sqrt(10), rel=0.15)
        assert es == pytest.approx(-2.063 * sigma * math.sqrt(10), rel=0.15)
        assert es < var < 0

    def test_follows_todays_volatility_where_a_long_window_lags(self):
        calm = np.random.default_rng(1).normal(0, 0.005, 400)
        stormy = np.random.default_rng(2).normal(0, 0.03, 30)
        returns = dated(np.concatenate([calm, stormy]))

        result = analysis.analyze(
            returns, 0.95, VaRMethod.HISTORICAL, 300, horizon=10, horizon_method='filtered_simulation'
        )
        root = analysis.analyze(returns, 0.95, VaRMethod.HISTORICAL, 300, horizon=10)['horizon']

        assert result['horizon']['var'] < 2 * root['var']  # a loss, so "more than twice" is more negative
        assert result['horizon']['expected_shortfall'] < result['horizon']['var']

    def test_names_what_it_did_in_the_notes(self):
        returns = random_returns(400)

        result = analysis.analyze(
            returns, 0.95, VaRMethod.HISTORICAL, 100, horizon=5, horizon_method='filtered_simulation'
        )

        assert any('filtered historical simulation' in a and '10,000 paths' in a for a in result['assumptions'])
        assert not any('square root' in a for a in result['assumptions'])
        assert result['horizon']['method'] == 'filtered_simulation' and result['horizon']['paths'] == 10_000

    def test_one_period_needs_no_simulation(self):
        result = analysis.analyze(
            random_returns(400), 0.95, VaRMethod.HISTORICAL, 100, horizon_method='filtered_simulation'
        )

        assert (
            result['horizon']['method'] == 'square_root'
            and result['horizon']['var'] == analysis.headline(result)['var']
        )


class TestDecay:
    def test_the_decay_is_used_and_reported(self):
        returns = random_returns(500, seed=6)

        result = analysis.analyze(returns, 0.95, VaRMethod.HISTORICAL, 100, ewma_decay=0.9)

        assert result['ewma']['decay'] == 0.9 and result['settings']['ewma_decay'] == 0.9
        assert result['ewma']['volatility'] == pytest.approx(
            analysis.ewma_volatility(returns, 0.9).iloc[-1] * math.sqrt(252), abs=1e-6
        )

    def test_a_shorter_memory_reacts_more_to_a_recent_shock(self):
        values = np.concatenate([np.random.default_rng(3).normal(0, 0.005, 300), [-0.06]])
        returns = dated(values)

        fast = analysis.analyze(returns, 0.95, VaRMethod.HISTORICAL, 100, ewma_decay=0.85)['ewma']['volatility']
        slow = analysis.analyze(returns, 0.95, VaRMethod.HISTORICAL, 100, ewma_decay=0.98)['ewma']['volatility']

        assert fast > slow

    @pytest.mark.parametrize('decay', [0.5, 0.79, 1.0])
    def test_a_decay_out_of_range_is_refused(self, decay):
        with pytest.raises(AnalysisError, match='EWMA decay'):
            analysis.analyze(random_returns(400), 0.95, VaRMethod.HISTORICAL, 100, ewma_decay=decay)

    def test_an_unknown_horizon_method_is_refused(self):
        with pytest.raises(AnalysisError, match='horizon method'):
            analysis.analyze(random_returns(400), 0.95, VaRMethod.HISTORICAL, 100, horizon_method='magic')


class TestNewSettingsOverHttp:
    def test_the_settings_are_accepted_and_echoed(self, client):
        sample = client.get('/api/sample', params={'scenario': 'regime_shift'}).json()

        body = client.post(
            '/api/analyze',
            json={
                'returns': sample['returns'],
                'dates': sample['dates'],
                'horizon': 10,
                'horizon_method': 'filtered_simulation',
                'ewma_decay': 0.9,
            },
        )

        assert body.status_code == 200
        result = body.json()
        assert result['settings']['horizon_method'] == 'filtered_simulation' and result['settings']['ewma_decay'] == 0.9
        assert result['horizon']['method'] == 'filtered_simulation' and result['horizon']['backtest'] is None

    @pytest.mark.parametrize('changes', [{'ewma_decay': 0.5}, {'ewma_decay': 1.0}, {'horizon_method': 'magic'}])
    def test_values_out_of_range_are_refused(self, client, changes):
        sample = client.get('/api/sample', params={'scenario': 'volatile'}).json()

        assert client.post('/api/analyze', json={'returns': sample['returns'], **changes}).status_code == 422

    def test_a_saved_run_keeps_them(self, client):
        saved = client.post(
            '/api/runs',
            json={
                'name': 'FHS',
                'kind': 'portfolio',
                'request': portfolio_body(horizon=5, horizon_method='filtered_simulation', ewma_decay=0.9),
            },
        )

        opened = client.get(f'/api/runs/{saved.json()["id"]}').json()['result']

        assert opened['settings']['ewma_decay'] == 0.9 and opened['horizon']['method'] == 'filtered_simulation'


class TestCaptureAndRollingBeta:
    def pair(self, up=2.0, down=0.5, n=120, seed=3):
        rng = np.random.default_rng(seed)
        b = rng.normal(0, 0.01, n)
        r = np.where(b > 0, up * b, down * b)
        return dated(r), dated(b), b, r

    def test_capture_ratios_are_the_average_return_over_the_up_and_the_down_periods(self):
        returns, benchmark, b, r = self.pair()

        result = analysis.versus_benchmark(returns, benchmark, 'B', 252)

        assert result['up_capture'] == pytest.approx(2.0, abs=1e-4)  # twice the benchmark whenever it rises
        assert result['down_capture'] == pytest.approx(0.5, abs=1e-4)  # half of it whenever it falls
        assert result['up_capture'] == pytest.approx(r[b > 0].mean() / b[b > 0].mean(), abs=1e-4)

    def test_too_few_up_or_down_periods_give_no_ratio(self):
        b = np.concatenate([np.full(3, 0.01), np.full(57, -0.01)])  # three rising periods
        returns, benchmark = dated(b * 1.5), dated(b)

        result = analysis.versus_benchmark(returns, benchmark, 'B', 252)

        assert result['up_capture'] is None and result['down_capture'] == pytest.approx(1.5, abs=1e-4)

    def test_rolling_beta_is_the_beta_over_the_last_window(self):
        rng = np.random.default_rng(5)
        b = rng.normal(0, 0.01, 150)
        r = np.concatenate([1.0 * b[:75], 3.0 * b[75:]]) + rng.normal(0, 0.0005, 150)
        returns, benchmark = dated(r), dated(b)

        result = analysis.versus_benchmark(returns, benchmark, 'B', 252, window=50)

        rolling = result['rolling_beta']
        assert rolling['window'] == 50 and len(rolling['values']) == 150 and len(rolling['dates']) == 150
        assert all(v is None for v in rolling['values'][:49]) and rolling['values'][49] is not None
        for end in (49, 100, 149):  # against the textbook formula over the same window
            w_r, w_b = r[end - 49 : end + 1], b[end - 49 : end + 1]
            assert rolling['values'][end] == pytest.approx(np.cov(w_r, w_b)[0, 1] / np.var(w_b, ddof=1), abs=1e-3)
        assert rolling['values'][74] == pytest.approx(1.0, abs=0.05) and rolling['values'][149] == pytest.approx(
            3.0, abs=0.05
        )

    def test_a_window_as_long_as_the_data_gives_no_series(self):
        returns, benchmark, *_ = self.pair(n=60)

        assert analysis.versus_benchmark(returns, benchmark, 'B', 252, window=60)['rolling_beta'] is None
        assert analysis.versus_benchmark(returns, benchmark, 'B', 252)['rolling_beta'] is None


class TestSingleSeriesBenchmark:
    def test_a_single_series_against_a_benchmark(self, client):
        n = 300
        returns = [round(float(v), 6) for v in analysis.simulate_returns('volatile', n, 2)]
        benchmark = [round(float(v), 6) for v in analysis.simulate_returns('volatile', n, 2)]  # the same market

        body = client.post(
            '/api/analyze',
            json={'returns': returns, 'benchmark': benchmark, 'benchmark_name': 'Same', 'window': 100},
        )

        assert body.status_code == 200
        versus = body.json()['benchmark']
        assert versus['name'] == 'Same' and versus['beta'] == pytest.approx(1.0, abs=1e-3)
        assert versus['tracking_error'] == pytest.approx(0.0, abs=1e-6) and versus['rolling_beta']['window'] == 100

    def test_prices_and_dates_work_like_they_do_for_the_data(self, client):
        n = 200
        rng = np.random.default_rng(1)
        prices = list(100 * np.cumprod(1 + rng.normal(0, 0.01, n)))
        index = list(100 * np.cumprod(1 + rng.normal(0, 0.01, n)))
        dates = [str(d.date()) for d in pd.bdate_range('2024-01-01', periods=n)]

        body = client.post(
            '/api/analyze',
            json={'prices': prices, 'dates': dates, 'benchmark': index, 'benchmark_name': 'IDX', 'window': 60},
        )

        assert body.status_code == 200 and body.json()['benchmark']['observations'] == n - 1

    def test_a_benchmark_of_another_length_is_refused(self, client):
        returns = [round(float(v), 6) for v in analysis.simulate_returns('volatile', 300, 2)]

        response = client.post('/api/analyze', json={'returns': returns, 'benchmark': returns[:250]})

        assert response.status_code == 422 and 'same number of observations' in response.json()['error']

    def test_without_one_there_is_none(self, client):
        returns = [round(float(v), 6) for v in analysis.simulate_returns('volatile', 300, 2)]

        assert 'benchmark' not in client.post('/api/analyze', json={'returns': returns}).json()
