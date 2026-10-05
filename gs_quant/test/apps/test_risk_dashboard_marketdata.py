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

import httpx
import numpy as np
import pandas as pd
import pytest

pytest.importorskip('starlette')

from starlette.testclient import TestClient  # noqa: E402

from gs_quant.apps.risk_dashboard import marketdata  # noqa: E402
from gs_quant.apps.risk_dashboard.app import create_app  # noqa: E402
from gs_quant.apps.risk_dashboard.marketdata import MarketData, MarketDataError  # noqa: E402
from gs_quant.apps.risk_dashboard.settings import Settings  # noqa: E402

DATES = pd.bdate_range('2024-01-01', periods=120)


def prices_for(seed: int) -> np.ndarray:
    return 100 * np.cumprod(1 + np.random.default_rng(seed).normal(0.0004, 0.01, len(DATES)))


def stooq_csv(values, dates=DATES) -> str:
    rows = ['Date,Open,High,Low,Close,Volume']
    rows += [f'{d.date()},{v},{v},{v},{v},1000' for d, v in zip(dates, values)]
    return '\n'.join(rows) + '\n'


def yahoo_json(values, dates=DATES, zone='Europe/Istanbul', adjusted=True, error=None, currency=None) -> str:
    stamps = [int(pd.Timestamp(d, tz=zone).replace(hour=10).timestamp()) for d in dates]
    indicators = {'quote': [{'close': [None if v is None else v * 2 for v in values]}]}
    if adjusted:
        indicators['adjclose'] = [{'adjclose': list(values)}]
    meta = {'exchangeTimezoneName': zone, **({'currency': currency} if currency else {})}
    result = {'meta': meta, 'timestamp': stamps, 'indicators': indicators}
    return json.dumps({'chart': {'result': None if error else [result], 'error': error}})


