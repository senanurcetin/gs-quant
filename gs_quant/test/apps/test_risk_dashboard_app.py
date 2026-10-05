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

import logging
import re

import numpy as np
import pandas as pd
import pytest

pytest.importorskip('starlette')
pytest.importorskip('pydantic')

from starlette.testclient import TestClient  # noqa: E402

from gs_quant.apps.risk_dashboard import analysis, portfolio, report  # noqa: E402
from gs_quant.apps.risk_dashboard.app import create_app  # noqa: E402
from gs_quant.apps.risk_dashboard.settings import Settings  # noqa: E402
from gs_quant.apps.risk_dashboard.store import RunStore  # noqa: E402

TOKEN = 'a-long-enough-test-token'


def make_settings(tmp_path, **overrides) -> Settings:
    return Settings(database=tmp_path / 'data' / 'runs.db', **overrides)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(make_settings(tmp_path)))


def single_request(n: int = 400, seed: int = 7, **extra) -> dict:
    series = analysis.simulate_returns('volatile', n, seed)
    return {'returns': [round(float(v), 6) for v in series], 'dates': [str(d.date()) for d in series.index], **extra}


def portfolio_request(n: int = 400, **extra) -> dict:
    names = {'Calm': 'calm', 'Volatile': 'volatile', 'Shift': 'regime_shift'}
    frames = {name: analysis.simulate_returns(scenario, n, seed=i) for i, (name, scenario) in enumerate(names.items())}
    first = next(iter(frames.values()))
    return {
        'assets': {name: [round(float(v), 6) for v in s] for name, s in frames.items()},
        'dates': [str(d.date()) for d in first.index],
        **extra,
    }


# ----------------------------------------------------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------------------------------------------------


class TestSettings:
    def test_defaults_bind_to_localhost_without_a_token(self):
        settings = Settings.from_env({})

        assert settings.is_local and settings.api_token is None and settings.port == 8000

    def test_reads_the_environment(self, tmp_path):
        settings = Settings.from_env(
            {
                'RISK_APP_HOST': '0.0.0.0',
                'RISK_APP_PORT': '9000',
                'RISK_APP_DATABASE': str(tmp_path / 'x.db'),
                'RISK_APP_API_TOKEN': TOKEN,
                'RISK_APP_MAX_RUNS': '5',
                'RISK_APP_LOG_LEVEL': 'warning',
            }
        )

        assert (settings.host, settings.port, settings.max_runs) == ('0.0.0.0', 9000, 5)
        assert (
            settings.database == tmp_path / 'x.db' and settings.api_token == TOKEN and settings.log_level == 'WARNING'
        )
        assert not settings.is_local

    @pytest.mark.parametrize(
        'environ, message',
        [
            ({'RISK_APP_PORT': 'abc'}, 'Invalid RISK_APP_'),
            ({'RISK_APP_PORT': '70000'}, 'port'),
            ({'RISK_APP_API_TOKEN': 'short'}, 'at least 16'),
            ({'RISK_APP_MAX_RUNS': '0'}, 'max_runs'),
            ({'RISK_APP_LOG_LEVEL': 'LOUD'}, 'log_level'),
        ],
    )
    def test_rejects_invalid_values(self, environ, message):
        with pytest.raises(ValueError, match=message):
            Settings.from_env(environ)


# ----------------------------------------------------------------------------------------------------------------------
# Store
# ----------------------------------------------------------------------------------------------------------------------


