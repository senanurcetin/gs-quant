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

from gs_quant.errors import MqValueError
from gs_quant.markets.report import PerformanceReport

START, END = dt.date(2024, 1, 2), dt.date(2024, 1, 5)


@pytest.fixture
def report():
    mock = MagicMock()
    mock.get_positions_data.return_value = [{"id": "MA1", "netWeight": 0.5}]
    return mock


def _fields(report) -> list[str]:
    return report.get_positions_data.call_args.kwargs["fields"]


def test_default_fields_and_forwarded_arguments(report):
    result = PerformanceReport.get_position_net_weights(report, START, END, position_type="close")

    report.get_positions_data.assert_called_once_with(
        start=START,
        end=END,
        fields=["id", "name", "ticker", "netWeight"],
        include_all_business_days=True,
        position_type="close",
    )
    assert result.to_dict("records") == [{"id": "MA1", "netWeight": 0.5}]


def test_repeated_calls_do_not_accumulate_fields(report):
    # Regression: "netWeight" used to be appended to the shared default list on every call
    for _ in range(3):
        PerformanceReport.get_position_net_weights(report, START, END)

    assert [c.kwargs["fields"] for c in report.get_positions_data.call_args_list] == [
        ["id", "name", "ticker", "netWeight"]
    ] * 3


def test_callers_list_is_not_mutated(report):
    fields = ["gsid"]

    PerformanceReport.get_position_net_weights(report, START, END, asset_metadata_fields=fields)

    assert fields == ["gsid"]
    assert _fields(report) == ["gsid", "netWeight"]


def test_net_weight_is_not_duplicated(report):
    PerformanceReport.get_position_net_weights(report, START, END, asset_metadata_fields=["id", "netWeight"])

    assert _fields(report) == ["id", "netWeight"]


def test_empty_field_list_is_respected(report):
    PerformanceReport.get_position_net_weights(report, START, END, asset_metadata_fields=[])

    assert _fields(report) == ["netWeight"]


def test_errors_are_wrapped(report):
    report.get_positions_data.side_effect = RuntimeError("boom")

    with pytest.raises(MqValueError, match="Error retrieving net weight data: boom"):
        PerformanceReport.get_position_net_weights(report, START, END)
