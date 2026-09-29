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

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from gs_quant.mcp import __main__ as cli

runner = CliRunner()


@pytest.fixture
def server_env(monkeypatch):
    """Patch everything the `server` command would use to start a real server"""
    mocks = MagicMock()
    monkeypatch.setattr(cli, "FastMCP", mocks.FastMCP)
    monkeypatch.setattr(cli, "get_tools", lambda *a, **k: {})
    monkeypatch.setattr(cli, "run_mcp_server", mocks.run)
    monkeypatch.setattr(cli, "LocalUserAuthMiddleware", mocks.local)
    monkeypatch.setattr(cli, "RemoteUserAuthMiddleware", mocks.remote)
    monkeypatch.setattr(cli, "LoggingMiddleware", mocks.logging)
    monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
    return mocks


def _server(*args: str):
    return runner.invoke(cli.app, ["server", *args], catch_exceptions=False)


class TestServerAuthModes:
    def test_none_never_creates_a_marquee_session(self, server_env):
        result = _server("--auth", "none")

        assert result.exit_code == 0
        server_env.local.assert_not_called()  # the local middleware connects to Marquee when constructed
        server_env.remote.assert_not_called()
        assert [c.args[0] for c in server_env.FastMCP.return_value.add_middleware.call_args_list] == [
            server_env.logging.return_value
        ]
        server_env.run.assert_called_once()
        assert "no authentication" in " ".join(result.output.split())

    def test_local_is_the_default(self, server_env):
        _server("--client-id", "id", "--client-secret", "secret")

        server_env.local.assert_called_once()
        assert server_env.local.call_args.kwargs == {"client_id": "id", "client_secret": "secret"}
        server_env.remote.assert_not_called()

    def test_passthrough(self, server_env):
        _server("--auth", "passthrough")

        server_env.remote.assert_called_once()
        server_env.local.assert_not_called()

    def test_unknown_auth_mode_is_rejected(self, server_env):
        result = runner.invoke(cli.app, ["server", "--auth", "bogus"])

        assert result.exit_code != 0
        server_env.run.assert_not_called()

    def test_tag_filters_are_applied(self, server_env):
        _server("--auth", "none", "--enable-tags", "analytics, data")

        server_env.FastMCP.return_value.enable.assert_called_once_with(tags={"analytics", "data"}, only=True)


class TestClientNoAuth:
    @pytest.fixture
    def client_env(self, monkeypatch):
        mocks = MagicMock()
        monkeypatch.setattr(cli, "build_gs_session", mocks.build_gs_session)
        monkeypatch.setattr(cli, "build_auth_headers", mocks.build_auth_headers)
        monkeypatch.setattr(cli, "make_client", mocks.make_client)
        monkeypatch.setattr(cli, "run_async", mocks.run_async)
        monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
        return mocks

    def _invoke(self, *args: str):
        return runner.invoke(cli.app, ["client", *args, "list-tools"], catch_exceptions=False)

    def test_no_auth_skips_the_gs_session(self, client_env):
        result = self._invoke("--no-auth", "--port", "4399")

        assert result.exit_code == 0
        client_env.build_gs_session.assert_not_called()
        client_env.build_auth_headers.assert_not_called()
        assert client_env.make_client.call_args.args[0] == "http://localhost:4399/mcp"
        assert client_env.make_client.call_args.kwargs["headers"] == {}

    def test_no_auth_still_sends_explicit_headers(self, client_env):
        self._invoke("--no-auth", "-H", "X-Team: quant")

        assert client_env.make_client.call_args.kwargs["headers"] == {"X-Team": "quant"}

    def test_default_authenticates_and_forwards_the_session_headers(self, client_env):
        client_env.build_auth_headers.return_value = {"Authorization": "Bearer t"}

        self._invoke("--client-id", "id", "--client-secret", "secret", "-H", "X-Team: quant")

        client_env.build_gs_session.assert_called_once_with(None, "id", "secret")
        assert client_env.make_client.call_args.kwargs["headers"] == {"Authorization": "Bearer t", "X-Team": "quant"}