class TestRunStore:
    def test_round_trips_a_request(self, tmp_path):
        store = RunStore(tmp_path / 'a' / 'b' / 'runs.db')

        saved = store.add('First', 'single', {'returns': [0.01, -0.02]}, {'var': -0.03})

        assert store.get(saved['id'])['request'] == {'returns': [0.01, -0.02]}
        assert store.get(saved['id'])['headline'] == {'var': -0.03}
        assert [r['id'] for r in store.list()] == [saved['id']]

    def test_lists_newest_first_and_prunes_the_oldest(self, tmp_path):
        store = RunStore(tmp_path / 'runs.db', max_runs=3)

        ids = [store.add(f'run {i}', 'single', {}, {})['id'] for i in range(5)]

        assert [r['id'] for r in store.list()] == ids[:1:-1]
        assert store.get(ids[0]) is None

    def test_delete_reports_whether_anything_was_deleted(self, tmp_path):
        store = RunStore(tmp_path / 'runs.db')
        run_id = store.add('x', 'single', {}, {})['id']

        assert store.delete(run_id) is True
        assert store.delete(run_id) is False
        assert store.get(run_id) is None

    def test_survives_reopening(self, tmp_path):
        run_id = RunStore(tmp_path / 'runs.db').add('x', 'single', {'k': 1}, {})['id']

        assert RunStore(tmp_path / 'runs.db').get(run_id)['request'] == {'k': 1}

    def test_stored_requests_are_compressed(self, tmp_path):
        store = RunStore(tmp_path / 'runs.db')
        store.add('x', 'single', {'returns': [0.0123] * 5000}, {})

        assert (tmp_path / 'runs.db').stat().st_size < 5000 * 7


# ----------------------------------------------------------------------------------------------------------------------
# Portfolio analysis
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture(scope='module')
def three_assets() -> dict:
    request = portfolio_request(500)
    return request['assets'], [pd.Timestamp(d).date() for d in request['dates']]


class TestPortfolio:
    def test_matches_the_weighted_sum_of_returns(self, three_assets):
        assets, dates = three_assets
        weights = {'Calm': 0.5, 'Volatile': 0.3, 'Shift': 0.2}

        result = portfolio.analyze_portfolio(assets, weights, dates)
        expected = sum(np.array(assets[k]) * w for k, w in weights.items())

        np.testing.assert_allclose(result['series']['returns'], expected, atol=1e-6)

    def test_contributions_add_up_to_the_portfolio(self, three_assets):
        assets, dates = three_assets

        details = portfolio.analyze_portfolio(assets, {'Calm': 2, 'Volatile': 1, 'Shift': 1}, dates)['portfolio']

        assert sum(a['weight'] for a in details['assets']) == pytest.approx(1)
        assert sum(a['volatility_contribution'] for a in details['assets']) == pytest.approx(1, abs=1e-5)
        assert sum(a['es_contribution'] for a in details['assets']) == pytest.approx(1, abs=1e-5)

    def test_es_contribution_decomposes_the_historical_expected_shortfall(self, three_assets):
        assets, dates = three_assets
        weights = {'Calm': 1 / 3, 'Volatile': 1 / 3, 'Shift': 1 / 3}

        result = portfolio.analyze_portfolio(assets, weights, dates, confidence=0.95)
        series = pd.Series(result['series']['returns'])
        tail = series <= np.quantile(series, 0.05)

        assert tail.sum() == result['portfolio']['tail_periods']
        assert series[tail].mean() == pytest.approx(
            sum(a['es_contribution'] * series[tail].mean() for a in result['portfolio']['assets']),
            abs=1e-5,
        )

    def test_diversification_ratio_is_above_one_for_imperfectly_correlated_assets(self, three_assets):
        assets, dates = three_assets

        details = portfolio.analyze_portfolio(assets, None, dates)['portfolio']

        assert details['diversification_ratio'] > 1
        matrix = np.array(details['correlation']['matrix'])
        np.testing.assert_allclose(np.diag(matrix), 1)
        np.testing.assert_allclose(matrix, matrix.T)

    def test_identical_assets_have_no_diversification(self):
        series = analysis.simulate_returns('volatile', 300, 1)
        values = [float(v) for v in series]

        details = portfolio.analyze_portfolio({'A': values, 'B': values}, None)['portfolio']

        assert details['diversification_ratio'] == pytest.approx(1)
        assert [a['volatility_contribution'] for a in details['assets']] == pytest.approx([0.5, 0.5])

    def test_notes_assumptions(self, three_assets):
        assets, dates = three_assets

        notes = portfolio.analyze_portfolio(assets, None, dates)['assumptions']
        scaled = portfolio.analyze_portfolio(assets, {'Calm': 2, 'Volatile': 2, 'Shift': 2}, dates)['assumptions']

        assert any('Equal weights' in n for n in notes) and any('rebalanced' in n for n in notes)
        assert any('scaled to sum to 1' in n for n in scaled)

    def test_prices_are_converted_per_asset(self):
        rng = np.random.default_rng(3)
        prices = {name: list(100 * np.cumprod(1 + rng.normal(0, 0.01, 301))) for name in ('A', 'B')}

        result = portfolio.analyze_portfolio(prices, None, kind='prices')

        assert result['summary']['observations'] == 300

    @pytest.mark.parametrize(
        'assets, weights, message',
        [
            ({'A': [0.01] * 100}, None, 'between 2 and'),
            ({f'A{i}': [0.01] * 100 for i in range(11)}, None, 'between 2 and'),
            ({'A': [0.01] * 100, 'B': [0.01] * 90}, None, 'same number'),
            ({'A': [0.01] * 100, ' ': [0.01] * 100}, None, 'Asset names'),
            ({'A': [0.01] * 100, 'B ': [0.01] * 100, 'B': [0.01] * 100}, None, 'unique'),
            ({'A': [0.01] * 100, 'B': [-1.5] * 100}, None, 'B: Simple returns'),
            ({'A': [0.01] * 100, 'B': [0.01] * 100}, {'A': 1}, 'exactly the assets'),
            ({'A': [0.01] * 100, 'B': [0.01] * 100}, {'A': 1, 'B': -1}, 'positive number'),
            ({'A': [0.01] * 100, 'B': [0.01] * 100}, {'A': float('nan'), 'B': 1}, 'finite'),
        ],
    )
    def test_rejects_bad_input(self, assets, weights, message):
        with pytest.raises(analysis.AnalysisError, match=message):
            portfolio.analyze_portfolio(assets, weights)

    def test_zero_variance_portfolio_cannot_be_decomposed(self):
        with pytest.raises(analysis.AnalysisError):
            portfolio.analyze_portfolio({'A': [0.001] * 300, 'B': [0.001] * 300}, None)


