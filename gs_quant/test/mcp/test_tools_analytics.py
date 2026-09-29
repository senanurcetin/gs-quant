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

import numpy as np
import pandas as pd
import pytest
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

from gs_quant.mcp.tools.analytics import tools
from gs_quant.mcp.tools.registry import discover_tools
from gs_quant.timeseries.risk_metrics import VaRMethod, risk_summary, value_at_risk

RETURNS = list(np.random.default_rng(1).normal(0.0005, 0.01, 400))
DATES = [d.date() for d in pd.bdate_range("2022-01-03", periods=400)]
BENCHMARK = list(np.random.default_rng(2).normal(0.0004, 0.01, 400))
PORTFOLIO = [b + a for b, a in zip(BENCHMARK, np.random.default_rng(3).normal(0.0002, 0.003, 400))]


def _input_schema(tool) -> dict:
    # renamed in newer FastMCP releases
    return getattr(tool, "input_schema", None) or tool.inputSchema


class _InjectSession(Middleware):
    """Stands in for the auth middleware: puts a user session into the request state"""

    def __init__(self, session):
        self.session = session

    async def on_request(self, context, call_next):
        await context.fastmcp_context.set_state("user_session", self.session, serializable=False)
        return await call_next(context)


def _server(session=None) -> FastMCP:
    mcp = FastMCP("test")
    for tool in discover_tools("gs_quant.mcp.tools.analytics").values():
        mcp.add_tool(tool)
    if session is not None:
        mcp.add_middleware(_InjectSession(session))
    return mcp


async def _call(name: str, arguments: dict, session=None) -> dict:
    async with Client(_server(session)) as client:
        result = await client.call_tool(name, arguments)
    return result.structured_content


# ----------------------------------------------------------------------------------------------------------------------
# Through the MCP protocol
# ----------------------------------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_are_discoverable_with_descriptions_and_schemas():
    async with Client(_server()) as client:
        listed = {t.name: t for t in await client.list_tools()}

    assert {
        "risk_summary_from_returns",
        "backtest_value_at_risk",
        "compare_with_benchmark",
        "asset_risk_summary",
    } <= set(listed)
    schema = _input_schema(listed["risk_summary_from_returns"])
    assert schema["required"] == ["returns"]
    assert "Simple periodic returns" in schema["properties"]["returns"]["description"]
    assert _input_schema(listed["backtest_value_at_risk"])["properties"]["method"]["enum"] == [
        "historical",
        "parametric",
        "cornish_fisher",
    ]
    assert all(t.description for t in listed.values())


@pytest.mark.asyncio
async def test_risk_summary_over_the_protocol_matches_the_library():
    payload = await _call("risk_summary_from_returns", {"returns": RETURNS, "confidence": 0.99})

    expected = risk_summary(pd.Series(RETURNS), confidence=0.99, annualization_factor=252).to_dict()
    assert payload["summary"] == pytest.approx(expected)
    assert "assumed to be 252" in payload["assumptions"][0]
    assert "Losses are negative" in payload["conventions"]


@pytest.mark.asyncio
async def test_dates_are_used_to_infer_the_frequency():
    weekly = [d.date() for d in pd.date_range("2022-01-02", periods=100, freq="W")]

    payload = await _call(
        "risk_summary_from_returns",
        {"returns": RETURNS[:100], "dates": [str(d) for d in weekly]},
    )

    assert payload["summary"]["periods_per_year"] == 52
    assert "inferred" in payload["assumptions"][0]


@pytest.mark.asyncio
async def test_output_is_strict_json():
    # null, not NaN or Infinity, for statistics that are undefined (no losses at all)
    payload = await _call("risk_summary_from_returns", {"returns": [0.01, 0.02, 0.015, 0.03, 0.005]})

    json.dumps(payload, allow_nan=False)
    assert payload["summary"]["sortino_ratio"] is None


