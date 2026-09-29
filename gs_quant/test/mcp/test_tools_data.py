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
import json
from unittest.mock import MagicMock

import pandas as pd
import pytest
from freezegun import freeze_time

from gs_quant.markets.securities import AssetIdentifier
from gs_quant.mcp.tools.data import tools


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def dataset(monkeypatch):
    ds = MagicMock()
    ds.get_data.return_value = pd.DataFrame({"bbid": ["AAPL"], "close": [1.5]})
    ds.get_data_last.return_value = pd.DataFrame({"bbid": ["AAPL"], "close": [2.5]})
    ds.get_coverage.return_value = pd.DataFrame({"bbid": ["AAPL", "MSFT"]})
    dataset_cls = MagicMock(return_value=ds)
    monkeypatch.setattr(tools, "Dataset", dataset_cls)
    return ds


def _rows(payload: dict) -> list[dict]:
    return payload["data"]


class TestDatasetTools:
    def test_get_daily_data(self, dataset, session):
        start, end = dt.date(2024, 1, 1), dt.date(2024, 1, 31)

        result = tools.get_daily_data("EDRVOL", "AAPL", start, end, user_session=session)

        dataset.get_data.assert_called_once_with(start, end, bbid="AAPL")
        assert _rows(result) == [{"index": 0, "bbid": "AAPL", "close": 1.5}]
        json.dumps(result)  # must be JSON serialisable for the MCP transport

    def test_get_intraday_data(self, dataset, session):
        start, end = dt.datetime(2024, 1, 1, 9, 30), dt.datetime(2024, 1, 1, 16)

        result = tools.get_intraday_data("TRADES", "AAPL", start, end, user_session=session)

        dataset.get_data.assert_called_once_with(start, end, bbid="AAPL")
        assert _rows(result)[0]["bbid"] == "AAPL"

    def test_get_last_data_uses_given_date(self, dataset, session):
        as_of = dt.date(2024, 5, 1)

        result = tools.get_last_data("EDRVOL", bbid="AAPL", asset_id="MA123", as_of=as_of, user_session=session)

        dataset.get_data_last.assert_called_once_with(bbid="AAPL", assetId="MA123", as_of=as_of)
        assert _rows(result)[0]["close"] == 2.5

    @freeze_time("2024-06-03")
    def test_get_last_data_defaults_to_today(self, dataset, session):
        tools.get_last_data("EDRVOL", user_session=session)

        dataset.get_data_last.assert_called_once_with(bbid=None, assetId=None, as_of=dt.date(2024, 6, 3))

    def test_get_dataset_coverage(self, dataset, session):
        result = tools.get_dataset_coverage("EDRVOL", user_session=session)

        assert [row["bbid"] for row in _rows(result)] == ["AAPL", "MSFT"]

    def test_tools_run_inside_the_user_session(self, dataset, session):
        tools.get_dataset_coverage("EDRVOL", user_session=session)

        session.__enter__.assert_called_once()
        session.__exit__.assert_called_once()


class _Asset:
    name = "Apple Inc"
    description = "Consumer electronics"

    def get_marquee_id(self):
        return "MA123"

    def get_identifiers(self):
        return {"bbid": "AAPL UW", "isin": "US0378331005"}

    def get_type(self):
        return "Single Stock"

    def get_currency(self):
        return "USD"


