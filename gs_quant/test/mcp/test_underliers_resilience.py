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

from unittest.mock import MagicMock

import pytest

from gs_quant.mcp.tools.data.tools import get_underliers


def _session(response):
    session = MagicMock()
    session.sync.get.return_value = response
    return session


def test_empty_position_list_returns_stable_payload():
    result = get_underliers("MA123", user_session=_session({"results": []}))

    assert result == {
        "count": 0,
        "fullResultsURL": "https://marquee.gs.com/s/products/MA123/constituents",
        "underliers": [],
    }


@pytest.mark.parametrize("response", [{"results": None}, {"results": {}}, None])
def test_unexpected_result_types_return_an_error(response):
    result = get_underliers("MA123", user_session=_session(response))

    assert "error" in result
    assert "Unexpected response format" in result["error"]


def test_empty_results_key_is_distinct_from_missing_key():
    result = get_underliers("MA123", user_session=_session({}))

    assert result == {"error": "Unexpected response format, no results"}


def test_null_market_values_do_not_break_ranking():
    positions = [
        {"positionType": "close", "marketValue": value}
        for value in range(1, 22)
    ]
    positions.append({"positionType": "close", "marketValue": None})

    result = get_underliers("MA123", user_session=_session({"results": positions}))

    assert result["count"] == 22
    assert len(result["underliers"]) == 20
    assert [p["marketValue"] for p in result["underliers"]] == list(range(21, 1, -1))


def test_close_positions_are_preferred_over_open_positions():
    response = {"results": [
        {"positionType": "open", "marketValue": 100},
        {"positionType": "close", "marketValue": 5},
    ]}
    result = get_underliers("MA123", user_session=_session(response))

    assert result["count"] == 1
    assert result["underliers"] == [{"positionType": "close", "marketValue": 5}]
