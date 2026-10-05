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

import json
import re

import numpy as np
import pandas as pd
import pytest
from scipy import stats

pytest.importorskip('starlette')
pytest.importorskip('pydantic')

from starlette.testclient import TestClient  # noqa: E402

from gs_quant.apps.risk_dashboard import analysis  # noqa: E402
from gs_quant.apps.risk_dashboard.app import MAX_BODY_BYTES, STATIC_DIR, create_app  # noqa: E402
from gs_quant.timeseries.helper import Window  # noqa: E402
from gs_quant.timeseries.risk_metrics import (  # noqa: E402
    VaRMethod,
    risk_summary,
    traffic_light_zone,
    value_at_risk,
    var_backtest,
    var_independence_test,
)


@pytest.fixture(scope='module')
def client():
    return TestClient(create_app())


@pytest.fixture(scope='module')
def volatile() -> pd.Series:
    return analysis.simulate_returns('volatile', 1000, seed=7)


# ----------------------------------------------------------------------------------------------------------------------
# Simulation
# ----------------------------------------------------------------------------------------------------------------------


class TestSimulation:
    def test_is_reproducible_and_seed_dependent(self):
        first = analysis.simulate_returns('volatile', 300, seed=1)

        pd.testing.assert_series_equal(first, analysis.simulate_returns('volatile', 300, seed=1))
        assert not first.equals(analysis.simulate_returns('volatile', 300, seed=2))

    def test_is_dated_on_business_days(self):
        series = analysis.simulate_returns('calm', 250)

        assert len(series) == 250
        assert isinstance(series.index, pd.DatetimeIndex)
        assert series.index.is_monotonic_increasing and series.index.dayofweek.max() <= 4
        assert series.index[-1] == pd.Timestamp('2025-12-31')

    def test_rejects_unknown_scenarios_and_sizes(self):
        with pytest.raises(analysis.AnalysisError, match='Unknown scenario'):
            analysis.simulate_returns('nope')
        for n in (10, analysis.MAX_OBSERVATIONS + 1):
            with pytest.raises(analysis.AnalysisError, match='between 60'):
                analysis.simulate_returns('calm', n)

    def test_scenarios_have_the_intended_character(self):
        calm = analysis.simulate_returns('calm', 4000, seed=3)
        volatile = analysis.simulate_returns('volatile', 4000, seed=3)

        assert abs(stats.kurtosis(calm)) < 1  # close to normal
        assert stats.kurtosis(volatile) > 1.5  # fat tails
        assert volatile.std() > calm.std()

    def test_regime_shift_turns_turbulent(self):
        series = analysis.simulate_returns('regime_shift', 1000, seed=7)

        assert series.iloc[800:].std() > 2 * series.iloc[:600].std()

    def test_volatility_clusters(self):
        squared = analysis.simulate_returns('volatile', 4000, seed=5) ** 2

        assert squared.autocorr(1) > 0.05  # GARCH: large moves follow large moves


# ----------------------------------------------------------------------------------------------------------------------
# Input handling
# ----------------------------------------------------------------------------------------------------------------------


