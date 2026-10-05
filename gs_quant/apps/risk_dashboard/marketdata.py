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

import contextvars
import datetime as dt
import io
import json
import logging
import re
import threading
import time
from typing import Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
import numpy as np
import pandas as pd
from cachetools import TTLCache

from . import analysis
from .settings import PROVIDERS

logger = logging.getLogger('gs_quant.apps.risk_dashboard')

SYMBOL = re.compile(r'^[A-Za-z0-9^][A-Za-z0-9.^_=-]{0,19}$')
MAX_SYMBOLS = 11  # ten assets and a benchmark
MAX_RESPONSE_BYTES = 5_000_000
TIMEOUT_SECONDS = 10.0
RETRY_STATUSES = (429, 500, 502, 503, 504)
RETRY_DELAY_SECONDS = 1.5
CACHE_SECONDS = 900
STALE_CACHE_SECONDS = 60  # a provider that is down is not asked again at every request
MIN_PRICES = 61  # sixty returns, the least the analysis accepts
USER_AGENT = 'Mozilla/5.0 (compatible; gs-quant-risk)'


class MarketDataError(Exception):
    """A problem fetching prices, with a message that is safe to show and the HTTP status to answer with"""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _fetch(client: httpx.Client, provider: str, url: str, params: Optional[dict] = None) -> str:
    """The body of a GET, refusing redirects and anything larger than MAX_RESPONSE_BYTES

    A throttled or briefly failing provider (429, 5xx) is asked once more after a short pause.
    """
    for attempt in (1, 2):
        try:
            return _get_once(client, provider, url, params)
        except _Retryable as e:
            if attempt == 2:
                message = (
                    f'{provider} is limiting requests: try again in a minute'
                    if e.status == 429
                    else f'{provider} answered with status {e.status}'
                )
                raise MarketDataError(message, 502) from e
            time.sleep(RETRY_DELAY_SECONDS)
    raise AssertionError('unreachable')


class _Retryable(Exception):
    def __init__(self, status: int):
        super().__init__(status)
        self.status = status


def _get_once(client: httpx.Client, provider: str, url: str, params: Optional[dict]) -> str:
    try:
        with client.stream(
            'GET', url, params=params, headers={'User-Agent': USER_AGENT}, timeout=TIMEOUT_SECONDS
        ) as response:
            if response.status_code == 404:
                raise MarketDataError(f'{provider} does not know this symbol')
            if response.status_code in RETRY_STATUSES:
                raise _Retryable(response.status_code)
            if response.status_code != 200:
                raise MarketDataError(f'{provider} answered with status {response.status_code}', 502)
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise MarketDataError(f'{provider} sent more data than expected', 502)
                chunks.append(chunk)
    except httpx.TimeoutException as e:
        raise MarketDataError(f'{provider} did not answer in time', 502) from e
    except httpx.HTTPError as e:
        raise MarketDataError(f'Could not reach {provider}', 502) from e
    return b''.join(chunks).decode('utf-8', errors='replace')


def _clean_prices(dates, values, provider: str) -> pd.Series:
    # plain arrays: a pandas Series of values would be aligned to the dates by label instead of by position
    numbers = pd.to_numeric(pd.Series(list(values)), errors='coerce').to_numpy(dtype=float)
    series = pd.Series(numbers, index=pd.DatetimeIndex(dates))
    series = series[np.isfinite(series) & (series > 0)]
    series = series[~series.index.duplicated(keep='last')].sort_index()
    if series.empty:
        raise MarketDataError(f'{provider} has no prices for this symbol')
    return series


def fetch_stooq(client: httpx.Client, symbol: str) -> pd.Series:
    """Daily closes from Stooq's CSV download. Not adjusted for dividends."""
    text = _fetch(client, 'Stooq', 'https://stooq.com/q/d/l/', {'s': symbol.lower(), 'i': 'd'})
    head = text.strip()[:200].lower()
    if not head or head.startswith('no data'):
        raise MarketDataError('Stooq has no prices for this symbol')
    if 'apikey' in head or not head.startswith('date'):
        raise MarketDataError('Stooq did not answer with prices (it may now ask for an API key)', 502)
    try:
        frame = pd.read_csv(io.StringIO(text))
        return _clean_prices(pd.to_datetime(frame['Date']), frame['Close'], 'Stooq')
    except (KeyError, ValueError, pd.errors.ParserError) as e:
        raise MarketDataError('Stooq answered in a format that was not understood', 502) from e


