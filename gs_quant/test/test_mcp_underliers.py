"""
Copyright 2026 Senanur Çetin.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied. See the License for the
specific language governing permissions and limitations
under the License.
"""

import datetime as dt
from unittest.mock import MagicMock

import pytest

from gs_quant.mcp.tools.data import tools


def _session(payload):
    session = MagicMock()
    session.sync.get.return_value = payload
    return session


def test_get_underliers_empty_results_have_stable_payload():
    result = tools.get_underliers("MA123", user_session=_session({"results": []}))
    assert result == {
        "count": 0,
        "fullResultsURL": "https://marquee.gs.com/s/products/MA123/constituents",
        "underliers": [],
    }


def test_get_underliers_missing_results_key_is_reported():
    assert tools.get_underliers("MA123", user_session=_session({"total": 0})) == {
        "error": "Unexpected response format, no results"
    }


def test_get_underliers_missing_market_values_do_not_break_sorting():
    positions = [{"positionType": "close", "marketValue": i} for i in range(1, 23)]
    positions += [{"positionType": "close", "marketValue": None}, {"positionType": "close"}]
    result = tools.get_underliers("MA123", user_session=_session({"results": positions}))
    assert result["count"] == 24
    assert len(result["underliers"]) == 20
    assert [v["marketValue"] for v in result["underliers"]] == list(range(22, 2, -1))


def test_get_underliers_close_positions_preferred():
    positions = [{"positionType": "open", "marketValue": 500}, {"positionType": "close", "marketValue": 10}]
    result = tools.get_underliers("MA123", user_session=_session({"results": positions}))
    assert result["underliers"] == positions[1:]


def test_get_underliers_uses_as_of_endpoint():
    session = _session({"results": []})
    tools.get_underliers("MA123", as_of=dt.date(2024, 1, 2), user_session=session)
    assert session.sync.get.call_args.args[0].startswith(
        "/indices/MA123/positions/data?startDate=2024-01-02&endDate=2024-01-02&"
    )


def test_get_underliers_returns_api_errors():
    session = _session({})
    session.sync.get.side_effect = RuntimeError("API unavailable")
    assert tools.get_underliers("MA123", user_session=session) == {"error": "API unavailable"}
