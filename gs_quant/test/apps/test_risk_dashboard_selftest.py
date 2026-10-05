"""
Copyright 2026 Senanurcetin.
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

import numpy as np
import pytest

pytest.importorskip('starlette')
pytest.importorskip('pydantic')

import gs_quant.apps.risk_dashboard.__main__ as cli  # noqa: E402
from gs_quant.apps.risk_dashboard import marketdata, selftest  # noqa: E402
from gs_quant.test.apps.test_risk_dashboard_marketdata import DATES, fx_service, prices_for  # noqa: E402


def quotes(**changes):
    base = {
        'THYAO.IS': ('TRY', prices_for(1), DATES),
        'GARAN.IS': ('TRY', prices_for(2), DATES),
        'AAPL': ('USD', prices_for(3), DATES),
        'XU100.IS': ('TRY', prices_for(4), DATES),
        'USDTRY=X': ('TRY', 30 + np.arange(len(DATES)) * 0.05, DATES),
    }
    base.update(changes)
    return base


def run(market, **arguments):
    lines: list[str] = []
    code = selftest.run(market, out=lines.append, years=None, **arguments)
    return code, '\n'.join(lines)


class TestSelfTest:
    def test_a_whole_pass_over_mixed_currencies_with_a_benchmark(self):
        code, text = run(fx_service(quotes()))

        assert code == 0, text
        assert 'OK    prices: 120 dates in common' in text
        assert 'AAPL: quoted in USD, converted to TRY with USDTRY=X' in text
        assert 'THYAO.IS: quoted in TRY\n' in text  # already in the currency asked for: nothing converted
        assert 'OK    analysis (3 assets at equal weights' in text and 'Basel zone' in text
        assert 'OK    benchmark XU100.IS: beta' in text
        # the history is short and the benchmark here is a random series that does not move with the portfolio
        assert text.rstrip().endswith('DONE: 0 failed, 2 warnings')
        assert 'WARN  only 120 dates' in text and 'almost uncorrelated with XU100.IS' in text

    def test_the_benchmark_is_not_one_of_the_assets(self):
        _, text = run(fx_service(quotes()))

        assert '3 assets' in text and 'XU100.IS: volatility' not in text

    def test_a_benchmark_that_is_also_an_asset_stays_an_asset(self):
        code, text = run(fx_service(quotes()), symbols=('THYAO.IS', 'GARAN.IS'), benchmark='THYAO.IS', base=None)

        assert code == 0, text
        assert '2 assets' in text and 'OK    benchmark THYAO.IS' in text

    def test_no_benchmark_skips_that_step(self):
        code, text = run(fx_service(quotes()), benchmark=None)

        assert code == 0 and 'benchmark XU100.IS' not in text.split('Symbols')[1].split('\n', 1)[1]

    def test_a_symbol_the_provider_does_not_know_fails_the_first_step(self):
        market = fx_service({k: v for k, v in quotes().items() if k != 'GARAN.IS'})

        code, text = run(market)

        assert code == 1 and text.splitlines()[-1].startswith('FAIL  prices:') and 'GARAN.IS' in text

    def test_a_missed_split_is_a_warning_not_a_failure(self):
        prices = prices_for(1).copy()
        prices[60:] = prices[60:] / 5  # an unadjusted 5-for-1 split

        code, text = run(fx_service(quotes(**{'THYAO.IS': ('TRY', prices, DATES)})))

        assert code == 0
        assert 'WARN  THYAO.IS: a move of -80.0%' in text and 'missed split' in text

    def test_a_series_that_never_changes_fails(self):
        code, text = run(fx_service(quotes(**{'GARAN.IS': ('TRY', np.full(len(DATES), 50.0), DATES)})))

        assert code == 1 and 'FAIL  data: GARAN.IS never changes' in text

    def test_a_short_history_is_a_warning(self):
        assert 'WARN  only 120 dates in common' in run(fx_service(quotes()))[1]


class TestCommand:
    def test_the_command_is_known_to_the_parser_and_passes_its_arguments(self, monkeypatch):
        seen = {}

        def fake(symbols, benchmark, base, years, provider):
            seen.update(symbols=symbols, benchmark=benchmark, base=base, years=years, provider=provider)
            return 0

        monkeypatch.setattr(cli, 'check_portfolio', fake)

        assert (
            cli.main(['check-portfolio', '--symbols', 'A,B', '--benchmark', 'none', '--base', 'auto', '--years', '0'])
            == 0
        )
        assert seen == {'symbols': 'A,B', 'benchmark': 'none', 'base': 'auto', 'years': 0, 'provider': 'yahoo'}

    def test_none_and_auto_mean_no_benchmark_and_no_currency(self, monkeypatch):
        captured = {}
        monkeypatch.setattr(marketdata, 'make_market_data', lambda provider: object())
        monkeypatch.setattr(
            selftest, 'run', lambda market, names, benchmark, base, years: captured.update(locals()) or 0
        )

        assert cli.check_portfolio('A, B', 'none', 'auto', 0, None) == 0
        assert captured['names'] == ('A', 'B') and captured['benchmark'] is None
        assert captured['base'] is None and captured['years'] is None