class TestFindAssetIdentifiers:
    @pytest.fixture
    def get_asset(self, monkeypatch):
        mock = MagicMock(return_value=_Asset())
        monkeypatch.setattr(tools.SecurityMaster, "get_asset", mock)
        return mock

    @pytest.mark.parametrize(
        "flags, expected",
        [
            ({}, AssetIdentifier.TICKER),
            ({"is_bloomberg_id": True}, AssetIdentifier.BLOOMBERG_ID),
            ({"is_isin": True}, AssetIdentifier.ISIN),
            ({"is_marquee_id": True}, AssetIdentifier.MARQUEE_ID),
            ({"is_ric": True}, AssetIdentifier.REUTERS_ID),
        ],
    )
    def test_identifier_type_selection(self, get_asset, session, flags, expected):
        tools.find_asset_identifiers("AAPL", user_session=session, **flags)

        get_asset.assert_called_once_with("AAPL", expected)

    def test_returns_asset_details(self, get_asset, session):
        result = tools.find_asset_identifiers("AAPL", user_session=session)

        assert result == {
            "name": "Apple Inc",
            "type": "Single Stock",
            "currency": "USD",
            "description": "Consumer electronics",
            "identifiers": {"marquee_id": "MA123", "bbid": "AAPL UW", "isin": "US0378331005"},
        }

    def test_optional_attributes_default_to_none(self, monkeypatch, session):
        class Bare:
            name = "Bare"

            def get_marquee_id(self):
                return "MA1"

            def get_identifiers(self):
                return {}

            def get_type(self):
                return "Index"

        monkeypatch.setattr(tools.SecurityMaster, "get_asset", MagicMock(return_value=Bare()))

        result = tools.find_asset_identifiers("X", user_session=session)

        assert result["currency"] is None and result["description"] is None

    def test_asset_not_found(self, monkeypatch, session):
        monkeypatch.setattr(tools.SecurityMaster, "get_asset", MagicMock(return_value=None))

        assert tools.find_asset_identifiers("nope", user_session=session) == {"error": "Asset not found"}


class TestGetUnderliers:
    @staticmethod
    def _position(value=1.0, position_type="close"):
        return {"positionType": position_type, "marketValue": value}

    @staticmethod
    def _session(response):
        session = MagicMock()
        session.sync.get.return_value = response
        return session

    def test_uses_last_positions_endpoint_by_default(self):
        session = self._session({"results": [self._position()]})

        tools.get_underliers("MA123", user_session=session)

        url = session.sync.get.call_args.args[0]
        assert url.startswith("/indices/MA123/positions/last/data?")
        assert "fields=underlyingAssetId" in url and "&fields=bbid" in url

    def test_uses_date_range_endpoint_when_as_of_given(self):
        session = self._session({"results": [self._position()]})

        tools.get_underliers("MA123", as_of=dt.date(2024, 3, 4), user_session=session)

        assert session.sync.get.call_args.args[0].startswith(
            "/indices/MA123/positions/data?startDate=2024-03-04&endDate=2024-03-04&"
        )

    def test_returns_all_positions_when_at_most_twenty(self):
        positions = [self._position(i) for i in range(20)]

        result = tools.get_underliers("MA123", user_session=self._session({"results": positions}))

        assert result == {
            "count": 20,
            "fullResultsURL": "https://marquee.gs.com/s/products/MA123/constituents",
            "underliers": positions,
        }

    def test_prefers_close_positions(self):
        close, other = self._position(1), self._position(2, position_type="open")

        result = tools.get_underliers("MA123", user_session=self._session({"results": [other, close]}))

        assert result["underliers"] == [close]

    def test_falls_back_to_all_results_when_no_close_positions(self):
        results = [self._position(1, position_type="open")]

        result = tools.get_underliers("MA123", user_session=self._session({"results": results}))

        assert result["underliers"] == results

    def test_truncates_to_top_twenty_by_market_value(self):
        positions = [self._position(i) for i in range(30)]

        result = tools.get_underliers("MA123", user_session=self._session({"results": positions}))

        assert result["count"] == 30
        assert "limitedTo" in result
        assert [p["marketValue"] for p in result["underliers"]] == list(range(29, 9, -1))

    def test_truncation_tolerates_missing_and_null_market_values(self):
        positions = [self._position(i) for i in range(1, 22)] + [self._position(None), {"positionType": "close"}]

        result = tools.get_underliers("MA123", user_session=self._session({"results": positions}))

        assert result["count"] == 23
        assert len(result["underliers"]) == 20
        assert all(p.get("marketValue") for p in result["underliers"])

    def test_empty_results_return_an_empty_payload(self):
        # Regression: this used to fall off the end of the function and return None
        result = tools.get_underliers("MA123", user_session=self._session({"results": []}))

        assert result == {
            "count": 0,
            "fullResultsURL": "https://marquee.gs.com/s/products/MA123/constituents",
            "underliers": [],
        }

    def test_missing_results_key_is_reported(self):
        result = tools.get_underliers("MA123", user_session=self._session({"totalResults": 0}))

        assert result == {"error": "Unexpected response format, no results"}

    def test_api_errors_are_returned_not_raised(self):
        session = MagicMock()
        session.sync.get.side_effect = RuntimeError("boom")

        assert tools.get_underliers("MA123", user_session=session) == {"error": "boom"}