# ----------------------------------------------------------------------------------------------------------------------
# Stress windows
# ----------------------------------------------------------------------------------------------------------------------


class TestStress:
    def test_finds_the_worst_stretch_by_brute_force(self):
        returns = analysis.simulate_returns('volatile', 300, 4)

        windows = {w['periods']: w for w in analysis.stress(returns)}

        for horizon in analysis.STRESS_HORIZONS:
            brute = min(
                np.prod(1 + returns.iloc[i : i + horizon].to_numpy()) - 1 for i in range(len(returns) - horizon + 1)
            )
            assert windows[horizon]['return'] == pytest.approx(brute, abs=1e-6)
            start, end = pd.Timestamp(windows[horizon]['start']), pd.Timestamp(windows[horizon]['end'])
            assert len(returns.loc[start:end]) == horizon
            assert np.prod(1 + returns.loc[start:end].to_numpy()) - 1 == pytest.approx(brute, abs=1e-6)

    def test_the_worst_period_is_the_minimum_return(self):
        returns = analysis.simulate_returns('calm', 200, 1)

        worst = analysis.stress(returns)[0]

        assert worst['periods'] == 1 and worst['return'] == pytest.approx(returns.min(), abs=1e-6)
        assert worst['start'] == worst['end'] == str(returns.idxmin().date())

    def test_windows_that_are_a_large_part_of_the_data_are_left_out(self):
        returns = analysis.simulate_returns('calm', 60, 1)

        assert [w['periods'] for w in analysis.stress(returns)] == [1, 5, 20]
        assert [w['periods'] for w in analysis.stress(returns.iloc[:50])] == [1, 5]

    def test_undated_series_use_positions(self):
        windows = analysis.stress(pd.Series(np.linspace(-0.02, 0.02, 100)))

        assert windows[0]['start'] == windows[0]['end'] == '0'

    def test_a_portfolio_lists_what_each_asset_did_in_the_window(self, three_assets):
        assets, dates = three_assets

        result = portfolio.analyze_portfolio(assets, {'Calm': 0.5, 'Volatile': 0.3, 'Shift': 0.2}, dates)
        window = next(w for w in result['stress'] if w['periods'] == 5)

        assert [a['name'] for a in window['assets']] == ['Calm', 'Volatile', 'Shift']
        frame = pd.DataFrame(assets, index=pd.to_datetime(dates))
        span = frame.loc[window['start'] : window['end']]
        expected = (1 + span).prod() - 1
        for asset in window['assets']:
            assert asset['return'] == pytest.approx(expected[asset['name']], abs=1e-6)

    def test_single_series_results_have_no_asset_breakdown(self, client):
        result = client.post('/api/analyze', json=single_request(400, window=100)).json()

        assert result['stress'] and all('assets' not in w for w in result['stress'])