@pytest.mark.asyncio
async def test_backtest_over_the_protocol():
    payload = await _call(
        "backtest_value_at_risk",
        {"returns": RETURNS, "dates": [str(d) for d in DATES], "confidence": 0.95, "window": 100},
    )

    result = payload["result"]
    assert result["observations"] == 400 - 100
    assert result["method"] == "parametric" and result["window"] == 100
    assert 0 <= result["p_value"] <= 1
    assert payload["interpretation"].startswith("Model rejected" if result["reject"] else "Model not rejected")


@pytest.mark.asyncio
async def test_invalid_input_is_reported_to_the_client_as_a_tool_error():
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="must not be empty"):
            await client.call_tool("risk_summary_from_returns", {"returns": []})


@pytest.mark.asyncio
async def test_schema_violations_are_rejected_before_the_tool_runs():
    async with Client(_server()) as client:
        with pytest.raises(ToolError):
            await client.call_tool("backtest_value_at_risk", {"returns": RETURNS, "method": "made_up"})


@pytest.mark.asyncio
async def test_asset_risk_summary_receives_the_injected_session(monkeypatch):
    prices = pd.DataFrame(
        {"closePrice": 100 * np.cumprod(1 + np.array(RETURNS[:60]))},
        index=pd.DatetimeIndex(pd.bdate_range("2024-01-02", periods=60), name="date"),
    )
    dataset = MagicMock()
    dataset.get_data.return_value = prices
    monkeypatch.setattr(tools, "Dataset", MagicMock(return_value=dataset))
    session = MagicMock()

    payload = await _call(
        "asset_risk_summary",
        {"dataset_name": "PRICES", "bbid": "AAPL UW", "start_date": "2024-01-02", "end_date": "2024-03-25"},
        session=session,
    )

    dataset.get_data.assert_called_once_with(dt.date(2024, 1, 2), dt.date(2024, 3, 25), bbid="AAPL UW")
    session.__enter__.assert_called_once()
    assert payload["summary"]["observations"] == 59
    assert payload["asset"] == {"bbid": "AAPL UW", "dataset": "PRICES", "column": "closePrice"}


@pytest.mark.asyncio
async def test_asset_risk_summary_without_authentication_fails_cleanly():
    async with Client(_server()) as client:
        with pytest.raises(ToolError, match="not authenticated"):
            await client.call_tool(
                "asset_risk_summary",
                {"dataset_name": "PRICES", "bbid": "X", "start_date": "2024-01-02", "end_date": "2024-01-31"},
            )


# ----------------------------------------------------------------------------------------------------------------------
# Tool logic
# ----------------------------------------------------------------------------------------------------------------------


class TestInputValidation:
    @pytest.mark.parametrize(
        "values, dates, message",
        [
            ([], None, "must not be empty"),
            ([0.01, float("nan")], None, "finite"),
            ([0.01, float("inf")], None, "finite"),
            ([0.01, 0.02], [dt.date(2024, 1, 2)], "1 entries but returns has 2"),
            ([0.01, 0.02], [dt.date(2024, 1, 3), dt.date(2024, 1, 2)], "strictly increasing"),
            ([0.01, 0.02], [dt.date(2024, 1, 2), dt.date(2024, 1, 2)], "strictly increasing"),
        ],
    )
    def test_series_rejects_bad_input(self, values, dates, message):
        with pytest.raises(ToolError, match=message):
            tools._series(values, dates, "returns")

    def test_series_rejects_oversized_input(self):
        with pytest.raises(ToolError, match="maximum"):
            tools._series([0.0] * (tools.MAX_OBSERVATIONS + 1), None, "returns")

    def test_series_uses_dates_as_the_index(self):
        series = tools._series([0.01, 0.02], [dt.date(2024, 1, 2), dt.date(2024, 1, 3)], "returns")

        assert isinstance(series.index, pd.DatetimeIndex)

    def test_library_errors_become_tool_errors(self):
        with pytest.raises(ToolError, match="-100%"):
            tools.risk_summary_from_returns([0.01, -1.5, 0.02])

        with pytest.raises(ToolError, match="confidence"):
            tools.risk_summary_from_returns(RETURNS, confidence=1.5)


