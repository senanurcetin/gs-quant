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

import copy
from unittest.mock import AsyncMock, MagicMock

import pytest

from gs_quant.mcp import run
from gs_quant.mcp.config import McpServiceConfig, SSLConfig
from gs_quant.mcp.run import _make_uvicorn_config, run_mcp_server, run_mcp_server_async


@pytest.fixture(autouse=True)
def _isolated_logging_config(monkeypatch):
    # _make_uvicorn_config mutates uvicorn's global logging config; keep that out of other tests
    monkeypatch.setattr(run, "LOGGING_CONFIG", copy.deepcopy(run.LOGGING_CONFIG))


@pytest.fixture
def mcp_server():
    server = MagicMock()
    server.http_app.return_value = "asgi-app"
    return server


def test_uses_config_values(mcp_server):
    config = _make_uvicorn_config(mcp_server, McpServiceConfig(base_path="/tools", port=9000, host="127.0.0.1"))

    mcp_server.http_app.assert_called_once_with(path="/tools")
    assert config.app == "asgi-app"
    assert config.host == "127.0.0.1"
    assert config.port == 9000
    assert config.ssl_certfile is None and config.ssl_keyfile is None


def test_port_precedence_argument_then_config_then_default(mcp_server):
    assert _make_uvicorn_config(mcp_server, McpServiceConfig(port=9000), port=8000).port == 8000
    assert _make_uvicorn_config(mcp_server, McpServiceConfig(port=9000)).port == 9000
    assert _make_uvicorn_config(mcp_server, McpServiceConfig()).port == 4301


def test_ssl_paths_expand_environment_variables(mcp_server, monkeypatch):
    monkeypatch.setenv("MCP_CERT_DIR", "/etc/certs")
    ssl_config = SSLConfig(cert_path="${MCP_CERT_DIR}/server.crt", key_path="${MCP_CERT_DIR}/server.key")

    config = _make_uvicorn_config(mcp_server, McpServiceConfig(ssl_config=ssl_config))

    assert config.ssl_certfile == "/etc/certs/server.crt"
    assert config.ssl_keyfile == "/etc/certs/server.key"


def test_log_formatters_include_timestamp(mcp_server):
    _make_uvicorn_config(mcp_server, McpServiceConfig())
    for name in ("default", "access"):
        assert run.LOGGING_CONFIG["formatters"][name]["fmt"].startswith("%(asctime)s")


def test_run_mcp_server_runs_uvicorn_server(mcp_server, monkeypatch):
    server_cls = MagicMock()
    monkeypatch.setattr(run.uvicorn, "Server", server_cls)

    run_mcp_server(mcp_server, McpServiceConfig(port=1234))

    server_cls.return_value.run.assert_called_once_with()


@pytest.mark.asyncio
async def test_run_mcp_server_async_serves(mcp_server, monkeypatch):
    server_cls = MagicMock()
    server_cls.return_value.serve = AsyncMock()
    monkeypatch.setattr(run.uvicorn, "Server", server_cls)

    await run_mcp_server_async(mcp_server, McpServiceConfig(), port=4444)

    server_cls.return_value.serve.assert_awaited_once_with()
    assert server_cls.call_args.args[0].port == 4444
