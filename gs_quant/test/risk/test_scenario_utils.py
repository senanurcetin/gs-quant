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
from unittest.mock import MagicMock

import pytest
from freezegun import freeze_time

from gs_quant.markets.securities import AssetIdentifier
from gs_quant.risk import scenario_utils
from gs_quant.risk.scenario_utils import build_eq_vol_scenario_eod, build_eq_vol_scenario_intraday


@pytest.fixture
def mocks(monkeypatch):
    asset = MagicMock()
    asset.get_marquee_id.return_value = "MA123"
    asset.get_identifier.return_value = "AAPL.OQ"
    security_master = MagicMock()
    security_master.get_asset.return_value = asset
    dataset = MagicMock()
    dataset.get_data.return_value = "vol-data"
    dataset_cls = MagicMock(return_value=dataset)
    scenario_cls = MagicMock()
    scenario_cls.from_dataframe.return_value = "scenario"
    monkeypatch.setattr(scenario_utils, "SecurityMaster", security_master)
    monkeypatch.setattr(scenario_utils, "Dataset", dataset_cls)
    monkeypatch.setattr(scenario_utils, "MarketDataVolShockScenario", scenario_cls)
    return MagicMock(
        security_master=security_master, asset=asset, dataset_cls=dataset_cls, dataset=dataset, scenario=scenario_cls
    )


class TestEod:
    def test_builds_scenario_from_dataset(self, mocks):
        vol_date = dt.date(2024, 1, 2)

        result = build_eq_vol_scenario_eod("AAPL.OQ", "EDRVOL", ref_spot=190.5, vol_date=vol_date)

        assert result == "scenario"
        mocks.security_master.get_asset.assert_called_once_with("AAPL.OQ", AssetIdentifier.REUTERS_ID)
        mocks.dataset_cls.assert_called_once_with("EDRVOL")
        mocks.dataset.get_data.assert_called_once_with(
            assetId=["MA123"], strikeReference="forward", startDate=vol_date, endDate=vol_date
        )
        mocks.asset.get_identifier.assert_called_once_with(AssetIdentifier.REUTERS_ID)
        mocks.scenario.from_dataframe.assert_called_once_with("AAPL.OQ", "vol-data", 190.5)

    def test_asset_name_type_is_forwarded(self, mocks):
        build_eq_vol_scenario_eod("AAPL UW", "EDRVOL", asset_name_type=AssetIdentifier.BLOOMBERG_ID)

        mocks.security_master.get_asset.assert_called_once_with("AAPL UW", AssetIdentifier.BLOOMBERG_ID)

    def test_default_date_is_evaluated_at_call_time(self, mocks):
        # Regression: the default used to be evaluated once at import time and go stale in long-running processes
        with freeze_time("2031-03-04"):
            build_eq_vol_scenario_eod("AAPL.OQ", "EDRVOL")
        with freeze_time("2031-03-05"):
            build_eq_vol_scenario_eod("AAPL.OQ", "EDRVOL")

        dates = [(c.kwargs["startDate"], c.kwargs["endDate"]) for c in mocks.dataset.get_data.call_args_list]
        assert dates == [(dt.date(2031, 3, 4),) * 2, (dt.date(2031, 3, 5),) * 2]


class TestIntraday:
    def test_builds_scenario_from_dataset(self, mocks):
        start, end = dt.datetime(2024, 1, 2, 9), dt.datetime(2024, 1, 2, 10)

        result = build_eq_vol_scenario_intraday("AAPL.OQ", "INTRADAY", start_time=start, end_time=end)

        assert result == "scenario"
        mocks.dataset.get_data.assert_called_once_with(
            assetId=["MA123"], strikeReference="forward", startTime=start, endTime=end
        )
        mocks.scenario.from_dataframe.assert_called_once_with("AAPL.OQ", "vol-data", None)

    def test_default_window_is_the_last_hour_at_call_time(self, mocks):
        # Regression: both defaults used to be evaluated once at import time
        with freeze_time("2031-03-04 12:00:00"):
            build_eq_vol_scenario_intraday("AAPL.OQ", "INTRADAY")
        with freeze_time("2031-03-04 15:30:00"):
            build_eq_vol_scenario_intraday("AAPL.OQ", "INTRADAY")

        windows = [(c.kwargs["startTime"], c.kwargs["endTime"]) for c in mocks.dataset.get_data.call_args_list]
        assert windows == [
            (dt.datetime(2031, 3, 4, 11), dt.datetime(2031, 3, 4, 12)),
            (dt.datetime(2031, 3, 4, 14, 30), dt.datetime(2031, 3, 4, 15, 30)),
        ]

    def test_start_defaults_to_one_hour_before_a_given_end(self, mocks):
        end = dt.datetime(2024, 1, 2, 10, 30)

        build_eq_vol_scenario_intraday("AAPL.OQ", "INTRADAY", end_time=end)

        kwargs = mocks.dataset.get_data.call_args.kwargs
        assert (kwargs["startTime"], kwargs["endTime"]) == (dt.datetime(2024, 1, 2, 9, 30), end)