# ----------------------------------------------------------------------------------------------------------------------
# HTTP: portfolio, saved runs, report
# ----------------------------------------------------------------------------------------------------------------------


class TestPortfolioApi:
    def test_analyzes_a_portfolio(self, client):
        response = client.post('/api/portfolio', json=portfolio_request(400, window=100))

        assert response.status_code == 200
        body = response.json()
        assert [a['name'] for a in body['portfolio']['assets']] == ['Calm', 'Volatile', 'Shift']
        assert body['summary']['observations'] == 400

    def test_reports_what_is_wrong(self, client):
        request = portfolio_request(400, window=100)
        request['weights'] = {'Calm': 1}

        response = client.post('/api/portfolio', json=request)

        assert response.status_code == 422 and 'exactly the assets' in response.json()['error']

    def test_rejects_unknown_fields_and_too_many_assets(self, client):
        assert client.post('/api/portfolio', json={**portfolio_request(100), 'extra': 1}).status_code == 422
        many = {'assets': {f'A{i}': [0.01] * 100 for i in range(11)}}
        assert client.post('/api/portfolio', json=many).status_code == 422


class TestRunsApi:
    def save(self, client, name='My run', kind='single', request=None):
        request = request if request is not None else single_request(400, window=100)
        return client.post('/api/runs', json={'name': name, 'kind': kind, 'request': request})

    def test_save_list_open_and_delete(self, client):
        saved = self.save(client)

        assert saved.status_code == 201
        meta = saved.json()
        assert meta['name'] == 'My run' and re.fullmatch(r'[0-9a-f]{32}', meta['id'])
        assert meta['headline']['zone'] in ('green', 'yellow', 'red')

        assert [r['id'] for r in client.get('/api/runs').json()] == [meta['id']]

        opened = client.get(f'/api/runs/{meta["id"]}').json()
        assert opened['run']['name'] == 'My run'
        assert opened['request']['window'] == 100
        direct = client.post('/api/analyze', json=single_request(400, window=100)).json()
        assert opened['result'] == direct

        assert client.delete(f'/api/runs/{meta["id"]}').status_code == 204
        assert client.get(f'/api/runs/{meta["id"]}').status_code == 404
        assert client.get('/api/runs').json() == []

    def test_saves_a_portfolio(self, client):
        saved = self.save(client, 'Book', 'portfolio', portfolio_request(400, window=100)).json()

        opened = client.get(f'/api/runs/{saved["id"]}').json()

        assert saved['kind'] == 'portfolio' and 'portfolio' in opened['result']

    def test_an_invalid_request_is_not_saved(self, client):
        bad_series = self.save(client, request={'returns': [0.01] * 10})
        bad_fields = self.save(client, request={'prices': [1, 2], 'returns': [0.1]})
        bad_name = client.post('/api/runs', json={'name': ' ', 'kind': 'single', 'request': {}})
        bad_kind = client.post('/api/runs', json={'name': 'x', 'kind': 'other', 'request': {}})

        assert [r.status_code for r in (bad_series, bad_fields, bad_name, bad_kind)] == [422] * 4
        assert client.get('/api/runs').json() == []

    def test_compares_saved_runs_in_the_order_asked_for(self, client):
        first = self.save(client, 'Original', request=single_request(400, window=100)).json()
        second = self.save(client, 'Riskier', request=single_request(400, window=100, confidence=0.99)).json()
        book = self.save(client, 'Book', 'portfolio', portfolio_request(400, window=100)).json()

        response = client.get(f'/api/runs/compare?ids={book["id"]},{first["id"]},{second["id"]}')

        assert response.status_code == 200
        runs = response.json()['runs']
        assert [r['name'] for r in runs] == ['Book', 'Original', 'Riskier']
        assert runs[0]['kind'] == 'portfolio' and runs[0]['metrics']['diversification_ratio'] > 1
        assert runs[1]['metrics']['diversification_ratio'] is None
        assert runs[1]['metrics']['confidence'] == 0.95 and runs[2]['metrics']['confidence'] == 0.99
        assert runs[2]['metrics']['var'] < runs[1]['metrics']['var']  # a higher confidence level is a larger loss
        direct = client.post('/api/analyze', json=single_request(400, window=100)).json()
        assert runs[1]['metrics']['var'] == analysis.headline(direct)['var']
        assert {'annualized_return', 'max_drawdown', 'exceedances', 'kupiec_p_value', 'zone'} <= set(runs[1]['metrics'])

    def test_comparison_needs_two_to_four_distinct_existing_runs(self, client):
        ids = [self.save(client, f'run {i}').json()['id'] for i in range(5)]

        def compare(chosen):
            return client.get('/api/runs/compare', params={'ids': ','.join(chosen)})

        assert compare([]).status_code == 422
        assert compare(ids[:1]).status_code == 422
        assert compare(ids[:5]).status_code == 422
        assert compare([ids[0], ids[0]]).status_code == 422
        assert compare([ids[0], '0' * 32]).status_code == 404
        assert compare([ids[0], 'not-an-id']).status_code == 404
        assert compare(ids[:2]).status_code == 200

    def test_unknown_and_malformed_ids_are_404(self, client):
        for run_id in ('0' * 32, 'not-an-id', '..%2f..%2fetc'):
            assert client.get(f'/api/runs/{run_id}').status_code == 404
            assert client.delete(f'/api/runs/{run_id}').status_code == 404
            assert client.get(f'/api/runs/{run_id}/report').status_code == 404

    def test_names_are_stored_as_text_and_cannot_break_out_of_the_report(self, client):
        name = '</script><img src=x onerror=alert(1)>'

        meta = self.save(client, name).json()
        html = client.get(f'/api/runs/{meta["id"]}/report').text

        assert client.get('/api/runs').json()[0]['name'] == name
        assert '</script><img' not in html and '<\\/script><img' in html  # inside the data, the tag cannot close
        assert '<title>Risk report: &lt;/script&gt;&lt;img' in html
        assert len(report.INLINE.findall(html)) == 4  # the data, the static api, the script and the style: no more

    def test_report_is_a_self_contained_download_with_a_matching_policy(self, client):
        meta = self.save(client, 'Quarterly').json()

        response = client.get(f'/api/runs/{meta["id"]}/report')

        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/html')
        assert f'risk_report_{meta["id"][:8]}.html' in response.headers['content-disposition']
        policy = response.headers['content-security-policy']
        assert "default-src 'none'" in policy and 'unsafe-inline' not in policy
        # one hash for each inline script and the inline style
        assert policy.count("'sha256-") == len(report.INLINE.findall(response.text))
        assert 'src="/static' not in response.text and 'href="/static' not in response.text
        assert 'Quarterly' in response.text

    def test_policy_hashes_match_the_inline_content(self):
        html = '<style>a{}</style><script>var x = 1;</script>'

        policy = report.content_security_policy(html)

        assert "script-src 'sha256-" in policy and "style-src 'sha256-" in policy
        assert report.content_security_policy('<p>none</p>').count("'none'") >= 3

    def test_saved_runs_persist_across_app_instances(self, tmp_path):
        settings = make_settings(tmp_path)
        run_id = self.save(TestClient(create_app(settings))).json()['id']

        assert TestClient(create_app(settings)).get(f'/api/runs/{run_id}').status_code == 200

    def test_the_store_is_trimmed_to_max_runs(self, tmp_path):
        client = TestClient(create_app(make_settings(tmp_path, max_runs=2)))

        for i in range(3):
            self.save(client, f'run {i}')

        assert [r['name'] for r in client.get('/api/runs').json()] == ['run 2', 'run 1']

    def test_oversized_bodies_are_refused(self, tmp_path):
        client = TestClient(create_app(make_settings(tmp_path, max_body_bytes=5_000)))

        response = client.post('/api/runs', content=b'{"name":"x"' + b' ' * 6_000)

        assert response.status_code == 413