def fetch_yahoo(client: httpx.Client, symbol: str) -> pd.Series:
    """Daily adjusted closes from Yahoo Finance's chart endpoint (unofficial, may change without notice)"""
    url = f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(symbol, safe="")}'
    text = _fetch(client, 'Yahoo Finance', url, {'range': '10y', 'interval': '1d', 'events': 'div,splits'})
    try:
        chart = json.loads(text)['chart']
    except (ValueError, KeyError, TypeError) as e:
        raise MarketDataError('Yahoo Finance answered in a format that was not understood', 502) from e
    if chart.get('error'):
        raise MarketDataError('Yahoo Finance does not know this symbol')
    try:
        result = chart['result'][0]
        stamps = result['timestamp']
        indicators = result['indicators']
        values = (indicators.get('adjclose') or [{}])[0].get('adjclose') or indicators['quote'][0]['close']
        try:
            zone = ZoneInfo(result['meta']['exchangeTimezoneName'])
        except (KeyError, ValueError, TypeError):
            zone = dt.timezone.utc
        # a bar is stamped with the exchange's opening time: take its date in the exchange's own time zone
        dates = [pd.Timestamp(dt.datetime.fromtimestamp(t, zone).date()) for t in stamps]
        series = _clean_prices(dates, values, 'Yahoo Finance')
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise MarketDataError('Yahoo Finance answered in a format that was not understood', 502) from e
    currency = result['meta'].get('currency') if isinstance(result.get('meta'), dict) else None
    series.attrs['currency'] = currency if isinstance(currency, str) and currency else None
    return series


FETCHERS = {'stooq': fetch_stooq, 'yahoo': fetch_yahoo}
LABELS = {'stooq': 'Stooq', 'yahoo': 'Yahoo Finance'}


def parse_symbols(text: str) -> list[str]:
    symbols = [s.strip() for s in text.split(',') if s.strip()]
    if not 1 <= len(symbols) <= MAX_SYMBOLS:
        raise MarketDataError(f'Give between 1 and {MAX_SYMBOLS} symbols, separated by commas')
    for symbol in symbols:
        if not SYMBOL.match(symbol):
            raise MarketDataError(f'"{symbol[:20]}" is not a valid symbol (letters, digits and . ^ _ = - only)')
    if len({s.upper() for s in symbols}) != len(symbols):
        raise MarketDataError('Each symbol can be given once')
    return symbols


CURRENCY = re.compile(r'^[A-Za-z]{3}$')
# prices quoted in a minor unit: the currency they belong to and the factor that turns them into that currency
MINOR_UNITS = {
    'GBp': ('GBP', 0.01),
    'GBX': ('GBP', 0.01),
    'ZAc': ('ZAR', 0.01),
    'ZAC': ('ZAR', 0.01),
    'ILA': ('ILS', 0.01),
}
FX_FILL_DAYS = 5  # an exchange rate is carried over holidays, but not over a longer gap