class TestBuildSeries:
    def test_returns_with_dates(self):
        dates = [d.date() for d in pd.bdate_range('2024-01-01', periods=100)]

        series, assumptions = analysis.build_series([0.001] * 100, dates)

        assert isinstance(series.index, pd.DatetimeIndex) and assumptions == []

    def test_missing_dates_are_reported_as_an_assumption(self):
        _, assumptions = analysis.build_series([0.001] * 100)

        assert 'periods per year' in assumptions[0]

    def test_prices_are_converted_to_returns(self):
        prices = list(100 * np.cumprod(1 + np.full(100, 0.01)))

        series, assumptions = analysis.build_series(prices, None, 'prices')

        assert len(series) == 99 and series.iloc[0] == pytest.approx(0.01)
        assert any('simple returns' in a for a in assumptions)

    @pytest.mark.parametrize(
        'values, dates, kind, message',
        [
            ([0.01] * 100 + [float('nan')], None, 'returns', 'finite'),
            ([0.01] * 100 + [float('inf')], None, 'returns', 'finite'),
            ([0.01] * 100, [None] * 99, 'returns', 'dates for'),
            ([0.01] * 59, None, 'returns', 'At least 60'),
            ([0.01] * 99 + [-1.0], None, 'returns', '-100%'),
            ([100.0] * 99 + [0.0], None, 'prices', 'positive'),
            ([0.01] * (analysis.MAX_OBSERVATIONS + 1), None, 'returns', 'At most'),
        ],
    )
    def test_rejects_bad_input(self, values, dates, kind, message):
        with pytest.raises(analysis.AnalysisError, match=message):
            analysis.build_series(values, dates, kind)

    def test_rejects_unordered_or_duplicate_dates(self):
        dates = [d.date() for d in pd.bdate_range('2024-01-01', periods=100)]

        with pytest.raises(analysis.AnalysisError, match='strictly increasing'):
            analysis.build_series([0.001] * 100, dates[::-1])
        with pytest.raises(analysis.AnalysisError, match='strictly increasing'):
            analysis.build_series([0.001] * 100, [dates[0]] + dates[:-1])


# ----------------------------------------------------------------------------------------------------------------------
# Analysis
# ----------------------------------------------------------------------------------------------------------------------


