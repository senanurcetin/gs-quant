"""Independent offline QA for five date-default API modules in draft PR #400.

Run on the contributor's #400 head, not on upstream master:
    python -m pytest -q gs_quant/test/test_lazy_defaults_five_api_qa.py

No network or credentials are required. Each assertion observes the arguments
delivered to a mocked API or downstream method.
"""

import datetime as dt
import inspect
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from freezegun import freeze_time

from gs_quant.backtests.strategy_systematic import StrategySystematic
from gs_quant.entities.entity import EntityType
from gs_quant.lazy_defaults import LazyDefault
from gs_quant.markets.baskets import Basket, GsAssetApi
from gs_quant.markets.index import Index
from gs_quant.markets.report import GsPortfolioApi, PerformanceReport
from gs_quant.markets.securities import Asset


CASES = (
    "strategy_systematic",
    "baskets",
    "index",
    "securities",
    "report",
)
_NOT_PROVIDED = object()


def _record_downstream_end(case, supplied_end=_NOT_PROVIDED):
    """Run the real lazy-default wrapper; capture end at the downstream boundary."""
    kwargs = {} if supplied_end is _NOT_PROVIDED else {"end": supplied_end}

    if case == "strategy_systematic":
        fake = SimpleNamespace()
        fake._StrategySystematic__use_xasset_backtesting_service = True
        runner = Mock(return_value=None)
        fake._StrategySystematic__run_service_based_backtest = runner
        StrategySystematic.backtest(fake, **kwargs)
        return runner.call_args.args[1]

    if case == "baskets":
        fake = SimpleNamespace(positioned_entity_type=EntityType.ASSET, id="TEST_BASKET")
        # Bypass only the separate @_validate guard: the underlying
        # @lazy_defaults wrapper and real production method still execute.
        with patch.object(GsAssetApi, "get_asset_positions_for_dates", return_value=[]) as api:
            Basket.get_position_sets.__wrapped__(fake, **kwargs)
        return api.call_args.args[2]

    if case == "index":
        downstream = Mock(return_value=[])
        fake = SimpleNamespace(get_position_sets=downstream)
        Index.get_constituents(fake, **kwargs)
        return downstream.call_args.args[1]

    if case == "securities":
        downstream = Mock(return_value=None)
        fake = SimpleNamespace(get_data_series=downstream)
        Asset.get_close_prices(fake, **kwargs)
        return downstream.call_args.args[4]

    if case == "report":
        fake = SimpleNamespace(id="TEST_REPORT", position_source_id="TEST_SOURCE")
        with patch.object(GsPortfolioApi, "get_positions_data", return_value=[]) as api:
            PerformanceReport.get_positions_data(fake, **kwargs)
        return api.call_args.args[2]

    raise AssertionError(f"Unknown case: {case}")


@pytest.mark.parametrize("case", CASES)
def test_default_end_tracks_wall_clock_across_calls(case):
    """Date defaults must never freeze at module-import time."""
    with freeze_time("2031-03-04 23:59:00"):
        first = _record_downstream_end(case)
    with freeze_time("2031-03-05 00:01:00"):
        second = _record_downstream_end(case)

    offset = dt.timedelta(days=1) if case == "strategy_systematic" else dt.timedelta()
    assert first == dt.date(2031, 3, 4) - offset
    assert second == dt.date(2031, 3, 5) - offset


@pytest.mark.parametrize("case", CASES)
@pytest.mark.parametrize("explicit", [dt.date(2024, 6, 15), None])
def test_explicit_end_is_never_overwritten(case, explicit):
    """Even an explicit None must be forwarded without clock substitution."""
    with freeze_time("2035-12-31"):
        result = _record_downstream_end(case, supplied_end=explicit)
    assert result is explicit


@pytest.mark.parametrize(
    ("case", "method"),
    (
        ("strategy_systematic", StrategySystematic.backtest),
        ("baskets", Basket.get_position_sets),
        ("index", Index.get_constituents),
        ("securities", Asset.get_close_prices),
        ("report", PerformanceReport.get_positions_data),
    ),
)
def test_public_signature_advertises_lazy_end(case, method):
    """The wrapped method retains a readable public call signature."""
    signature = inspect.signature(method)
    assert "end" in signature.parameters, case
    assert isinstance(signature.parameters["end"].default, LazyDefault)