class TestRiskSummary:
    def test_explicit_periods_per_year_needs_no_assumption(self):
        payload = tools.risk_summary_from_returns(RETURNS, periods_per_year=12)

        assert payload["summary"]["periods_per_year"] == 12
        assert payload["assumptions"] == []

    def test_minimum_acceptable_return_is_forwarded(self):
        zero = tools.risk_summary_from_returns(RETURNS)["summary"]
        higher = tools.risk_summary_from_returns(RETURNS, minimum_acceptable_return=0.002)["summary"]

        assert higher["downside_deviation"] > zero["downside_deviation"]


class TestBacktest:
    def test_no_look_ahead(self):
        # The forecast for each date only uses earlier returns: a huge final shock cannot change earlier forecasts
        calm = [0.001, -0.001] * 100
        shocked = calm[:-1] + [-0.5]

        base = tools.backtest_value_at_risk(calm, window=50, confidence=0.95, method="historical")["result"]
        with_shock = tools.backtest_value_at_risk(shocked, window=50, confidence=0.95, method="historical")["result"]

        assert with_shock["exceedances"] == base["exceedances"] + 1  # only the shocked day itself is a new breach
        assert with_shock["observations"] == base["observations"]

    def test_forecasts_are_full_window_and_lagged(self):
        series = pd.Series(RETURNS)
        expected_forecast = value_at_risk(series, 0.99, VaRMethod.PARAMETRIC, w=tools.Window(60, 59)).shift(1)
        aligned_returns, aligned_forecast = series.align(expected_forecast.dropna(), join='inner')
        expected_breaches = int((aligned_returns < aligned_forecast).sum())

        result = tools.backtest_value_at_risk(RETURNS, window=60, confidence=0.99)["result"]

        assert result["exceedances"] == expected_breaches
        assert result["observations"] == len(RETURNS) - 60

    def test_requires_enough_history(self):
        with pytest.raises(ToolError, match="Need more than"):
            tools.backtest_value_at_risk(RETURNS[:100], window=100)
        with pytest.raises(ToolError, match="at least 30"):
            tools.backtest_value_at_risk(RETURNS, window=10)

    def test_a_badly_specified_model_is_rejected(self):
        # a regime shift to much higher volatility that the 60 day window is slow to notice
        calm = list(np.random.default_rng(9).normal(0, 0.005, 300))
        wild = list(np.random.default_rng(10).normal(0, 0.03, 300))

        result = tools.backtest_value_at_risk(calm + wild, window=250, confidence=0.99)

        assert result["result"]["reject"] is True
        assert result["interpretation"].startswith("Model rejected")


class TestCompareWithBenchmark:
    def test_metrics(self):
        payload = tools.compare_with_benchmark(PORTFOLIO, BENCHMARK)

        active = np.array(PORTFOLIO) - np.array(BENCHMARK)
        assert payload["observations"] == 400
        assert payload["periods_per_year"] == 252
        assert payload["annualized_active_return"] == pytest.approx(active.mean() * 252)
        assert payload["tracking_error"] == pytest.approx(active.std(ddof=1) * np.sqrt(252))
        assert payload["information_ratio"] == pytest.approx(active.mean() / active.std(ddof=1) * np.sqrt(252))
        assert payload["beta"] == pytest.approx(np.polyfit(BENCHMARK, PORTFOLIO, 1)[0])
        assert payload["correlation"] == pytest.approx(np.corrcoef(BENCHMARK, PORTFOLIO)[0, 1])

    def test_a_portfolio_that_is_the_benchmark(self):
        payload = tools.compare_with_benchmark(BENCHMARK, BENCHMARK)

        assert payload["tracking_error"] == 0
        assert payload["information_ratio"] is None
        assert payload["beta"] == pytest.approx(1)

    def test_a_constant_benchmark_has_no_beta(self):
        payload = tools.compare_with_benchmark(RETURNS[:50], [0.001] * 50)

        assert payload["beta"] is None and payload["correlation"] is None

    def test_length_mismatch_and_minimum_size(self):
        with pytest.raises(ToolError, match="benchmark_returns has 2"):
            tools.compare_with_benchmark([0.01, 0.02, 0.03], [0.01, 0.02])
        with pytest.raises(ToolError, match="three"):
            tools.compare_with_benchmark([0.01, 0.02], [0.01, 0.02])

    def test_dates_set_the_annualization(self):
        weekly = [d.date() for d in pd.date_range("2022-01-02", periods=60, freq="W")]

        payload = tools.compare_with_benchmark(PORTFOLIO[:60], BENCHMARK[:60], dates=weekly)

        assert payload["periods_per_year"] == 52