class TestAnalyze:
    def test_agrees_with_the_library(self, volatile):
        result = analysis.analyze(volatile, 0.99, VaRMethod.PARAMETRIC, 250)

        assert result['summary'] == pytest.approx(risk_summary(volatile, 0.99).to_dict())
        forecast = value_at_risk(volatile, 0.99, VaRMethod.PARAMETRIC, w=Window(250, 249)).shift(1)
        expected = var_backtest(volatile, forecast, 0.99)
        assert result['backtest']['exceedances'] == expected.exceedances
        assert result['backtest']['p_value'] == pytest.approx(expected.p_value)

    def test_series_are_aligned_and_consistent(self, volatile):
        result = analysis.analyze(volatile)
        series = result['series']

        assert {len(v) for v in series.values()} == {len(volatile)}
        assert series['dates'][0] == str(volatile.index[0].date())
        assert series['growth'][-1] == pytest.approx((1 + volatile).prod(), rel=1e-5)
        assert all(d <= 0 for d in series['drawdown'])
        assert min(series['drawdown']) == pytest.approx(result['summary']['max_drawdown'], abs=1e-5)
        assert sum(series['breach']) == result['backtest']['exceedances']

    def test_the_first_forecasts_need_a_full_window(self, volatile):
        series = analysis.analyze(volatile, window=100)['series']

        assert series['var'][:99] == [None] * 99 and series['var'][99] is not None
        assert not any(series['breach'][:100])  # no forecast exists for the first window, so no breach

    def test_breaches_are_judged_against_the_forecast_made_before(self, volatile):
        result = analysis.analyze(volatile, 0.95, VaRMethod.HISTORICAL, 100)
        series = result['series']

        for i in np.flatnonzero(series['breach']):
            assert series['returns'][i] < series['var'][i - 1]

    def test_histogram_covers_the_central_99_percent_and_counts_the_outliers(self, volatile):
        histogram = analysis.analyze(volatile)['histogram']

        assert len(histogram['centres']) == len(histogram['counts']) == analysis.HISTOGRAM_BINS
        # every return is either in a bin or counted as an outlier, and the outliers are about 1% of the sample
        outliers = histogram['outliers_below'] + histogram['outliers_above']
        assert sum(histogram['counts']) + outliers == len(volatile)
        assert 0 < outliers <= 0.02 * len(volatile)
        assert histogram['centres'][0] - histogram['width'] / 2 == pytest.approx(np.quantile(volatile, 0.005), abs=1e-6)
        assert sum(histogram['normal_counts']) == pytest.approx(len(volatile), rel=0.15)

    def test_qq_data_compares_standardised_returns_with_normal_quantiles(self, volatile):
        qq = analysis.analyze(volatile)['qq']
        sample, theoretical = np.array(qq['sample']), np.array(qq['theoretical'])

        assert len(sample) == len(theoretical) <= analysis.QQ_MAX_POINTS
        assert (np.diff(sample) >= 0).all() and (np.diff(theoretical) > 0).all()
        # the extremes are always kept, and the sample is standardised
        z = (volatile - volatile.mean()) / volatile.std(ddof=1)
        assert sample[0] == pytest.approx(z.min(), abs=1e-3) and sample[-1] == pytest.approx(z.max(), abs=1e-3)
        assert theoretical[0] == pytest.approx(stats.norm.ppf(0.5 / len(volatile)), abs=1e-3)

    def test_qq_shows_normal_data_on_the_diagonal_and_fat_tails_off_it(self):
        calm = analysis.analyze(analysis.simulate_returns('calm', 3000, seed=2))['qq']
        volatile = analysis.analyze(analysis.simulate_returns('volatile', 3000, seed=2))['qq']

        assert np.corrcoef(calm['theoretical'], calm['sample'])[0, 1] > 0.995
        # the fat-tailed sample's worst returns are far beyond what a normal distribution of that size produces
        assert volatile['sample'][0] < volatile['theoretical'][0] - 1
        assert calm['sample'][0] > calm['theoretical'][0] - 1

    def test_worst_drawdown_matches_the_summary(self, volatile):
        result = analysis.analyze(volatile)
        episode = result['worst_drawdown']
        growth = np.array(result['series']['growth'])

        assert episode['depth'] == pytest.approx(result['summary']['max_drawdown'], abs=1e-5)
        assert 0 <= episode['peak'] <= episode['trough'] < len(volatile)
        assert growth[episode['trough']] / growth[: episode['trough'] + 1].max() - 1 == pytest.approx(
            episode['depth'], abs=1e-4
        )

    def test_backtest_carries_the_independence_test_and_the_traffic_light(self, volatile):
        result = analysis.analyze(volatile, 0.99, VaRMethod.PARAMETRIC, 250)
        forecast = value_at_risk(volatile, 0.99, VaRMethod.PARAMETRIC, w=Window(250, 249)).shift(1)
        independence = var_independence_test(volatile, forecast, 0.99)
        light = traffic_light_zone(result['backtest']['exceedances'], result['backtest']['observations'], 0.99)

        assert result['backtest']['independence']['independence_lr'] == pytest.approx(independence.independence_lr)
        assert result['backtest']['independence']['n11'] == independence.n11
        assert result['backtest']['traffic_light']['zone'] == light.zone.value
        assert result['backtest']['traffic_light']['cumulative_probability'] == pytest.approx(
            light.cumulative_probability, abs=1e-6
        )

    def test_a_regime_shift_is_a_red_zone_and_a_calm_market_is_green(self):
        shifted = analysis.analyze(analysis.simulate_returns('regime_shift', 1000, seed=7), 0.95)
        calm = analysis.analyze(analysis.simulate_returns('calm', 1000, seed=7), 0.95, VaRMethod.PARAMETRIC)

        assert shifted['backtest']['traffic_light']['zone'] == 'red'
        assert calm['backtest']['traffic_light']['zone'] == 'green'

    def test_expected_shortfall_is_never_better_than_var(self, volatile):
        series = analysis.analyze(volatile, 0.95)['series']

        pairs = [(v, e) for v, e in zip(series['var'], series['expected_shortfall']) if v is not None]
        assert pairs and all(e <= v for v, e in pairs)

    def test_cornish_fisher_uses_the_parametric_shortfall_and_says_so(self, volatile):
        result = analysis.analyze(volatile, 0.95, VaRMethod.CORNISH_FISHER)

        assert any('parametric method' in a for a in result['assumptions'])
        assert result['settings']['method'] == 'cornish_fisher'

    def test_undated_returns_assume_daily_data(self):
        returns = pd.Series(np.random.default_rng(0).normal(0, 0.01, 400))

        result = analysis.analyze(returns, window=100, assumptions=['a note'])

        assert result['settings']['periods_per_year'] == 252
        assert result['assumptions'] == ['a note']
        assert result['series']['dates'][:2] == ['0', '1']

    def test_explicit_periods_per_year_is_used(self, volatile):
        assert analysis.analyze(volatile, periods_per_year=12)['settings']['periods_per_year'] == 12

    def test_window_must_be_shorter_than_the_series(self, volatile):
        with pytest.raises(analysis.AnalysisError, match='must be shorter'):
            analysis.analyze(volatile, window=1000)

    def test_library_errors_become_analysis_errors(self, volatile):
        with pytest.raises(analysis.AnalysisError, match='confidence'):
            analysis.analyze(volatile, confidence=1.5)

    def test_result_is_strict_json(self, volatile):
        json.dumps(analysis.analyze(volatile, 0.99, VaRMethod.CORNISH_FISHER), allow_nan=False)

    def test_a_trailing_var_model_is_rejected_after_a_regime_shift(self):
        shifted = analysis.simulate_returns('regime_shift', 1000, seed=7)

        for method in (VaRMethod.HISTORICAL, VaRMethod.PARAMETRIC):
            backtest = analysis.analyze(shifted, 0.95, method, 250)['backtest']
            assert backtest['reject'] and backtest['observed_rate'] > backtest['expected_rate']

    def test_a_trailing_var_model_is_not_rejected_in_a_calm_market(self):
        calm = analysis.simulate_returns('calm', 1000, seed=7)

        assert not analysis.analyze(calm, 0.95, VaRMethod.PARAMETRIC, 250)['backtest']['reject']


