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

from gs_quant.mcp.tools.marketview import tools


@pytest.fixture
def session():
    return MagicMock()


def _patch(monkeypatch, api, method, result=None):
    mock = MagicMock(return_value=result if result is not None else {"ok": True})
    monkeypatch.setattr(getattr(tools, api), method, mock)
    return mock


def test_search_dashboards_defaults(monkeypatch, session):
    api = _patch(monkeypatch, "GsMarketviewDashboardsApi", "get_dashboards")

    assert tools.search_dashboards(user_session=session) == {"ok": True}

    api.assert_called_once_with(ids=None, query=None, size=20, page=1, dashboard_type=None, author=None)


def test_search_dashboards_forwards_filters(monkeypatch, session):
    api = _patch(monkeypatch, "GsMarketviewDashboardsApi", "get_dashboards")

    tools.search_dashboards(
        query="rates", size=5, page=2, dashboard_type=["THEMATIC"], author=["guid"], user_session=session
    )

    api.assert_called_once_with(ids=None, query="rates", size=5, page=2, dashboard_type=["THEMATIC"], author=["guid"])


def test_get_dashboard(monkeypatch, session):
    api = _patch(monkeypatch, "GsMarketviewDashboardsApi", "get_dashboard")

    tools.get_dashboard("dash", expand=True, widget_limit=3, user_session=session)

    api.assert_called_once_with(dashboard_id="dash", expand=True, widget_limit=3)


@pytest.mark.parametrize(
    "tool, api, method",
    [
        (tools.get_trending_dashboards, "GsMarketviewDashboardsApi", "get_trending_dashboards"),
        (tools.get_personalized_dashboards, "GsMarketviewDashboardsApi", "get_personalized_dashboards"),
        (tools.get_trending_widgets, "GsMarketviewWidgetsApi", "get_trending_widgets"),
    ],
)
def test_limit_only_tools(monkeypatch, session, tool, api, method):
    mock = _patch(monkeypatch, api, method)

    assert tool(limit=3, user_session=session) == {"ok": True}
    tool(user_session=session)

    assert [c.kwargs for c in mock.call_args_list] == [{"limit": 3}, {"limit": 10}]


def test_search_widgets(monkeypatch, session):
    api = _patch(monkeypatch, "GsMarketviewWidgetsApi", "get_widgets")

    tools.search_widgets(query="vol", tags=["fx"], metadata=True, user_session=session)

    api.assert_called_once_with(ids=None, query="vol", limit=20, offset=0, author=None, tags=["fx"], metadata=True)


def test_get_widget(monkeypatch, session):
    api = _patch(monkeypatch, "GsMarketviewWidgetsApi", "get_widget")

    tools.get_widget("w1", merge_params=True, user_session=session)

    api.assert_called_once_with(widget_id="w1", merge_params=True)


def test_get_personalized_widgets(monkeypatch, session):
    api = _patch(monkeypatch, "GsMarketviewWidgetsApi", "get_personalized_widgets")

    tools.get_personalized_widgets(limit=4, metadata=True, user_session=session)

    api.assert_called_once_with(limit=4, metadata=True)


def test_tools_run_inside_the_user_session(monkeypatch, session):
    _patch(monkeypatch, "GsMarketviewWidgetsApi", "get_widget")

    tools.get_widget("w1", user_session=session)

    session.__enter__.assert_called_once()
    session.__exit__.assert_called_once()