def client_for(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def stooq_service(bodies: dict, calls=None, status=200) -> MarketData:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        symbol = request.url.params['s']
        return httpx.Response(status, text=bodies.get(symbol, 'No data'))

    return MarketData('stooq', client_for(handler))


# ----------------------------------------------------------------------------------------------------------------------
# Stooq
# ----------------------------------------------------------------------------------------------------------------------


class TestStooq:
    def test_reads_closes_and_asks_for_the_lower_case_symbol(self):
        calls = []
        service = stooq_service({'spy.us': stooq_csv(prices_for(1))}, calls)

        result = service.prices(['SPY.US'])

        assert result['source'] == 'Stooq' and result['symbols'] == ['SPY.US']
        assert result['dates'][0] == str(DATES[0].date()) and len(result['dates']) == len(DATES)
        assert result['prices']['SPY.US'] == pytest.approx(list(prices_for(1)), abs=1e-5)
        assert calls[0].url.host == 'stooq.com' and dict(calls[0].url.params) == {'s': 'spy.us', 'i': 'd'}

    @pytest.mark.parametrize(
        'body, message',
        [
            ('No data', 'no prices'),
            ('', 'no prices'),
            ('Get your apikey: https://stooq.com/q/d/?s=spy.us&get_apikey', 'API key'),
            ('<html>captcha</html>', 'API key'),
            ('Date,Open\n2024-01-01,1\n', 'not understood'),
            ('Date,Close\nnot-a-date,5\n', 'not understood'),
            ('Date,Close\n2024-01-01,0\n2024-01-02,-1\n2024-01-03,abc\n', 'no prices'),
        ],
    )
    def test_refuses_what_is_not_prices(self, body, message):
        with pytest.raises(MarketDataError, match=message):
            stooq_service({'x': body}).prices(['x'])

    def test_drops_unusable_rows_and_sorts_and_deduplicates(self):
        values = list(prices_for(2))
        rows = stooq_csv(values).splitlines()
        shuffled = [rows[0], *reversed(rows[1:]), rows[5], 'Date-less,junk']
        body = '\n'.join(s for s in shuffled if not s.startswith('Date-less')) + '\n2024-02-01,,,,0,0\n'

        result = stooq_service({'x': body}).prices(['x'])

        assert result['dates'] == sorted(set(result['dates']))
        assert len(result['dates']) == len(DATES)

    def test_upstream_errors_become_502_and_unknown_symbols_422(self):
        with pytest.raises(MarketDataError) as unavailable:
            stooq_service({}, status=403).prices(['x'])
        with pytest.raises(MarketDataError) as unknown:
            stooq_service({}, status=404).prices(['x'])

        assert unavailable.value.status == 502 and unknown.value.status == 422

    def test_network_failures_become_502(self):
        def refuse(request):
            raise httpx.ConnectError('boom')

        def slow(request):
            raise httpx.ReadTimeout('slow')

        with pytest.raises(MarketDataError, match='Could not reach') as refused:
            MarketData('stooq', client_for(refuse)).prices(['x'])
        with pytest.raises(MarketDataError, match='did not answer in time'):
            MarketData('stooq', client_for(slow)).prices(['x'])
        assert refused.value.status == 502

    def test_redirects_are_not_followed(self):
        def redirect(request):
            return httpx.Response(302, headers={'Location': 'http://169.254.169.254/'})

        with pytest.raises(MarketDataError, match='status 302'):
            MarketData('stooq', client_for(redirect)).prices(['x'])

    def test_oversized_responses_are_refused(self, monkeypatch):
        monkeypatch.setattr(marketdata, 'MAX_RESPONSE_BYTES', 1_000)

        with pytest.raises(MarketDataError, match='more data than expected'):
            stooq_service({'x': stooq_csv(prices_for(1))}).prices(['x'])


# ----------------------------------------------------------------------------------------------------------------------
# Yahoo Finance
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(marketdata.time, 'sleep', lambda seconds: None)


class TestRetries:
    def service(self, statuses: list, body: str, calls: list) -> MarketData:
        def handler(request):
            calls.append(request)
            status = statuses.pop(0) if statuses else 200
            return httpx.Response(status, text=body if status == 200 else '')

        return MarketData('yahoo', client_for(handler))

    def test_a_throttled_request_is_repeated_once(self):
        calls = []

        result = self.service([429], yahoo_json(prices_for(1)), calls).prices(['X'])

        assert len(calls) == 2 and len(result['dates']) == len(DATES)

    @pytest.mark.parametrize('status', [500, 502, 503, 504])
    def test_so_is_a_briefly_failing_one(self, status):
        calls = []

        self.service([status], yahoo_json(prices_for(1)), calls).prices(['X'])

        assert len(calls) == 2

    def test_a_second_429_says_to_wait(self):
        calls = []

        with pytest.raises(MarketDataError, match='limiting requests') as error:
            self.service([429, 429, 429], '', calls).prices(['X'])

        assert len(calls) == 2 and error.value.status == 502

    def test_a_second_server_error_is_reported_with_its_status(self):
        with pytest.raises(MarketDataError, match='status 503'):
            self.service([503, 503], '', []).prices(['X'])

    def test_other_errors_are_not_repeated(self):
        for status in (400, 401, 403):
            calls = []
            with pytest.raises(MarketDataError, match=f'status {status}'):
                self.service([status], '', calls).prices(['X'])
            assert len(calls) == 1


class TestYahoo:
    def service(self, body: str, calls=None, status=200) -> MarketData:
        def handler(request):
            if calls is not None:
                calls.append(request)
            return httpx.Response(status, text=body)

        return MarketData('yahoo', client_for(handler))

    def test_prefers_adjusted_closes_and_encodes_the_symbol_in_the_path(self):
        calls = []
        values = prices_for(3)

        result = self.service(yahoo_json(values), calls).prices(['^GSPC'])

        assert result['prices']['^GSPC'] == pytest.approx(list(values), abs=1e-5)
        assert calls[0].url.host == 'query1.finance.yahoo.com'
        assert calls[0].url.raw_path.startswith(b'/v8/finance/chart/%5EGSPC?')
        assert 'Mozilla' in calls[0].headers['user-agent']

    def test_falls_back_to_plain_closes(self):
        values = prices_for(4)

        result = self.service(yahoo_json(values, adjusted=False)).prices(['THYAO.IS'])

        assert result['prices']['THYAO.IS'] == pytest.approx([v * 2 for v in values], abs=1e-5)

    def test_dates_are_taken_in_the_exchange_time_zone(self):
        # 10:00 in Istanbul is 07:00 UTC; 09:00 in Tokyo is 00:00 UTC the same day, and 00:00 in Sydney the day before
        for zone in ('Europe/Istanbul', 'Asia/Tokyo', 'Australia/Sydney', 'America/New_York'):
            result = self.service(yahoo_json(prices_for(5), zone=zone)).prices(['X'])

            assert result['dates'] == [str(d.date()) for d in DATES], zone

    def test_missing_values_are_skipped(self):
        values = [float(v) for v in prices_for(6)]
        values[10] = None
        values[11] = 0

        result = self.service(yahoo_json(values)).prices(['X'])

        assert len(result['dates']) == len(DATES) - 2

    @pytest.mark.parametrize(
        'body, message',
        [
            ('not json', 'not understood'),
            ('{}', 'not understood'),
            (json.dumps({'chart': {'result': [], 'error': None}}), 'not understood'),
            (json.dumps({'chart': {'result': [{'timestamp': [1]}], 'error': None}}), 'not understood'),
            (yahoo_json([1.0], error={'code': 'Not Found', 'description': 'No data found'}), 'does not know'),
        ],
    )
    def test_refuses_what_is_not_a_chart(self, body, message):
        with pytest.raises(MarketDataError, match=message):
            self.service(body).prices(['X'])

    def test_a_404_means_an_unknown_symbol(self):
        with pytest.raises(MarketDataError, match='does not know') as error:
            self.service('', status=404).prices(['X'])
        assert error.value.status == 422


# ----------------------------------------------------------------------------------------------------------------------
# The service
# ----------------------------------------------------------------------------------------------------------------------


class TestService:
    def test_aligns_symbols_on_the_dates_all_of_them_traded(self):
        short = DATES[20:]
        service = stooq_service({'a': stooq_csv(prices_for(1)), 'b': stooq_csv(prices_for(2)[20:], short)})

        result = service.prices(['a', 'b'])

        assert result['symbols'] == ['A', 'B'] and len(result['dates']) == len(short)
        assert len(result['prices']['A']) == len(result['prices']['B']) == len(short)
        assert result['prices']['A'] == pytest.approx(list(prices_for(1)[20:]), abs=1e-5)

    def test_applies_the_date_range(self):
        service = stooq_service({'a': stooq_csv(prices_for(1))})

        result = service.prices(['a'], start=dt.date(2024, 2, 1), end=dt.date(2024, 4, 30))

        assert result['dates'][0] >= '2024-02-01' and result['dates'][-1] <= '2024-04-30'

    def test_needs_enough_overlapping_history(self):
        service = stooq_service({'a': stooq_csv(prices_for(1)), 'b': stooq_csv(prices_for(2)[:40], DATES[:40])})

        with pytest.raises(MarketDataError, match='at least 61'):
            service.prices(['a', 'b'])

    def test_keeps_the_latest_observations_within_the_limit(self, monkeypatch):
        monkeypatch.setattr(marketdata.analysis, 'MAX_OBSERVATIONS', 80)
        service = stooq_service({'a': stooq_csv(prices_for(1))})

        result = service.prices(['a'])

        assert len(result['dates']) == 81 and result['dates'][-1] == str(DATES[-1].date())

    def test_repeated_requests_come_from_the_cache(self):
        calls = []
        service = stooq_service({'a': stooq_csv(prices_for(1))}, calls)

        service.prices(['a'])
        service.prices(['A'])
        service.prices(['a'], start=dt.date(2024, 3, 1))

        assert len(calls) == 1

    @pytest.mark.parametrize(
        'text, message',
        [
            ('', 'between 1 and'),
            (',,', 'between 1 and'),
            (','.join('abcdefghijkl'), 'between 1 and'),
            ('a,A', 'once'),
            ('../etc/passwd', 'not a valid symbol'),
            ('a b', 'not a valid symbol'),
            ('spy.us?x=1', 'not a valid symbol'),
            ('x' * 21, 'not a valid symbol'),
            ('http://evil.example', 'not a valid symbol'),
        ],
    )
    def test_symbols_are_validated(self, text, message):
        with pytest.raises(MarketDataError, match=message):
            marketdata.parse_symbols(text)

    def test_accepts_the_symbols_of_the_common_markets(self):
        assert marketdata.parse_symbols('THYAO.IS, ^GSPC,EURUSD=X ,brk-b,spy.us') == [
            'THYAO.IS',
            '^GSPC',
            'EURUSD=X',
            'brk-b',
            'spy.us',
        ]

    def test_unknown_providers_are_refused(self):
        with pytest.raises(ValueError, match='Unknown market data provider'):
            MarketData('nope')
        assert marketdata.make_market_data(None) is None


# ----------------------------------------------------------------------------------------------------------------------
# HTTP
# ----------------------------------------------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    app = create_app(Settings(database=tmp_path / 'runs.db', market_data='stooq'))
    bodies = {'a': stooq_csv(prices_for(1)), 'b': stooq_csv(prices_for(2))}
    app.state.application.market = stooq_service(bodies)
    return TestClient(app)


class TestApi:
    def test_can_be_switched_off(self, tmp_path):
        client = TestClient(create_app(Settings(database=tmp_path / 'runs.db', market_data=None)))

        assert client.get('/api/config').json()['market_data'] is None
        response = client.get('/api/market/prices?symbols=a')
        assert response.status_code == 404 and 'not enabled' in response.json()['error']

    def test_config_names_the_source(self, client):
        assert client.get('/api/config').json()['market_data'] == 'Stooq'

    def test_returns_prices_ready_to_analyse(self, client):
        response = client.get('/api/market/prices?symbols=a,b')

        assert response.status_code == 200
        body = response.json()
        assert body['symbols'] == ['A', 'B'] and body['source'] == 'Stooq'
        analysed = client.post(
            '/api/portfolio', json={'assets': body['prices'], 'kind': 'prices', 'dates': body['dates'], 'window': 60}
        )
        assert analysed.status_code == 200 and analysed.json()['summary']['observations'] == len(DATES) - 1

    def test_single_symbol_prices_can_be_analysed(self, client):
        body = client.get('/api/market/prices?symbols=a').json()

        analysed = client.post(
            '/api/analyze', json={'prices': body['prices']['A'], 'dates': body['dates'], 'window': 60}
        )

        assert analysed.status_code == 200

    @pytest.mark.parametrize(
        'query, status, message',
        [
            ('', 422, 'between 1 and'),
            ('symbols=../x', 422, 'not a valid symbol'),
            ('symbols=a&start=yesterday', 422, 'YYYY-MM-DD'),
            ('symbols=unknown', 422, 'no prices'),
            ('symbols=a&start=2030-01-01', 422, 'at least 61'),
        ],
    )
    def test_reports_what_is_wrong(self, client, query, status, message):
        response = client.get(f'/api/market/prices?{query}')

        assert response.status_code == status and message in response.json()['error']

    def test_upstream_failures_are_502_and_logged_without_detail_to_the_caller(self, tmp_path):
        app = create_app(Settings(database=tmp_path / 'runs.db', market_data='stooq'))
        app.state.application.market = stooq_service({}, status=500)

        response = TestClient(app).get('/api/market/prices?symbols=a')

        assert response.status_code == 502 and response.json() == {
            'error': 'Stooq answered with status 500'
        }  # after one retry

    def test_needs_the_token_like_the_rest(self, tmp_path):
        app = create_app(
            Settings(database=tmp_path / 'runs.db', market_data='stooq', api_token='a-long-enough-test-token')
        )

        assert TestClient(app).get('/api/market/prices?symbols=a').status_code == 401


class TestSettings:
    def test_reads_and_validates_the_provider(self):
        assert Settings.from_env({'RISK_APP_MARKET_DATA': 'Yahoo'}).market_data == 'yahoo'
        assert Settings.from_env({}).market_data == 'yahoo'  # verified against the live service
        assert Settings.from_env({'RISK_APP_MARKET_DATA': 'off'}).market_data is None
        assert Settings.from_env({'RISK_APP_MARKET_DATA': 'NONE'}).market_data is None
        with pytest.raises(ValueError, match='market_data'):
            Settings.from_env({'RISK_APP_MARKET_DATA': 'bloomberg'})


class TestCheck:
    def test_reports_what_a_working_provider_returned(self):
        client = client_for(lambda request: httpx.Response(200, text=stooq_csv(prices_for(1))))

        report = marketdata.check('stooq', client=client)

        assert report['ok'] and report['symbol'] == 'aapl.us' and report['observations'] == len(DATES)
        assert report['first'] == str(DATES[0].date()) and report['last'] == str(DATES[-1].date())
        assert report['last_close'] == pytest.approx(prices_for(1)[-1], abs=1e-3) and report['enough_for_analysis']

    def test_says_when_the_history_is_too_short(self):
        client = client_for(lambda request: httpx.Response(200, text=stooq_csv(prices_for(1)[:30], DATES[:30])))

        assert marketdata.check('stooq', client=client)['enough_for_analysis'] is False

    def test_reports_failures_instead_of_raising(self):
        def refuse(request):
            raise httpx.ConnectError('blocked')

        refused = marketdata.check('yahoo', 'AAPL', client_for(refuse))
        forbidden = marketdata.check('stooq', client=client_for(lambda r: httpx.Response(403)))
        bad_symbol = marketdata.check('yahoo', '../x', client_for(refuse))

        assert not refused['ok'] and 'Could not reach' in refused['error']
        assert not forbidden['ok'] and 'status 403' in forbidden['error']
        assert not bad_symbol['ok'] and 'not a valid symbol' in bad_symbol['error']

    def test_defaults_name_each_providers_own_spelling(self):
        assert marketdata.DEFAULT_CHECK_SYMBOLS == {'stooq': 'aapl.us', 'yahoo': 'AAPL'}
        assert set(marketdata.DEFAULT_CHECK_SYMBOLS) == set(marketdata.FETCHERS)


# ----------------------------------------------------------------------------------------------------------------------
# Currencies
# ----------------------------------------------------------------------------------------------------------------------


def fx_service(quotes: dict, calls=None) -> MarketData:
    """Yahoo, answering from memory: symbol -> (currency, prices, dates)"""
    from urllib.parse import unquote

    def handler(request: httpx.Request) -> httpx.Response:
        symbol = unquote(request.url.path.rsplit('/', 1)[-1])
        if calls is not None:
            calls.append(symbol)
        if symbol not in quotes:
            return httpx.Response(404)
        currency, values, dates = quotes[symbol]
        return httpx.Response(200, text=yahoo_json(values, dates, currency=currency))

    return MarketData('yahoo', client_for(handler))


class TestCurrency:
    @pytest.fixture
    def quotes(self):
        usdtry = 30 + np.arange(len(DATES)) * 0.05
        return {
            'AAPL': ('USD', prices_for(1), DATES),
            'THYAO.IS': ('TRY', prices_for(2) * 3, DATES),
            'USDTRY=X': ('TRY', usdtry, DATES),
            'SAP.DE': ('EUR', prices_for(3), DATES),
            'EURUSD=X': ('USD', 1.1 + np.arange(len(DATES)) * 0.001, DATES),
        }

    def test_mixed_currencies_are_converted_to_the_first_symbols_currency(self, quotes):
        result = fx_service(quotes).prices(['THYAO.IS', 'AAPL'])

        assert result['base'] == 'TRY' and result['currencies'] == {'THYAO.IS': 'TRY', 'AAPL': 'USD'}
        assert result['prices']['THYAO.IS'] == pytest.approx(list(prices_for(2) * 3), abs=1e-4)
        expected = prices_for(1) * (30 + np.arange(len(DATES)) * 0.05)
        assert result['prices']['AAPL'] == pytest.approx(list(expected), rel=1e-6)
        assert list(result['converted']) == ['AAPL'] and result['converted']['AAPL']['rate'] == 'USDTRY=X'
        assert any('different currencies' in n for n in result['notes'])
        assert any('USDTRY=X' in n for n in result['notes'])

    def test_an_explicit_base_wins_and_converts_every_other_currency(self, quotes):
        result = fx_service(quotes).prices(['THYAO.IS', 'AAPL'], base='usd')

        assert result['base'] == 'USD' and list(result['converted']) == ['THYAO.IS']
        expected = (
            prices_for(2) * 3 / (30 + np.arange(len(DATES)) * 0.05)
        )  # TRYUSD=X is not quoted: the inverse is used
        assert result['prices']['THYAO.IS'] == pytest.approx(list(expected), rel=1e-6)
        assert result['prices']['AAPL'] == pytest.approx(list(prices_for(1)), abs=1e-4)
        assert result['converted']['THYAO.IS']['rate'] == 'USDTRY=X'

    def test_the_direct_pair_is_preferred_to_the_inverse(self, quotes):
        calls = []

        fx_service(quotes, calls).prices(['SAP.DE', 'AAPL'], base='USD')

        assert 'EURUSD=X' in calls and 'USDEUR=X' not in calls

    def test_one_currency_needs_no_conversion_and_no_exchange_rate_request(self, quotes):
        calls = []

        result = fx_service(quotes, calls).prices(['AAPL'])

        assert result['base'] is None and result['converted'] == {} and calls == ['AAPL']
        assert result['notes'] == []

    def test_a_single_symbol_is_converted_only_when_asked(self, quotes):
        plain = fx_service(quotes).prices(['AAPL'])
        converted = fx_service(quotes).prices(['AAPL'], base='TRY')

        assert plain['base'] is None and converted['base'] == 'TRY'
        assert converted['prices']['AAPL'][0] == pytest.approx(prices_for(1)[0] * 30, rel=1e-6)

    def test_the_same_currency_as_the_base_is_left_alone(self, quotes):
        result = fx_service(quotes).prices(['AAPL'], base='USD')

        assert result['base'] == 'USD' and result['converted'] == {} and result['notes'] == []

    def test_pence_are_turned_into_pounds_before_conversion(self, quotes):
        quotes['VOD.L'] = ('GBp', prices_for(4) * 100, DATES)
        quotes['GBPUSD=X'] = ('USD', np.full(len(DATES), 1.25), DATES)

        result = fx_service(quotes).prices(['VOD.L'], base='USD')

        assert result['prices']['VOD.L'] == pytest.approx(list(prices_for(4) * 1.25), rel=1e-6)
        assert result['currencies']['VOD.L'] == 'GBP'

    def test_pence_priced_assets_converted_to_pounds_need_no_exchange_rate(self, quotes):
        quotes['VOD.L'] = ('GBX', prices_for(4) * 100, DATES)
        calls = []

        result = fx_service(quotes, calls).prices(['VOD.L'], base='GBP')

        assert result['prices']['VOD.L'] == pytest.approx(list(prices_for(4)), rel=1e-6) and calls == ['VOD.L']

    def test_a_rate_is_carried_over_a_holiday_but_not_a_long_gap(self, quotes):
        rate_dates = DATES.delete([30, 31])  # two days without a rate
        quotes['USDTRY=X'] = ('TRY', 30 + np.arange(len(rate_dates)) * 0.05, rate_dates)

        result = fx_service(quotes).prices(['THYAO.IS', 'AAPL'])

        assert len(result['dates']) == len(DATES)
        first_gap = 30 + 29 * 0.05
        assert result['prices']['AAPL'][30] == pytest.approx(prices_for(1)[30] * first_gap, rel=1e-6)
        quotes['USDTRY=X'] = ('TRY', 30 + np.arange(len(DATES) - 10) * 0.05, DATES[10:])  # rates start ten days late
        late = fx_service(quotes).prices(['THYAO.IS', 'AAPL'])
        assert late['dates'][0] >= str(DATES[10].date())

    def test_a_missing_exchange_rate_is_reported(self, quotes):
        del quotes['USDTRY=X']

        with pytest.raises(MarketDataError, match='No exchange rate between USD and TRY'):
            fx_service(quotes).prices(['THYAO.IS', 'AAPL'])

    def test_an_unreachable_rate_service_is_a_502_not_a_missing_rate(self, quotes):
        def handler(request):
            if 'USDTRY' in request.url.path or 'TRYUSD' in request.url.path:
                return httpx.Response(503)
            return httpx.Response(
                200, text=yahoo_json(prices_for(1), currency='USD' if 'AAPL' in request.url.path else 'TRY')
            )

        with pytest.raises(MarketDataError) as error:
            MarketData('yahoo', client_for(handler)).prices(['THYAO.IS', 'AAPL'])

        assert error.value.status == 502

    def test_an_unknown_currency_is_left_alone(self, quotes):
        quotes['AAPL'] = (None, prices_for(1), DATES)

        result = fx_service(quotes).prices(['THYAO.IS', 'AAPL'])

        assert result['base'] is None and result['converted'] == {} and result['currencies']['AAPL'] is None

    def test_a_base_that_is_not_a_currency_code_is_refused(self, quotes):
        for bad in ('TL', 'TURKISH', '12$', 'US D'):
            with pytest.raises(MarketDataError, match='not a currency code'):
                fx_service(quotes).prices(['AAPL'], base=bad)

    def test_stooq_cannot_convert(self):
        with pytest.raises(MarketDataError, match='needs Yahoo Finance'):
            stooq_service({'a': stooq_csv(prices_for(1))}).prices(['a'], base='TRY')

    def test_returns_are_those_of_an_investor_in_the_base_currency(self, quotes):
        """A flat dollar price still moves in lira when the lira weakens: that is the point of converting"""
        quotes['AAPL'] = ('USD', np.full(len(DATES), 100.0), DATES)

        result = fx_service(quotes).prices(['THYAO.IS', 'AAPL'])
        returns = pd.Series(result['prices']['AAPL']).pct_change().dropna()

        assert (returns > 0).all() and returns.iloc[0] == pytest.approx(0.05 / 30, rel=1e-6)


class TestCurrencyApi:
    @pytest.fixture
    def client(self, tmp_path):
        app = create_app(Settings(database=tmp_path / 'runs.db', market_data='yahoo'))
        quotes = {
            'AAPL': ('USD', prices_for(1), DATES),
            'THYAO.IS': ('TRY', prices_for(2) * 3, DATES),
            'USDTRY=X': ('TRY', 30 + np.arange(len(DATES)) * 0.05, DATES),
        }
        app.state.application.market = fx_service(quotes)
        return TestClient(app)

    def test_converted_prices_can_be_analysed_as_a_portfolio(self, client):
        body = client.get('/api/market/prices?symbols=THYAO.IS,AAPL').json()

        analysed = client.post(
            '/api/portfolio', json={'assets': body['prices'], 'kind': 'prices', 'dates': body['dates'], 'window': 60}
        )

        assert body['base'] == 'TRY' and body['notes']
        assert analysed.status_code == 200 and analysed.json()['summary']['observations'] == len(DATES) - 1

    def test_the_base_currency_is_a_query_parameter(self, client):
        usd = client.get('/api/market/prices?symbols=AAPL,THYAO.IS&base=USD').json()
        try_ = client.get('/api/market/prices?symbols=AAPL,THYAO.IS&base=TRY').json()

        assert usd['base'] == 'USD' and try_['base'] == 'TRY'
        assert usd['prices']['AAPL'] != try_['prices']['AAPL']

    def test_errors_are_reported_with_their_status(self, client):
        bad = client.get('/api/market/prices?symbols=AAPL&base=dollars')
        missing = client.get('/api/market/prices?symbols=AAPL&base=JPY')

        assert bad.status_code == 422 and 'currency code' in bad.json()['error']
        assert missing.status_code == 422 and 'No exchange rate between USD and JPY' in missing.json()['error']