# ----------------------------------------------------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------------------------------------------------


class TestApi:
    def test_health(self, client):
        payload = client.get('/api/health').json()

        assert payload['status'] == 'ok' and payload['version']

    def test_scenarios(self, client):
        payload = client.get('/api/scenarios').json()

        assert {s['id'] for s in payload} == set(analysis.SCENARIOS)
        assert all(s['title'] and s['description'] for s in payload)

    def test_sample(self, client):
        payload = client.get('/api/sample', params={'scenario': 'calm', 'n': 120, 'seed': 3}).json()

        assert payload['scenario'] == 'calm'
        assert len(payload['dates']) == len(payload['returns']) == 120

    @pytest.mark.parametrize(
        'params',
        [{'scenario': 'nope'}, {'n': 5}, {'n': 'many'}, {'seed': 'x'}],
        ids=['scenario', 'small', 'nan', 'seed'],
    )
    def test_sample_errors(self, client, params):
        response = client.get('/api/sample', params=params)

        assert response.status_code == 422 and response.json()['error']

    def test_analyze_round_trip(self, client):
        sample = client.get('/api/sample', params={'scenario': 'volatile'}).json()

        response = client.post(
            '/api/analyze',
            json={'returns': sample['returns'], 'dates': sample['dates'], 'confidence': 0.99, 'method': 'parametric'},
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload['settings'] == {
            'confidence': 0.99,
            'method': 'parametric',
            'window': 250,
            'minimum_acceptable_return': 0.0,
            'periods_per_year': 252,
            'horizon': 1,
            'horizon_method': 'square_root',
            'ewma_decay': 0.94,
        }
        assert set(payload) == {
            'summary',
            'backtest',
            'settings',
            'horizon',
            'ewma',
            'series',
            'histogram',
            'qq',
            'worst_drawdown',
            'stress',
            'assumptions',
            'conventions',
        }

    def test_analyze_prices(self, client):
        prices = list(100 * np.cumprod(1 + np.random.default_rng(1).normal(0, 0.01, 400)))

        response = client.post('/api/analyze', json={'prices': prices, 'window': 100})

        assert response.status_code == 200
        assert response.json()['summary']['observations'] == 399

    @pytest.mark.parametrize(
        'body, message',
        [
            ({}, 'either returns or prices'),
            ({'returns': [0.01] * 100, 'prices': [1.0] * 100}, 'either returns or prices'),
            ({'returns': [0.01] * 100, 'confidence': 0.5}, 'confidence'),
            ({'returns': [0.01] * 100, 'confidence': 1.0}, 'confidence'),
            ({'returns': [0.01] * 100, 'method': 'magic'}, 'method'),
            ({'returns': [0.01] * 100, 'window': 5}, 'window'),
            ({'returns': [0.01] * 100, 'surprise': 1}, 'surprise'),
            ({'returns': ['a'] * 100}, 'returns'),
            ({'returns': [0.01] * 100, 'dates': ['not-a-date'] * 100}, 'dates'),
            ({'returns': [0.01] * 30}, 'At least 60'),
            ({'returns': [0.01] * 100, 'window': 500}, 'must be shorter'),
            ({'returns': [0.01] * (analysis.MAX_OBSERVATIONS + 1)}, 'returns'),
        ],
    )
    def test_analyze_rejects_bad_requests(self, client, body, message):
        response = client.post('/api/analyze', json=body)

        assert response.status_code == 422
        assert message.lower() in response.json()['error'].lower()

    def test_analyze_rejects_invalid_json(self, client):
        response = client.post('/api/analyze', content=b'{not json', headers={'Content-Type': 'application/json'})

        assert response.status_code == 422

    def test_analyze_rejects_oversized_bodies(self, client):
        response = client.post('/api/analyze', content=b' ' * (MAX_BODY_BYTES + 1))

        assert response.status_code == 413

    def test_analyze_rejects_oversized_bodies_sent_without_a_content_length(self, client):
        # a chunked upload declares no length up front, so the size has to be checked on what was actually received
        chunks = (b' ' * 100_000 for _ in range(MAX_BODY_BYTES // 100_000 + 2))

        response = client.post('/api/analyze', content=chunks)

        assert response.status_code == 413

    def test_analyze_is_post_only(self, client):
        assert client.get('/api/analyze').status_code == 405

    def test_unknown_paths_are_404(self, client):
        assert client.get('/api/nothing').status_code == 404
        assert client.get('/static/../app.py').status_code == 404


class TestServingAndSecurity:
    def test_index_and_assets_are_served(self, client):
        assert 'Risk Analytics Dashboard' in client.get('/').text
        assert (
            client.get('/static/app.js')
            .headers['content-type']
            .startswith(('text/javascript', 'application/javascript'))
        )
        assert client.get('/static/styles.css').headers['content-type'].startswith('text/css')

    @pytest.mark.parametrize('path', ['/', '/api/health', '/static/app.js'])
    def test_security_headers_on_every_response(self, client, path):
        headers = client.get(path).headers

        assert "script-src 'self'" in headers['content-security-policy']
        assert "default-src 'none'" in headers['content-security-policy']
        assert headers['x-content-type-options'] == 'nosniff'
        assert headers['x-frame-options'] == 'DENY'
        assert headers['referrer-policy'] == 'no-referrer'

    def test_api_responses_are_not_cached(self, client):
        assert client.get('/api/health').headers['cache-control'] == 'no-store'
        assert 'no-store' not in client.get('/static/app.js').headers.get('cache-control', '')

    def test_page_works_under_its_own_content_security_policy(self):
        """The CSP forbids inline script and style, so the page must not rely on either"""
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')

        assert not re.search(r'<script(?![^>]*\bsrc=)', html), 'inline <script>'
        assert '<style' not in html
        assert not re.search(r'\sstyle\s*=', html), 'inline style attribute'
        assert not re.search(r'\son\w+\s*=', html), 'inline event handler'
        for reference in re.findall(r'(?:src|href)="(/static/[^"]+)"', html):
            assert (STATIC_DIR / reference.removeprefix('/static/')).is_file(), reference

    def test_script_does_not_write_html(self):
        """Uploaded CSV text reaches the page, so it must only ever be inserted as text"""
        script = (STATIC_DIR / 'app.js').read_text(encoding='utf-8')

        assert 'innerHTML' not in script and 'insertAdjacentHTML' not in script and 'document.write' not in script
        assert 'eval(' not in script

    def test_page_and_script_use_the_same_element_ids(self):
        html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
        script = (STATIC_DIR / 'app.js').read_text(encoding='utf-8')

        ids = set(re.findall(r'id="([\w-]+)"', html))
        used = set(re.findall(r"\$\('#([\w-]+)'\)", script))
        assert used <= ids, used - ids
