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

from http.cookies import SimpleCookie
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.requests import Request

from gs_quant.mcp import session_utils
from gs_quant.mcp.session_utils import (
    AuthType,
    _get_auth_token_and_type,
    construct_session,
    extract_from_starlette_request,
    get_session_application_name,
    set_session_config,
)
from gs_quant.session import Environment


def _cookies(**values) -> SimpleCookie:
    cookies = SimpleCookie()
    for key, value in values.items():
        cookies[key] = value
    return cookies


def _request(headers: dict[str, str] | None = None) -> Request:
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": raw_headers})


@pytest.fixture(autouse=True)
def _isolated_state(monkeypatch):
    monkeypatch.setattr(session_utils, "_local_config", {})
    getattr(session_utils, "__session_cache").clear()
    yield
    getattr(session_utils, "__session_cache").clear()


class TestGetAuthTokenAndType:
    def test_gssso_cookie(self):
        assert _get_auth_token_and_type(_cookies(GSSSO="abc"), {}) == ("abc", AuthType.GSSSO)

    def test_marquee_login_cookie(self):
        assert _get_auth_token_and_type(_cookies(MarqueeLogin="xyz"), {}) == ("xyz", AuthType.MARQUEE_LOGIN)

    def test_bearer_header_preserves_token_case(self):
        assert _get_auth_token_and_type(_cookies(), {"Authorization": "Bearer AbCd"}) == ("AbCd", AuthType.OAUTH)

    def test_bearer_prefix_is_case_insensitive(self):
        assert _get_auth_token_and_type(_cookies(), {"Authorization": "bearer tok"}) == ("tok", AuthType.OAUTH)

    def test_cookies_take_precedence_over_header(self):
        headers = {"Authorization": "Bearer tok"}
        assert _get_auth_token_and_type(_cookies(GSSSO="a", MarqueeLogin="b"), headers)[1] == AuthType.GSSSO
        assert _get_auth_token_and_type(_cookies(MarqueeLogin="b"), headers)[1] == AuthType.MARQUEE_LOGIN

    def test_non_bearer_authorization_is_unknown(self):
        assert _get_auth_token_and_type(_cookies(), {"Authorization": "Basic dXNlcjpwdw=="}) == (None, AuthType.UNKNOWN)

    def test_no_credentials_is_unknown(self):
        assert _get_auth_token_and_type(_cookies(), {}) == (None, AuthType.UNKNOWN)


class TestSessionConfig:
    def test_default_application_name(self):
        assert get_session_application_name() == "gs-quant"

    def test_set_application_name(self):
        set_session_config("my-mcp-server")
        assert get_session_application_name() == "my-mcp-server"


class TestConstructSession:
    @pytest.mark.parametrize(
        "auth_type, expected_flags",
        [
            (AuthType.GSSSO, (True, False, False)),
            (AuthType.MARQUEE_LOGIN, (False, True, False)),
            (AuthType.JWT, (False, False, True)),
            (AuthType.OAUTH, (False, False, False)),
        ],
    )
    def test_flags_per_auth_type(self, monkeypatch, auth_type, expected_flags):
        get = MagicMock()
        monkeypatch.setattr(session_utils.GsSession, "get", get)
        cookies = _cookies(GSSSO="t")

        construct_session(Environment.QA, "tok", auth_type, cookies=cookies)

        get.assert_called_once_with(
            environment_or_domain=Environment.QA,
            application="gs-quant",
            token="tok",
            is_gssso=expected_flags[0],
            is_marquee_login=expected_flags[1],
            is_jwt_login=expected_flags[2],
            cookies=cookies,
        )

    def test_unknown_auth_type_raises(self):
        with pytest.raises(ValueError, match="Unknown auth type"):
            construct_session(Environment.PROD, None, AuthType.UNKNOWN)

    def test_application_name_precedence(self, monkeypatch):
        get = MagicMock()
        monkeypatch.setattr(session_utils.GsSession, "get", get)
        set_session_config("configured")

        construct_session(Environment.PROD, "t", AuthType.OAUTH)
        assert get.call_args.kwargs["application"] == "configured"

        construct_session(Environment.PROD, "t", AuthType.OAUTH, application_name_override="override")
        assert get.call_args.kwargs["application"] == "override"


@pytest.mark.asyncio
class TestExtractFromStarletteRequest:
    @staticmethod
    def _patch_session(monkeypatch, profile=None):
        session = MagicMock()
        session.async_.get = AsyncMock(return_value=profile or {"login": "jdoe"})
        construct = MagicMock(return_value=session)
        monkeypatch.setattr(session_utils, "construct_session", construct)
        return session, construct

    async def test_no_credentials_returns_none_pair(self, monkeypatch):
        _, construct = self._patch_session(monkeypatch)
        assert await extract_from_starlette_request(_request()) == (None, None)
        construct.assert_not_called()

    async def test_creates_and_initialises_session(self, monkeypatch):
        session, construct = self._patch_session(monkeypatch, {"login": "alice"})

        profile, result_session = await extract_from_starlette_request(
            _request({"Authorization": "Bearer tok"}), Environment.QA
        )

        assert profile == {"login": "alice"}
        assert result_session is session
        assert construct.call_args.args[:3] == (Environment.QA, "tok", AuthType.OAUTH)
        session.init.assert_called_once()
        session.async_.get.assert_awaited_once_with("/users/self")

    async def test_session_is_cached_per_token(self, monkeypatch):
        session, construct = self._patch_session(monkeypatch)
        request = _request({"Authorization": "Bearer tok"})

        first = await extract_from_starlette_request(request)
        second = await extract_from_starlette_request(request)

        assert first == second
        construct.assert_called_once()
        session.async_.get.assert_awaited_once()

    async def test_cache_is_keyed_by_token_and_environment(self, monkeypatch):
        _, construct = self._patch_session(monkeypatch)

        await extract_from_starlette_request(_request({"Authorization": "Bearer one"}), Environment.PROD)
        await extract_from_starlette_request(_request({"Authorization": "Bearer two"}), Environment.PROD)
        await extract_from_starlette_request(_request({"Authorization": "Bearer one"}), Environment.QA)

        assert construct.call_count == 3
