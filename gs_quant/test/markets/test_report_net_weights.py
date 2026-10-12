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

from gs_quant.errors import MqValueError
from gs_quant.markets.report import PerformanceReport


START = dt.date(2024, 1, 2)
END = dt.date(2024, 1, 5)


@pytest.fixture
def report():
    mock = MagicMock()
    mock.get_positions_data.return_value = [{"id": "MA1", "netWeight": 0.5}]
    return mock


def test_default_fields_do_not_accumulate_on_repeated_calls(report):
    for _ in range(3):
        PerformanceReport.get_position_net_weights(report, START, END)

    expected = ["id", "name", "ticker", "netWeight"]
    assert [call.kwargs["fields"] for call in report.get_positions_data.call_args_list] == [
        expected, expected, expected
    ]


def test_caller_fields_are_not_mutated(report):
    requested = ["gsid"]
    PerformanceReport.get_position_net_weights(
        report, START, END, asset_metadata_fields=requested
    )

    assert requested == ["gsid"]
    assert report.get_positions_data.call_args.kwargs["fields"] == ["gsid", "netWeight"]


def test_net_weight_field_is_not_duplicated(report):
    PerformanceReport.get_position_net_weights(
        report, START, END, asset_metadata_fields=["id", "netWeight"]
    )

    assert report.get_positions_data.call_args.kwargs["fields"] == ["id", "netWeight"]


def test_explicit_empty_fields_list_is_respected(report):
    PerformanceReport.get_position_net_weights(
        report, START, END, asset_metadata_fields=[]
    )

    assert report.get_positions_data.call_args.kwargs["fields"] == ["netWeight"]


def test_forwards_date_range_and_options(report):
    result = PerformanceReport.get_position_net_weights(
        report, START, END, position_type="close", include_all_business_days=False
    )

    report.get_positions_data.assert_called_once_with(
        start=START,
        end=END,
        fields=["id", "name", "ticker", "netWeight"],
        include_all_business_days=False,
        position_type="close",
    )
    assert result.to_dict("records") == [{"id": "MA1", "netWeight": 0.5}]


def test_existing_error_contract_is_preserved(report):
    report.get_positions_data.side_effect = RuntimeError("temporary failure")

    with pytest.raises(MqValueError, match="Error retrieving net weight data: temporary failure"):
        PerformanceReport.get_position_net_weights(report, START, END)