# ----------------------------------------------------------------------------------------------------------------------
# HTTP: operations
# ----------------------------------------------------------------------------------------------------------------------


class TestOperations:
    def test_probes_and_config_are_open_even_with_a_token(self, tmp_path):
        client = TestClient(create_app(make_settings(tmp_path, api_token=TOKEN)))

        assert client.get('/api/health').status_code == 200
        assert client.get('/api/ready').status_code == 200
        assert client.get('/').status_code == 200
        assert client.get('/static/app.js').status_code == 200

    def test_the_token_protects_every_other_endpoint(self, tmp_path):
        client = TestClient(create_app(make_settings(tmp_path, api_token=TOKEN)))
        paths = [
            '/api/config',
            '/api/scenarios',
            '/api/sample',
            '/api/runs',
            '/api/runs/compare',
            f'/api/runs/{"0" * 32}',
        ]

        for path in paths:
            denied = client.get(path)
            assert denied.status_code == 401 and denied.headers['www-authenticate'] == 'Bearer', path
        assert client.post('/api/analyze', json=single_request()).status_code == 401
        assert client.delete(f'/api/runs/{"0" * 32}').status_code == 401

    @pytest.mark.parametrize('header', ['Bearer wrong-token-of-some-length', 'Basic ' + TOKEN, TOKEN, 'Bearer '])
    def test_wrong_credentials_are_refused(self, tmp_path, header):
        client = TestClient(create_app(make_settings(tmp_path, api_token=TOKEN)))

        assert client.get('/api/runs', headers={'Authorization': header}).status_code == 401

    def test_the_right_token_is_accepted(self, tmp_path):
        client = TestClient(create_app(make_settings(tmp_path, api_token=TOKEN)))

        assert client.get('/api/runs', headers={'Authorization': f'Bearer {TOKEN}'}).status_code == 200
        assert client.get('/api/config', headers={'Authorization': f'bearer {TOKEN}'}).json()['auth_required'] is True

    def test_config_without_a_token(self, client):
        config = client.get('/api/config').json()

        assert config['auth_required'] is False and config['limits']['assets'] == portfolio.MAX_ASSETS

    def test_ready_fails_when_the_store_is_unavailable(self, tmp_path):
        blocked = tmp_path / 'file'
        blocked.write_text('not a directory')
        client = TestClient(create_app(Settings(database=blocked / 'runs.db')))

        response = client.get('/api/ready')

        assert response.status_code == 503 and 'not available' in response.json()['error']

    def test_every_response_has_a_request_id_that_is_echoed_when_sane(self, client):
        generated = client.get('/api/health').headers['x-request-id']
        echoed = client.get('/api/health', headers={'X-Request-ID': 'trace-123'}).headers['x-request-id']
        replaced = client.get('/api/health', headers={'X-Request-ID': 'bad id\twith spaces'}).headers['x-request-id']

        assert re.fullmatch(r'[0-9a-f]{16}', generated)
        assert echoed == 'trace-123' and re.fullmatch(r'[0-9a-f]{16}', replaced)

    def test_requests_are_logged_without_their_query_or_body(self, client, caplog):
        with caplog.at_level(logging.INFO, logger='gs_quant.apps.risk_dashboard'):
            client.get('/api/sample?scenario=calm&secret=hunter2')

        line = next(r.getMessage() for r in caplog.records if '/api/sample' in r.getMessage())
        assert 'GET /api/sample 200' in line and 'hunter2' not in line and 'rid=' in line

    def test_unexpected_errors_become_a_json_500_with_the_security_headers(self, tmp_path, monkeypatch, caplog):
        app = create_app(make_settings(tmp_path))
        monkeypatch.setattr(app.state.application.store, 'list', lambda: 1 / 0)
        client = TestClient(app, raise_server_exceptions=False)

        with caplog.at_level(logging.ERROR, logger='gs_quant.apps.risk_dashboard'):
            response = client.get('/api/runs')

        assert response.status_code == 500
        body = response.json()
        assert (
            body['error'] == 'Something went wrong on the server'
            and body['request_id'] == response.headers['x-request-id']
        )
        assert 'division' not in response.text and 'Content-Security-Policy' in response.headers
        assert any(r.exc_info for r in caplog.records)
