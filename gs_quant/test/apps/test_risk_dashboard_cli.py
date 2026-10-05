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

import pytest

pytest.importorskip('starlette')
pytest.importorskip('uvicorn')

from gs_quant.apps.risk_dashboard import __main__ as cli  # noqa: E402

TOKEN = 'a-long-enough-test-token'


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Replaces the server with a recorder, and gives the application a database of its own"""
    calls = {}
    monkeypatch.setattr('uvicorn.run', lambda app, **kwargs: calls.update(app=app, **kwargs))
    monkeypatch.setenv('RISK_APP_DATABASE', str(tmp_path / 'runs.db'))
    for name in ('HOST', 'PORT', 'API_TOKEN', 'LOG_LEVEL'):
        monkeypatch.delenv(f'RISK_APP_{name}', raising=False)
    return calls


def test_serves_on_localhost_by_default(served):
    assert cli.main([]) == 0

    assert (served['host'], served['port']) == ('127.0.0.1', 8000)
    assert served['access_log'] is False


def test_options_without_a_command_mean_serve(served):
    assert cli.main(['--port', '9100']) == 0

    assert served['port'] == 9100


def test_environment_sets_the_defaults_and_flags_override_them(served, monkeypatch):
    monkeypatch.setenv('RISK_APP_PORT', '9200')

    cli.main(['serve'])
    assert served['port'] == 9200

    cli.main(['serve', '--port', '9300'])
    assert served['port'] == 9300


def test_refuses_to_listen_on_the_network_without_a_token(served, capsys):
    assert cli.main(['serve', '--host', '0.0.0.0']) == 2

    assert 'app' not in served
    assert 'RISK_APP_API_TOKEN' in capsys.readouterr().err


def test_listens_on_the_network_with_a_token_or_an_explicit_override(served, monkeypatch):
    assert cli.main(['serve', '--host', '0.0.0.0', '--no-auth']) == 0
    assert served['host'] == '0.0.0.0'

    served.clear()
    monkeypatch.setenv('RISK_APP_API_TOKEN', TOKEN)
    assert cli.main(['serve', '--host', '0.0.0.0']) == 0
    assert served['host'] == '0.0.0.0'


def test_reports_invalid_configuration_without_a_traceback(served, monkeypatch, capsys):
    monkeypatch.setenv('RISK_APP_PORT', 'abc')

    assert cli.main([]) == 2

    assert 'RISK_APP_' in capsys.readouterr().err


def test_exports_the_static_page(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr('gs_quant.apps.risk_dashboard.export.main', lambda argv: calls.append(argv))

    assert cli.main(['export', '-o', str(tmp_path / 'x.html'), '--observations', '300']) == 0

    assert calls == [['-o', str(tmp_path / 'x.html'), '--observations', '300', '--seed', '7']]
