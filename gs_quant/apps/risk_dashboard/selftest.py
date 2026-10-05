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

import datetime as dt
from typing import Callable, Optional

import numpy as np

from . import analysis, marketdata
from .app import PortfolioRequest, execute

DEFAULT_SYMBOLS = ('THYAO.IS', 'GARAN.IS', 'AAPL')
DEFAULT_BENCHMARK = 'XU100.IS'
DEFAULT_BASE = 'TRY'
DEFAULT_YEARS = 3
JUMP = 0.25  # a one-day move beyond this in an adjusted close is worth a look: a missed split, a bad quote


def _pct(value: Optional[float], digits: int = 2) -> str:
    return 'n/a' if value is None else f'{value * 100:.{digits}f}%'


def _num(value: Optional[float], digits: int = 2) -> str:
    return 'n/a' if value is None else f'{value:.{digits}f}'


def run(
    market: marketdata.MarketData,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    benchmark: Optional[str] = DEFAULT_BENCHMARK,
    base: Optional[str] = DEFAULT_BASE,
    years: Optional[int] = DEFAULT_YEARS,
    out: Callable[[str], None] = print,
) -> int:
    """Everything the application does with live data, in one pass, and what came out of each step

    Meant to be run on the machine that will serve the application, with real internet access, and its output shared: it
    says what to look at. Returns 0 if every step worked, 1 if one failed. Warnings do not fail it.
    """
    failures: list[str] = []
    warnings: list[str] = []

    def fail(step: str, message: str) -> int:
        failures.append(step)
        out(f'FAIL  {step}: {message}')
        return 1

    fetched = list(symbols) + (
        [benchmark] if benchmark and benchmark.upper() not in {s.upper() for s in symbols} else []
    )
    start = None
    if years:
        today = dt.date.today()
        start = today.replace(year=today.year - years, day=min(today.day, 28))
    out(
        f'Symbols {", ".join(symbols)}; benchmark {benchmark or "none"}; currency {base or "automatic"}; '
        f'{years or "all"} years; provider {market.label}'
    )

    # 1. prices, with the currency conversion
    try:
        data = market.prices(fetched, start, None, base)
    except marketdata.MarketDataError as e:
        return fail('prices', str(e))
    out(f'OK    prices: {len(data["dates"])} dates in common, {data["dates"][0]} to {data["dates"][-1]}')
    for name in data['symbols']:
        how = data['converted'].get(name)
        currency = data['currencies'].get(name) or 'unknown'
        detail = f'quoted in {currency}'
        if how:
            detail += f', converted to {data["base"]}' + (f' with {how["rate"]}' if how.get('rate') else '')
        out(f'      {name}: {detail}')
    for note in data['notes']:
        out(f'      note: {note}')
    if len(data['dates']) < 250:
        warnings.append(f'only {len(data["dates"])} dates in common: a short history makes every estimate noisy')

    # 2. does the data look like prices
    for name in data['symbols']:
        values = np.asarray(data['prices'][name], dtype=float)
        moves = np.diff(values) / values[:-1]
        worst = int(np.argmax(np.abs(moves)))
        if np.abs(moves[worst]) > JUMP:
            warnings.append(
                f'{name}: a move of {_pct(float(moves[worst]), 1)} on {data["dates"][worst + 1]} (a missed split or a bad quote?)'
            )
        if np.ptp(values) == 0:
            return fail('data', f'{name} never changes')
    out('OK    data: prices are positive, vary and have no gaps')

    # 3. the analysis itself, as the page would ask for it
    held = [
        s
        for s in data['symbols']
        if not (benchmark and s == benchmark.upper() and s not in {x.upper() for x in symbols})
    ]
    assets = {s: data['prices'][s] for s in held}
    returns = len(data['dates']) - 1
    window = max(30, min(250, returns // 2))
    request = {
        'assets': assets,
        'kind': 'prices',
        'dates': data['dates'],
        'window': window,
        'horizon': 10,
        'confidence': 0.95,
    }
    if benchmark:
        request['benchmark'] = data['prices'][benchmark.upper()]
        request['benchmark_name'] = benchmark.upper()
    try:
        result = execute('portfolio', PortfolioRequest.model_validate(request))
    except analysis.AnalysisError as e:
        return fail('analysis', str(e))
    except ValueError as e:
        return fail('analysis', f'the request was refused: {e}')
    risk = analysis.headline(result)
    out(
        f'OK    analysis ({len(held)} assets at equal weights, window {window}): volatility {_pct(risk["volatility"])}, '
        f'95% VaR {_pct(risk["var"])}, expected shortfall {_pct(risk["expected_shortfall"])}, '
        f'10-period VaR {_pct(result["horizon"]["var"])}, Basel zone {risk["zone"]}'
    )
    ewma = result['ewma']
    out(
        f'      filtered volatility {_pct(ewma["volatility"])} against {_pct(ewma["window_volatility"])} over the window'
    )
    for asset in result['portfolio']['assets']:
        out(
            f'      {asset["name"]}: volatility {_pct(asset["volatility"])}, share of volatility '
            f'{_pct(asset["volatility_contribution"], 1)}'
        )
    if result.get('benchmark'):
        b = result['benchmark']
        out(
            f'OK    benchmark {b["name"]}: beta {_num(b["beta"])}, correlation {_num(b["correlation"])}, '
            f'tracking error {_pct(b["tracking_error"], 1)}, information ratio {_num(b["information_ratio"])}, '
            f'{b["observations"]} periods'
        )
        if abs(b['correlation'] or 0) < 0.1:
            warnings.append(
                f'the portfolio is almost uncorrelated with {b["name"]}: check that it is the right benchmark'
            )
    if result['backtest']['reject']:
        warnings.append(
            'the Kupiec test rejects the 95% VaR over this history (not a fault: the model may not suit it)'
        )

    for text in warnings:
        out(f'WARN  {text}')
    out(f'{"FAILED" if failures else "DONE"}: {len(failures)} failed, {len(warnings)} warnings')
    return 1 if failures else 0
