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
from freezegun import freeze_time

from gs_quant.risk import scenario_utils


@pytest.fixture
def mocked_dependencies(monkeypatch):
    asset = MagicMock()
    asset.get_marquee_id.return_value = "MA123"
    asset.get_identifier.return_value = "AAPL.OQ"
    security = MagicMock()
    security.get_asset.return_value = asset
    dataset = MagicMock()
    dataset.get_data.return_value = "vol-data"
    dataset_type = MagicMock(return_value=dataset)
    scenario_type = MagicMock()
    scenario_type.from_dataframe.return_value = "scenario"

    monkeypatch.setattr(scenario_utils, "SecurityMaster", security)
    monkeypatch.setattr(scenario_utils, "Dataset", dataset_type)
    monkeypatch.setattr(scenario_utils, "MarketDataVolShockScenario", scenario_type)
    return dataset


def test_eod_default_date_is_computed_per_call(mocked_dependencies):
    with freeze_time("2031-03-04"):
        scenario_utils.build_eq_vol_scenario_eod("AAPL.OQ", "EDRVOL")
    with freeze_time("2031-03-05"):
        scenario_utils.build_eq_vol_scenario_eod("AAPL.OQ", "EDRVOL")

    pairs = [
        (call.kwargs["startDate"], call.kwargs["endDate"])
        for call in mocked_dependencies.get_data.call_args_list
    ]
    assert pairs == [
        (dt.date(2031, 3, 4), dt.date(2031, 3, 4)),
        (dt.date(2031, 3, 5), dt.date(2031, 3, 5)),
    ]


def test_intraday_default_window_moves_with_clock(mocked_dependencies):
    with freeze_time("2031-03-04 12:00:00"):
        scenario_utils.build_eq_vol_scenario_intraday("AAPL.OQ", "INTRADAY")
    with freeze_time("2031-03-04 15:30:00"):
        scenario_utils.build_eq_vol_scenario_intraday("AAPL.OQ", "INTRADAY")

    pairs = [
        (call.kwargs["startTime"], call.kwargs["endTime"])
        for call in mocked_dependencies.get_data.call_args_list
    ]
    assert pairs == [
        (dt.datetime(2031, 3, 4, 11), dt.datetime(2031, 3, 4, 12)),
        (dt.datetime(2031, 3, 4, 14, 30), dt.datetime(2031, 3, 4, 15, 30)),
    ]


def test_intraday_default_start_is_relative_to_explicit_end(mocked_dependencies):
    end = dt.datetime(2024, 1, 2, 10, 30)

    scenario_utils.build_eq_vol_scenario_intraday(
        "AAPL.OQ", "INTRADAY", end_time=end
    )

    kwargs = mocked_dependencies.get_data.call_args.kwargs
    assert kwargs["startTime"] == dt.datetime(2024, 1, 2, 9, 30)
    assert kwargs["endTime"] == end


def test_explicit_eod_date_is_preserved(mocked_dependencies):
    requested_date = dt.date(2024, 1, 2)

    with freeze_time("2031-03-05"):
        scenario_utils.build_eq_vol_scenario_eod(
            "AAPL.OQ", "EDRVOL", vol_date=requested_date
        )

    kwargs = mocked_dependencies.get_data.call_args.kwargs
    assert kwargs["startDate"] == requested_date
    assert kwargs["endDate"] == requested_date
