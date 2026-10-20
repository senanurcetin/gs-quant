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

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp.exceptions import ToolError

from gs_quant.mcp.dependencies import user_profile_from_ctx, user_session_from_ctx


def _ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.get_state = AsyncMock(side_effect=lambda key: state.get(key))
    return ctx


@pytest.mark.asyncio
async def test_user_profile_from_ctx_returns_profile():
    ctx = _ctx({"user_profile": {"login": "jdoe"}})
    assert await user_profile_from_ctx(ctx) == {"login": "jdoe"}
    ctx.get_state.assert_awaited_once_with("user_profile")


@pytest.mark.asyncio
async def test_user_profile_from_ctx_rejects_unauthenticated():
    with pytest.raises(ToolError, match="User not authenticated"):
        await user_profile_from_ctx(_ctx({}))


@pytest.mark.asyncio
async def test_user_session_from_ctx_returns_session():
    session = object()
    ctx = _ctx({"user_session": session})
    assert await user_session_from_ctx(ctx) is session
    ctx.get_state.assert_awaited_once_with("user_session")


@pytest.mark.asyncio
async def test_user_session_from_ctx_rejects_unauthenticated():
    with pytest.raises(ToolError, match="User not authenticated"):
        await user_session_from_ctx(_ctx({}))
