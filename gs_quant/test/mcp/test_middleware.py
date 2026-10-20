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

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest

from gs_quant.mcp import middleware
from gs_quant.mcp.middleware import LocalUserAuthMiddleware, RemoteUserAuthMiddleware, _time_str
from gs_quant.session import Environment


def _context(request_context=None, state: dict | None = None, session_id: str = "sess-1") -> MagicMock:
    context = MagicMock()
    fastmcp_context = context.fastmcp_context
    fastmcp_context.request_context = request_context
    fastmcp_context.session_id = session_id
    fastmcp_context.set_state = AsyncMock()
    fastmcp_context.get_state = AsyncMock(side_effect=lambda key: (state or {}).get(key))
    return context


def _printed(capsys) -> str:
    # rich wraps at the terminal width; normalise whitespace so assertions do not depend on line breaks
    return " ".join(capsys.readouterr().out.split())


def test_time_str_is_iso_with_milliseconds():
    parsed = dt.datetime.fromisoformat(_time_str())
    assert parsed.microsecond % 1000 == 0


class TestLocalUserAuthMiddleware:
    @pytest.fixture
    def gs_session(self, monkeypatch):
        gs_session = MagicMock()
        gs_session.get.return_value = MagicMock(name="session")
        gs_session.current.sync.get.return_value = {"login": "jdoe"}
        monkeypatch.setattr(middleware, "GsSession", gs_session)
        return gs_session

    def test_loads_user_profile_on_init(self, gs_session):
        mw = LocalUserAuthMiddleware(Environment.QA, client_id="id", client_secret="secret")

        gs_session.get.assert_called_once_with(Environment.QA, client_id="id", client_secret="secret")
        gs_session.current.sync.get.assert_called_once_with("/users/self")
        assert mw.user_profile == {"login": "jdoe"}

    def test_defaults_to_prod(self, gs_session):
        LocalUserAuthMiddleware()
        assert gs_session.get.call_args.args[0] == Environment.PROD

    @pytest.mark.asyncio
    async def test_on_request_stores_profile_and_session(self, gs_session):
        mw = LocalUserAuthMiddleware()
        context = _context(request_context=object())
        call_next = AsyncMock(return_value="result")

        assert await mw.on_request(context, call_next) == "result"

        context.fastmcp_context.set_state.assert_any_await("user_profile", {"login": "jdoe"})
        context.fastmcp_context.set_state.assert_any_await("user_session", mw.session, serializable=False)
        call_next.assert_awaited_once_with(context)

    @pytest.mark.asyncio
    async def test_on_request_without_request_context_skips_state(self, gs_session):
        mw = LocalUserAuthMiddleware()
        context = _context(request_context=None)
        call_next = AsyncMock(return_value="result")

        assert await mw.on_request(context, call_next) == "result"

        context.fastmcp_context.set_state.assert_not_awaited()


class TestRemoteUserAuthMiddleware:
    def test_environment_defaults_to_prod(self):
        assert RemoteUserAuthMiddleware().environment == Environment.PROD
        assert RemoteUserAuthMiddleware(None).environment == Environment.PROD
        assert RemoteUserAuthMiddleware(Environment.QA).environment == Environment.QA

    @pytest.mark.asyncio
    async def test_on_request_stores_non_serializable_state(self, monkeypatch, capsys):
        session = object()
        extract = AsyncMock(return_value=({"login": "jdoe"}, session))
        monkeypatch.setattr(middleware, "extract_from_starlette_request", extract)
        request = MagicMock()
        context = _context(request_context=MagicMock(request=request))
        call_next = AsyncMock(return_value="result")

        assert await RemoteUserAuthMiddleware(Environment.QA).on_request(context, call_next) == "result"

        extract.assert_awaited_once_with(request, Environment.QA)
        context.fastmcp_context.set_state.assert_any_await("user_profile", {"login": "jdoe"}, serializable=False)
        context.fastmcp_context.set_state.assert_any_await("user_session", session, serializable=False)
        assert "[session] Created session for: jdoe" in _printed(capsys)

    @pytest.mark.asyncio
    async def test_on_request_without_credentials_stores_nothing(self, monkeypatch):
        monkeypatch.setattr(middleware, "extract_from_starlette_request", AsyncMock(return_value=(None, None)))
        context = _context(request_context=MagicMock())
        call_next = AsyncMock(return_value="result")

        assert await RemoteUserAuthMiddleware().on_request(context, call_next) == "result"

        context.fastmcp_context.set_state.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_request_without_request_context_does_not_extract(self, monkeypatch):
        extract = AsyncMock()
        monkeypatch.setattr(middleware, "extract_from_starlette_request", extract)
        call_next = AsyncMock(return_value="result")

        assert await RemoteUserAuthMiddleware().on_request(_context(request_context=None), call_next) == "result"

        extract.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_on_call_tool_logs_user_and_tool(self, capsys):
        context = _context(state={"user_profile": {"login": "jdoe"}}, session_id="abc")
        context.message.name = "whois"
        call_next = AsyncMock(return_value="tool-result")

        assert await RemoteUserAuthMiddleware().on_call_tool(context, call_next) == "tool-result"

        # The bracketed tags are Rich-escaped, so they must be printed literally rather than treated as markup
        printed = _printed(capsys)
        assert "[abc] [call_tool" in printed
        assert "jdoe using tool whois" in printed

    @pytest.mark.asyncio
    async def test_on_call_tool_unknown_user(self, capsys):
        context = _context(state={}, session_id="abc")
        context.message.name = "whois"

        await RemoteUserAuthMiddleware().on_call_tool(context, AsyncMock())

        assert "unknown using tool whois" in _printed(capsys)

    @pytest.mark.asyncio
    async def test_on_list_tools_logs_user(self, capsys):
        context = _context(state={"user_profile": {"login": "jdoe"}}, session_id="abc")
        call_next = AsyncMock(return_value=["tool"])

        assert await RemoteUserAuthMiddleware().on_list_tools(context, call_next) == ["tool"]

        printed = _printed(capsys)
        assert "[abc] [tools/list" in printed
        assert printed.rstrip().endswith("jdoe")
