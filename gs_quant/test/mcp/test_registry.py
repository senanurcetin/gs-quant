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
from fastmcp.tools import tool

from gs_quant.mcp.tools import registry
from gs_quant.mcp.tools.registry import discover_tools, get_registered_tools, mcp_tool, register_mcp_tool


@pytest.fixture
def isolated_registry(monkeypatch):
    monkeypatch.setattr(registry, "_TOOL_REGISTRY", {})


def test_mcp_tool_registers_by_qualified_name(isolated_registry):
    @mcp_tool(tags={"unit"})
    def sample(a: int) -> int:
        """Adds one"""
        return a + 1

    assert list(get_registered_tools()) == [f"{sample.__module__}.{sample.__qualname__}"]
    assert get_registered_tools()[f"{sample.__module__}.{sample.__qualname__}"] is sample


def test_mcp_tool_leaves_function_callable_and_forwards_tool_args(isolated_registry):
    @mcp_tool(tags={"unit", "other"})
    def sample(a: int) -> int:
        """Adds one"""
        return a + 1

    assert sample(1) == 2
    assert sample.__fastmcp__.tags == {"unit", "other"}


def test_register_mcp_tool_requires_fastmcp_decorator(isolated_registry):
    def plain():
        pass

    with pytest.raises(ValueError, match="already decorated with @tool"):
        register_mcp_tool(plain)
    assert get_registered_tools() == {}


def test_register_mcp_tool_returns_function_unchanged(isolated_registry):
    @register_mcp_tool
    @tool(tags={"unit"})
    def sample() -> str:
        """Says hi"""
        return "hi"

    assert sample() == "hi"
    assert len(get_registered_tools()) == 1


def test_get_registered_tools_returns_a_copy(isolated_registry):
    @mcp_tool()
    def sample() -> None:
        """Does nothing"""

    snapshot = get_registered_tools()
    snapshot.clear()
    assert len(get_registered_tools()) == 1


def test_discover_tools_imports_all_submodules():
    tools = discover_tools("gs_quant.mcp.tools")

    expected = {
        "gs_quant.mcp.tools.users.tools.current_user_info",
        "gs_quant.mcp.tools.users.tools.whois",
        "gs_quant.mcp.tools.data.tools.get_daily_data",
        "gs_quant.mcp.tools.data.tools.get_underliers",
        "gs_quant.mcp.tools.marketview.tools.search_dashboards",
        "gs_quant.mcp.tools.marketview.tools.get_widget",
    }
    assert expected <= set(tools)