class TestAssetRiskSummary:
    @staticmethod
    def _call(frame, monkeypatch, **kwargs):
        dataset = MagicMock()
        dataset.get_data.return_value = frame
        monkeypatch.setattr(tools, "Dataset", MagicMock(return_value=dataset))
        arguments = {
            "dataset_name": "PRICES",
            "bbid": "AAPL UW",
            "start_date": dt.date(2024, 1, 2),
            "end_date": dt.date(2024, 6, 28),
            **kwargs,
        }
        return tools.asset_risk_summary(user_session=MagicMock(), **arguments)

    @staticmethod
    def _frame(prices, column="closePrice"):
        index = pd.DatetimeIndex(pd.bdate_range("2024-01-02", periods=len(prices)), name="date")
        return pd.DataFrame({column: prices}, index=index)

    def test_returns_are_computed_from_prices(self, monkeypatch):
        prices = list(100 * np.cumprod(1 + np.array(RETURNS[:80])))

        payload = self._call(self._frame(prices), monkeypatch)

        expected = risk_summary(pd.Series(prices).pct_change().dropna(), annualization_factor=252)
        assert payload["summary"]["var_historical"] == pytest.approx(expected.var_historical)
        assert payload["summary"]["observations"] == 79
        assert payload["period"] == {
            "start": "2024-01-03",
            "end": str(pd.bdate_range("2024-01-02", periods=80)[-1].date()),
        }

    def test_custom_value_column(self, monkeypatch):
        prices = list(100 * np.cumprod(1 + np.array(RETURNS[:30])))

        payload = self._call(self._frame(prices, column="level"), monkeypatch, value_column="level")

        assert payload["asset"]["column"] == "level"

    def test_missing_values_are_skipped_and_dates_sorted(self, monkeypatch):
        frame = self._frame(list(100 * np.cumprod(1 + np.array(RETURNS[:30]))))
        frame.iloc[5, 0] = np.nan

        payload = self._call(frame.iloc[::-1], monkeypatch)

        assert payload["summary"]["observations"] == 28

    @pytest.mark.parametrize(
        "frame, message",
        [
            (None, "No data returned"),
            (pd.DataFrame(), "No data returned"),
            (pd.DataFrame({"other": [1.0, 2.0, 3.0]}), "not found"),
            (pd.DataFrame({"closePrice": [1.0, -2.0, 3.0]}), "non-positive"),
        ],
    )
    def test_bad_data_is_reported(self, monkeypatch, frame, message):
        with pytest.raises(ToolError, match=message):
            self._call(frame, monkeypatch)

    def test_duplicate_dates_are_rejected(self, monkeypatch):
        frame = pd.DataFrame(
            {"closePrice": [1.0, 1.1, 1.2]},
            index=pd.DatetimeIndex(["2024-01-02", "2024-01-02", "2024-01-03"]),
        )

        with pytest.raises(ToolError, match="several rows per date"):
            self._call(frame, monkeypatch)