def parse_currency(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    if not CURRENCY.match(text.strip()):
        raise MarketDataError(f'"{text[:10]}" is not a currency code such as USD or TRY')
    return text.strip().upper()


def _unit(currency: str) -> tuple[str, float]:
    """The currency of a quote and the factor that converts it to major units (pence to pounds)"""
    return MINOR_UNITS.get(currency, (currency.upper(), 1.0))


# the symbols whose prices came from a saved copy, in the call of MarketData.prices that is running
_stale: contextvars.ContextVar = contextvars.ContextVar('stale_prices', default=None)


class MarketData:
    """Daily prices from one provider, cached for a few minutes so a page reload does not become a new request

    With an archive (anything with save_prices(provider, symbol, series) and load_prices(provider, symbol)), the latest
    prices of each symbol are also kept, and when the provider cannot be reached (not when it does not know the symbol)
    the saved copy is used instead and said so, with its date.
    """

    def __init__(self, provider: str, client: Optional[httpx.Client] = None, archive=None):
        if provider not in FETCHERS:
            raise ValueError(f'Unknown market data provider {provider!r}, choose from {PROVIDERS}')
        self.provider = provider
        self.label = LABELS[provider]
        self._client = client or httpx.Client(follow_redirects=False)
        self._archive = archive
        self._cache: TTLCache = TTLCache(maxsize=64, ttl=CACHE_SECONDS)
        self._stale_cache: TTLCache = TTLCache(maxsize=64, ttl=STALE_CACHE_SECONDS)
        self._lock = threading.Lock()

    def _series(self, symbol: str) -> pd.Series:
        key = symbol.upper()
        with self._lock:
            if key in self._cache:
                return self._cache[key]
            stale = self._stale_cache.get(key)
        if stale is not None:
            self._note_stale(key, stale.attrs['fetched_at'])
            return stale
        try:
            series = FETCHERS[self.provider](self._client, symbol)
        except MarketDataError as e:
            if e.status != 502 or self._archive is None:  # an unknown symbol is not a reason to show old prices
                raise
            saved = self._saved(key)
            if saved is None:
                raise
            logger.warning(
                '%s: using the saved prices of %s from %s (%s)', self.label, key, saved.attrs['fetched_at'], e
            )
            with self._lock:
                self._stale_cache[key] = saved
            self._note_stale(key, saved.attrs['fetched_at'])
            return saved
        with self._lock:
            self._cache[key] = series
        self._save(key, series)
        return series

    @staticmethod
    def _note_stale(symbol: str, fetched_at: str) -> None:
        found = _stale.get()
        if found is not None:
            found[symbol] = fetched_at

    def _save(self, key: str, series: pd.Series) -> None:
        if self._archive is None:
            return
        payload = {
            'currency': series.attrs.get('currency'),
            'dates': [str(d.date()) for d in series.index],
            'values': [float(v) for v in series],
        }
        try:
            self._archive.save_prices(self.provider, key, payload)
        except Exception as e:  # the copy is a convenience: failing to keep it must not fail the request
            logger.warning('Could not save the prices of %s: %s', key, e)

    def _saved(self, key: str) -> Optional[pd.Series]:
        try:
            found = self._archive.load_prices(self.provider, key)
        except Exception as e:
            logger.warning('Could not read the saved prices of %s: %s', key, e)
            return None
        if found is None:
            return None
        payload, fetched_at = found
        series = pd.Series(payload['values'], index=pd.DatetimeIndex(pd.to_datetime(payload['dates'])), dtype=float)
        if payload.get('currency'):
            series.attrs['currency'] = payload['currency']
        series.attrs['fetched_at'] = fetched_at
        return series

    def _rate(self, currency: str, base: str) -> tuple[pd.Series, str]:
        """The price of one unit of the currency in the base currency, and the Yahoo symbol it came from"""
        direct = f'{currency}{base}=X'
        try:
            return self._series(direct), direct
        except MarketDataError as e:
            if e.status != 422:
                raise
        inverse = f'{base}{currency}=X'
        try:
            return 1 / self._series(inverse), inverse
        except MarketDataError as e:
            if e.status != 422:
                raise
        raise MarketDataError(f'No exchange rate between {currency} and {base} is available') from None

    def _convert(self, series: pd.Series, base: str) -> tuple[pd.Series, Optional[dict]]:
        """The prices in the base currency; unchanged, and None, if they are already in it or their currency is unknown"""
        quoted = series.attrs.get('currency')
        if not quoted:
            return series, None
        currency, factor = _unit(quoted)
        if currency == base and factor == 1.0:
            return series, None
        if currency == base:
            return series * factor, {'from': quoted, 'rate': None}
        rate, symbol = self._rate(currency, base)
        dates = series.index
        aligned = rate.reindex(rate.index.union(dates)).ffill(limit=FX_FILL_DAYS).reindex(dates)
        converted = (series * factor * aligned).dropna()
        if converted.empty:
            raise MarketDataError(f'The {currency}/{base} exchange rate does not cover the dates of these prices')
        return converted, {'from': quoted, 'rate': symbol}

    def prices(
        self,
        symbols: list[str],
        start: Optional[dt.date] = None,
        end: Optional[dt.date] = None,
        base: Optional[str] = None,
    ) -> dict:
        """Closing prices of the symbols on the dates all of them traded, the latest MAX_OBSERVATIONS of them

        Symbols quoted in different currencies are converted into one, because the returns of a portfolio must be in a
        single currency: the base currency if one is given, else the currency of the first symbol. A single symbol is
        converted only if a base is given. Conversion needs the currency of each quote, which only Yahoo Finance gives.
        """
        base = parse_currency(base)
        found: dict = {}
        token = _stale.set(found)
        try:
            return self._prices(symbols, start, end, base, found)
        finally:
            _stale.reset(token)

    def _prices(self, symbols: list[str], start, end, base, found: dict) -> dict:
        series = {s.upper(): self._series(s) for s in symbols}
        currencies = {name: _unit(c)[0] if (c := ser.attrs.get('currency')) else None for name, ser in series.items()}
        notes: list[str] = []
        if base is None and len({c for c in currencies.values() if c}) > 1:
            base = next(c for c in currencies.values() if c)
            notes.append(f'The assets are quoted in different currencies, so prices were converted to {base}')
        converted: dict[str, dict] = {}
        if base is not None:
            if self.provider != 'yahoo':
                raise MarketDataError(f'Converting to another currency needs Yahoo Finance, not {self.label}')
            for name in series:
                series[name], how = self._convert(series[name], base)
                if how:
                    converted[name] = how
        frame = pd.concat(series, axis=1, join='inner')
        if start is not None:
            frame = frame[frame.index >= pd.Timestamp(start)]
        if end is not None:
            frame = frame[frame.index <= pd.Timestamp(end)]
        frame = frame.iloc[-(analysis.MAX_OBSERVATIONS + 1) :]
        if len(frame) < MIN_PRICES:
            raise MarketDataError(
                f'Only {len(frame)} dates have prices for all of {", ".join(frame.columns)}; at least {MIN_PRICES} are needed'
            )
        if converted:
            rates = sorted({how['rate'] for how in converted.values() if how['rate']})
            notes.append(
                f'Prices are in {base}' + (f', converted at the daily rate of {", ".join(rates)}' if rates else '')
            )
        if found:
            newest = max(found.values())[:10]
            notes.append(
                f'Prices of {", ".join(sorted(found))} come from the copy saved on {newest} because {self.label} '
                'could not be reached: they may be out of date'
            )
        return {
            'source': self.label,
            'symbols': list(frame.columns),
            'dates': [str(d.date()) for d in frame.index],
            'prices': {s: [round(float(v), 6) for v in frame[s]] for s in frame.columns},
            'currencies': {name: currencies[name] for name in frame.columns},
            'base': base,
            'converted': converted,
            'notes': notes,
            'stale': {name: when[:10] for name, when in sorted(found.items())},
        }


def make_market_data(
    provider: Optional[str], client: Optional[httpx.Client] = None, archive=None
) -> Optional[MarketData]:
    return MarketData(provider, client, archive) if provider else None


DEFAULT_CHECK_SYMBOLS = {'stooq': 'aapl.us', 'yahoo': 'AAPL'}


def check(provider: str, symbol: Optional[str] = None, client: Optional[httpx.Client] = None) -> dict:
    """Fetches one symbol from the real provider and reports what came back, for diagnosing a deployment

    Never raises: the answer says whether the provider could be reached and read, and if not, why.
    """
    symbol = symbol or DEFAULT_CHECK_SYMBOLS[provider]
    report = {'provider': LABELS[provider], 'symbol': symbol, 'ok': False}
    try:
        parse_symbols(symbol)
        series = FETCHERS[provider](client or httpx.Client(follow_redirects=False), symbol)
    except MarketDataError as e:
        return {**report, 'error': str(e)}
    except Exception as e:  # a bug or an unforeseen answer: report it rather than crash a diagnostic
        return {**report, 'error': f'Unexpected {type(e).__name__}: {e}'}
    return {
        **report,
        'ok': True,
        'observations': len(series),
        'first': str(series.index[0].date()),
        'last': str(series.index[-1].date()),
        'last_close': round(float(series.iloc[-1]), 4),
        'enough_for_analysis': len(series) >= MIN_PRICES,
    }
