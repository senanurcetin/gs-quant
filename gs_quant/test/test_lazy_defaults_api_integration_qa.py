"""Offline integration-boundary QA for GS Quant draft PR #400.

These tests execute the real decorated API methods, but mock remote
transports. No GS credentials or outbound network connections are used.
"""
import datetime as dt
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pandas as pd
import pytest
from freezegun import freeze_time

import gs_quant.backtests.strategy_systematic as strategy_module
from gs_quant.backtests.strategy_systematic import StrategySystematic
from gs_quant.markets.baskets import Basket
from gs_quant.markets.index import Index
from gs_quant.markets.securities import Asset, SecMasterAsset, Stock
from gs_quant.markets import baskets as basket_module
from gs_quant.markets import index as index_module
from gs_quant.markets import securities as securities_module

_CASES = (
    "basket_corporate_actions",
    "basket_fundamentals",
    "index_fundamentals",
    "index_close_prices",
    "index_close_price_for_date",
    "index_constituents_for_date",
    "index_constituent_instruments_for_date",
    "index_constituent_instruments",
    "secmaster_hloc",
    "stock_thematic_beta",
    "strategy_nonservice_sync",
    "strategy_nonservice_async",
)
_NOT_GIVEN = object()


def _downstream_date(case, explicit=_NOT_GIVEN):
    """Return the date sent past the decorated public API boundary."""
    parameter = "date" if case.endswith("_for_date") else "end"
    kwargs = {} if explicit is _NOT_GIVEN else {parameter: explicit}

    if case.startswith("basket_"):
        obj = SimpleNamespace(id="BASKET_1")
        method = (Basket.get_corporate_actions if case == "basket_corporate_actions"
                  else Basket.get_fundamentals)
        with (patch.object(basket_module, "DataQuery") as query,
              patch.object(basket_module.GsDataApi, "query_data", return_value=[])):
            # Strip only @_validate; keep the real @lazy_defaults decorator.
            method.__wrapped__(obj, **kwargs)
        return query.call_args.kwargs["end_date"]

    if case == "index_fundamentals":
        obj = SimpleNamespace(id="INDEX_1", _Index__is_sts_index=lambda: True)
        with (patch.object(index_module, "DataQuery") as query,
              patch.object(index_module.GsDataApi, "query_data", return_value=[])):
            Index.get_fundamentals(obj, **kwargs)
        return query.call_args.kwargs["end_date"]

    if case in {"index_close_prices", "index_close_price_for_date"}:
        obj = object.__new__(Index)
        parent_method = ("get_close_price_for_date" if case.endswith("_for_date")
                         else "get_close_prices")
        with patch.object(Asset, parent_method, return_value=pd.DataFrame()) as parent:
            getattr(Index, parent_method)(obj, **kwargs)
        return parent.call_args.args[-1]

    if case in {"index_constituents_for_date", "index_constituent_instruments_for_date"}:
        fake_positions = Mock()
        fake_positions.get_positions.return_value = pd.DataFrame()
        fake_positions.to_target.return_value.positions = []
        obj = SimpleNamespace(get_position_set_for_date=Mock(return_value=fake_positions))
        if case == "index_constituents_for_date":
            Index.get_constituents_for_date(obj, **kwargs)
        else:
            with patch.object(index_module.GsAssetApi, "get_instruments_for_positions", return_value=()):
                Index.get_constituent_instruments_for_date(obj, **kwargs)
        return obj.get_position_set_for_date.call_args.args[0]

    if case == "index_constituent_instruments":
        obj = SimpleNamespace(get_position_sets=Mock(return_value=[]))
        Index.get_constituent_instruments(obj, **kwargs)
        return obj.get_position_sets.call_args.args[1]

    if case == "secmaster_hloc":
        obj = object.__new__(SecMasterAsset)
        # Range validation is an independent algorithm; intercept its input.
        with patch.object(SecMasterAsset, "_SecMasterAsset__is_validate_range",
                          return_value=False) as validate:
            SecMasterAsset.get_hloc_prices(obj, **kwargs)
        return validate.call_args.kwargs["end"]

    if case == "stock_thematic_beta":
        obj = SimpleNamespace(get_identifier=Mock(return_value="GSID_1"))
        basket = {"BASKET_1": [{"id": "BASKET_ID_1", "type": "Custom Basket"}]}
        payload = [{"date": "2032-01-01", "gsid": "GSID_1",
                    "basketId": "BASKET_ID_1", "beta": 0.5}]
        with (patch.object(securities_module.GsAssetApi, "resolve_assets",
                           return_value=basket),
              patch.object(securities_module, "DataQuery") as query,
              patch.object(securities_module.GsDataApi, "query_data",
                           return_value=payload)):
            Stock.get_thematic_beta(obj, basket_identifier="BASKET_1", **kwargs)
        queried = query.call_args.kwargs["end_date"]
        assert obj.get_identifier.call_args.args[1] == queried
        return queried

    if case.startswith("strategy_nonservice_"):
        obj = SimpleNamespace(
            _StrategySystematic__use_xasset_backtesting_service=False,
            _StrategySystematic__backtest_parameters=SimpleNamespace(as_dict=lambda: {}),
            _StrategySystematic__backtest_type="Fake",
            _StrategySystematic__name="QA",
            _StrategySystematic__currency=None,
            _StrategySystematic__cost_netting=None,
            _StrategySystematic__cash_accrual=None,
        )
        fakes = SimpleNamespace(FakeBacktestParameters=SimpleNamespace(from_dict=lambda _: object()))
        with (patch.object(strategy_module, "backtests", fakes),
              patch.object(strategy_module, "Backtest") as backtest,
              patch.object(strategy_module.GsBacktestApi, "run_backtest"),
              patch.object(strategy_module.GsBacktestApi, "create_backtest",
                           return_value=SimpleNamespace(id="MOCK_BACKTEST")),
              patch.object(strategy_module.GsBacktestApi, "schedule_backtest")):
            StrategySystematic.backtest(obj, is_async=case.endswith("_async"), **kwargs)
        return backtest.call_args.kwargs["end_date"]

    raise AssertionError(case)


@pytest.mark.parametrize("case", _CASES)
def test_call_time_date_reaches_api_boundary(case):
    with freeze_time("2032-01-01 23:59:00"):
        first = _downstream_date(case)
    with freeze_time("2032-01-02 00:01:00"):
        second = _downstream_date(case)

    offset = (dt.timedelta(days=10) if case == "basket_corporate_actions"
              else -dt.timedelta(days=1) if case.startswith("strategy_nonservice_")
              else dt.timedelta())
    assert first == dt.date(2032, 1, 1) + offset, case
    assert second == dt.date(2032, 1, 2) + offset, case


@pytest.mark.parametrize("case", _CASES)
@pytest.mark.parametrize("explicit", [None, dt.date(2023, 7, 19)])
def test_explicit_api_date_stays_unchanged(case, explicit):
    with freeze_time("2033-08-09"):
        received = _downstream_date(case, explicit)
    assert received is explicit, case
