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

import io

import pytest

pytest.importorskip('starlette')
pytest.importorskip('pydantic')
openpyxl = pytest.importorskip('openpyxl')

from starlette.testclient import TestClient  # noqa: E402

from gs_quant.apps.risk_dashboard import analysis  # noqa: E402
from gs_quant.apps.risk_dashboard.app import create_app  # noqa: E402
from gs_quant.apps.risk_dashboard.settings import Settings  # noqa: E402
from gs_quant.apps.risk_dashboard.xlsx import XLSX_MIME  # noqa: E402

TOKEN = 'a-long-enough-test-token'


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(database=tmp_path / 'runs.db')))


def returns_of(scenario, n=400, seed=7):
    series = analysis.simulate_returns(scenario, n, seed)
    return [round(float(v), 6) for v in series], [str(d.date()) for d in series.index]


def single_request(**extra):
    values, dates = returns_of('volatile')
    return {'returns': values, 'dates': dates, 'window': 100, 'horizon': 10, **extra}


def portfolio_request(**extra):
    first, dates = returns_of('calm')
    second, _ = returns_of('volatile', seed=3)
    bench, _ = returns_of('regime_shift', seed=5)
    return {
        'assets': {'=A': first, '@B': second},
        'dates': dates,
        'window': 100,
        'benchmark': bench,
        'benchmark_name': '-Index',
        'scenarios': [{'name': '+Crash', 'shocks': {'=A': -0.1, '@B': -0.2}}],
        **extra,
    }


def save(client, kind, request, name='Run'):
    saved = client.post('/api/runs', json={'name': name, 'kind': kind, 'request': request})
    assert saved.status_code == 201
    return saved.json()['id']


def workbook(client, run_id):
    response = client.get(f'/api/runs/{run_id}/xlsx')
    assert response.status_code == 200
    return openpyxl.load_workbook(io.BytesIO(response.content)), response


def rows_of(sheet):
    return [[c.value for c in row] for row in sheet.iter_rows()]


class TestWorkbook:
    def test_is_a_download_with_the_spreadsheet_type(self, client):
        run_id = save(client, 'single', single_request())

        _, response = workbook(client, run_id)

        assert response.headers['content-type'] == XLSX_MIME
        assert response.headers['content-disposition'] == f'attachment; filename="risk_{run_id[:8]}.xlsx"'

    def test_a_single_series_has_the_parts_that_apply(self, client):
        run_id = save(client, 'single', single_request())

        book, _ = workbook(client, run_id)

        assert book.sheetnames == ['Summary', 'Backtest', 'Series', 'Stress']

    def test_the_figures_are_the_numbers_the_api_gives_and_are_numeric(self, client):
        request = single_request(confidence=0.99, method='parametric')
        run_id = save(client, 'single', request)
        result = client.get(f'/api/runs/{run_id}').json()['result']

        book, _ = workbook(client, run_id)

        summary = {row[0]: row[1] for row in rows_of(book['Summary']) if row[0]}
        assert summary['Value at risk, one period (parametric, 99.0%)'] == pytest.approx(
            result['summary']['var_parametric']
        )
        assert summary['Value at risk, 10 periods'] == pytest.approx(result['horizon']['var'])
        assert summary['Annualized volatility'] == pytest.approx(result['summary']['annualized_volatility'])
        cell = next(
            c for row in book['Summary'].iter_rows() for c in row if c.value == summary['Annualized volatility']
        )
        assert isinstance(cell.value, float) and cell.number_format == '0.00%'
        assert summary['Observations'] == result['summary']['observations']

    def test_the_series_sheet_has_a_row_per_period(self, client):
        run_id = save(client, 'single', single_request())
        result = client.get(f'/api/runs/{run_id}').json()['result']

        book, _ = workbook(client, run_id)

        rows = rows_of(book['Series'])
        assert rows[0][0] == 'Date' and len(rows) == 1 + len(result['series']['dates'])
        assert rows[1][0] == result['series']['dates'][0]
        assert rows[1][1] == pytest.approx(result['series']['returns'][0])
        assert rows[-1][7] in (True, False)
        assert rows[1][4] is None  # no value at risk before the first full window

    def test_a_portfolio_has_its_decomposition_scenarios_and_benchmark(self, client):
        run_id = save(client, 'portfolio', portfolio_request())
        result = client.get(f'/api/runs/{run_id}').json()['result']

        book, _ = workbook(client, run_id)

        assert book.sheetnames == ['Summary', 'Backtest', 'Series', 'Stress', 'Portfolio', 'What-if', 'Benchmark']
        benchmark = {row[0]: row[1] for row in rows_of(book['Benchmark']) if row[0]}
        assert benchmark['Beta'] == pytest.approx(result['benchmark']['beta'])
        assert benchmark['Tracking error (annualized)'] == pytest.approx(result['benchmark']['tracking_error'])
        weights = [row[1] for row in rows_of(book['Portfolio'])[1:3]]
        assert weights == pytest.approx([0.5, 0.5])

    def test_names_that_look_like_formulas_stay_text(self, client):
        run_id = save(client, 'portfolio', portfolio_request(), name='=HYPERLINK("http://example.com","x")')

        book, _ = workbook(client, run_id)

        texts = {
            c.value
            for sheet in book
            for row in sheet.iter_rows()
            for c in row
            if isinstance(c.value, str) and c.value[:1] in '=+-@'
        }
        assert {'=A', '@B', '-Index', '+Crash', '=HYPERLINK("http://example.com","x")'} <= texts
        assert all(c.data_type != 'f' for sheet in book for row in sheet.iter_rows() for c in row)

    def test_an_unknown_run_is_not_found(self, client):
        assert client.get(f'/api/runs/{"0" * 32}/xlsx').status_code == 404
        assert client.get('/api/runs/not-an-id/xlsx').status_code == 404

    def test_a_run_that_can_no_longer_be_analysed_is_a_conflict(self, client, monkeypatch):
        run_id = save(client, 'single', single_request())

        def refuse(kind, params):
            raise analysis.AnalysisError('the model changed')

        monkeypatch.setattr('gs_quant.apps.risk_dashboard.app.execute', refuse)

        response = client.get(f'/api/runs/{run_id}/xlsx')

        assert response.status_code == 409 and 'no longer be analysed' in response.json()['error']

    def test_it_needs_the_token_like_the_rest(self, tmp_path):
        client = TestClient(create_app(Settings(database=tmp_path / 'runs.db', api_token=TOKEN)))
        headers = {'Authorization': f'Bearer {TOKEN}'}
        saved = client.post(
            '/api/runs', headers=headers, json={'name': 'x', 'kind': 'single', 'request': single_request()}
        )
        run_id = saved.json()['id']

        assert client.get(f'/api/runs/{run_id}/xlsx').status_code == 401
        assert client.get(f'/api/runs/{run_id}/xlsx', headers=headers).status_code == 200
