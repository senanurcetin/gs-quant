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

from urllib.parse import unquote

import httpx
import numpy as np
import pytest

pytest.importorskip('starlette')

from starlette.testclient import TestClient  # noqa: E402

from gs_quant.apps.risk_dashboard import marketdata, store as store_module  # noqa: E402
from gs_quant.apps.risk_dashboard.app import create_app  # noqa: E402
from gs_quant.apps.risk_dashboard.marketdata import MarketData, MarketDataError  # noqa: E402
from gs_quant.apps.risk_dashboard.settings import Settings  # noqa: E402
from gs_quant.apps.risk_dashboard.store import RunStore  # noqa: E402
from gs_quant.test.apps.test_risk_dashboard_marketdata import DATES, client_for, prices_for, yahoo_json  # noqa: E402


@pytest.fixture(autouse=True)
def no_waiting(monkeypatch):
    monkeypatch.setattr(marketdata, 'RETRY_DELAY_SECONDS', 0)


class Provider:
    """Yahoo, answering from memory, until it is told to be down or to be missing a symbol"""

    def __init__(self, quotes):
        self.quotes = quotes
        self.down = False
        self.calls: list[str] = []

    def client(self) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            symbol = unquote(request.url.path.rsplit('/', 1)[-1])
            self.calls.append(symbol)
            if self.down:
                return httpx.Response(503)
            if symbol not in self.quotes:
                return httpx.Response(404)
            currency, values, dates = self.quotes[symbol]
            return httpx.Response(200, text=yahoo_json(values, dates, currency=currency))

        return client_for(handler)


@pytest.fixture
def quotes():
    return {
        'AAPL': ('USD', prices_for(1), DATES),
        'THYAO.IS': ('TRY', prices_for(2), DATES),
        'USDTRY=X': ('TRY', 30 + np.arange(len(DATES)) * 0.05, DATES),
    }


@pytest.fixture
def archive(tmp_path):
    return RunStore(tmp_path / 'runs.db')


def market_with(provider, archive):
    return MarketData('yahoo', provider.client(), archive=archive)


class TestSavedCopies:
    def test_each_fetch_keeps_the_latest_prices(self, quotes, archive):
        market = market_with(Provider(quotes), archive)

        market.prices(['THYAO.IS'])

        payload, fetched_at = archive.load_prices('yahoo', 'THYAO.IS')
        assert payload['currency'] == 'TRY' and len(payload['dates']) == len(DATES)
        assert payload['values'] == pytest.approx(list(prices_for(2)))
        assert fetched_at[:4].isdigit()

    def test_a_provider_that_cannot_be_reached_is_replaced_by_the_saved_copy_with_a_note(self, quotes, archive):
        provider = Provider(quotes)
        fresh = market_with(provider, archive).prices(['THYAO.IS'])
        provider.down = True

        stale = market_with(provider, archive).prices(['THYAO.IS'])  # a new process, a new in-memory cache

        assert stale['prices'] == fresh['prices'] and stale['dates'] == fresh['dates']
        assert list(stale['stale']) == ['THYAO.IS']
        assert any('come from the copy saved on' in n and 'could not be reached' in n for n in stale['notes'])
        assert fresh['stale'] == {} and not any('copy saved' in n for n in fresh['notes'])

    def test_the_currency_of_the_copy_is_kept_so_it_can_still_be_converted(self, quotes, archive):
        provider = Provider(quotes)
        market_with(provider, archive).prices(['AAPL', 'THYAO.IS'], base='TRY')
        provider.down = True

        stale = market_with(provider, archive).prices(['AAPL', 'THYAO.IS'], base='TRY')

        assert stale['currencies'] == {'AAPL': 'USD', 'THYAO.IS': 'TRY'}
        assert stale['converted']['AAPL']['rate'] == 'USDTRY=X'
        assert sorted(stale['stale']) == ['AAPL', 'THYAO.IS', 'USDTRY=X']  # the exchange rate was a saved copy too

    def test_an_unknown_symbol_is_never_answered_with_old_prices(self, quotes, archive):
        provider = Provider(quotes)
        market_with(provider, archive).prices(['THYAO.IS'])
        del provider.quotes['THYAO.IS']  # delisted, or a typo in the provider's eyes

        with pytest.raises(MarketDataError, match='does not know this symbol') as raised:
            market_with(provider, archive).prices(['THYAO.IS'])

        assert raised.value.status == 422

    def test_nothing_saved_means_the_error_stands(self, quotes, archive):
        provider = Provider(quotes)
        provider.down = True

        with pytest.raises(MarketDataError, match='answered with status 503') as raised:
            market_with(provider, archive).prices(['THYAO.IS'])

        assert raised.value.status == 502

    def test_without_an_archive_nothing_changes(self, quotes):
        provider = Provider(quotes)
        market = MarketData('yahoo', provider.client())
        market.prices(['THYAO.IS'])
        provider.down = True

        fresh = MarketData('yahoo', provider.client())
        with pytest.raises(MarketDataError):
            fresh.prices(['THYAO.IS'])

    def test_a_provider_that_is_down_is_not_asked_again_at_every_request(self, quotes, archive):
        provider = Provider(quotes)
        market_with(provider, archive).prices(['THYAO.IS'])
        provider.down = True
        market = market_with(provider, archive)
        market.prices(['THYAO.IS'])
        asked = len(provider.calls)

        market.prices(['THYAO.IS'])
        market.prices(['THYAO.IS'])

        assert len(provider.calls) == asked  # the copy answered for the next minute

    def test_the_copy_is_replaced_once_the_provider_is_back(self, quotes, archive):
        provider = Provider(quotes)
        market = market_with(provider, archive)
        market.prices(['THYAO.IS'])
        provider.down = True
        market_with(provider, archive).prices(['THYAO.IS'])
        provider.down = False
        provider.quotes['THYAO.IS'] = ('TRY', prices_for(9), DATES)

        again = market_with(provider, archive).prices(['THYAO.IS'])

        assert again['stale'] == {} and again['prices']['THYAO.IS'] == pytest.approx(list(prices_for(9)), abs=1e-5)
        assert archive.load_prices('yahoo', 'THYAO.IS')[0]['values'] == pytest.approx(list(prices_for(9)))

    def test_an_archive_that_fails_does_not_fail_the_request(self, quotes):
        class Broken:
            def save_prices(self, *args):
                raise OSError('disk full')

            def load_prices(self, *args):
                raise OSError('disk gone')

        provider = Provider(quotes)
        market = market_with(provider, Broken())
        assert market.prices(['THYAO.IS'])['stale'] == {}

        provider.down = True
        with pytest.raises(MarketDataError, match='503'):  # no copy could be read: the provider's error is reported
            market_with(provider, Broken()).prices(['THYAO.IS'])


class TestStore:
    def test_round_trip_and_replacement(self, archive):
        archive.save_prices('yahoo', 'A', {'currency': 'USD', 'dates': ['2024-01-02'], 'values': [1.5]})
        archive.save_prices('yahoo', 'A', {'currency': 'USD', 'dates': ['2024-01-02'], 'values': [2.5]})

        payload, fetched_at = archive.load_prices('yahoo', 'A')

        assert payload['values'] == [2.5] and fetched_at.endswith('+00:00')
        assert archive.load_prices('stooq', 'A') is None and archive.load_prices('yahoo', 'B') is None

    def test_the_least_recently_fetched_are_dropped(self, archive, monkeypatch):
        monkeypatch.setattr(store_module, 'MAX_PRICE_SERIES', 2)
        for symbol in ('A', 'B', 'C'):
            archive.save_prices('yahoo', symbol, {'currency': None, 'dates': ['2024-01-02'], 'values': [1.0]})

        assert archive.load_prices('yahoo', 'A') is None
        assert archive.load_prices('yahoo', 'B') is not None and archive.load_prices('yahoo', 'C') is not None


class TestApi:
    def test_the_page_is_told_which_prices_are_copies(self, tmp_path, quotes):
        app = create_app(Settings(database=tmp_path / 'runs.db', market_data='yahoo'))
        provider = Provider(quotes)
        application = app.state.application
        application.market = MarketData('yahoo', provider.client(), archive=application.market._archive)
        client = TestClient(app)
        assert client.get('/api/market/prices', params={'symbols': 'THYAO.IS'}).json()['stale'] == {}
        provider.down = True
        application.market = MarketData('yahoo', provider.client(), archive=application.market._archive)

        body = client.get('/api/market/prices', params={'symbols': 'THYAO.IS'}).json()

        assert list(body['stale']) == ['THYAO.IS'] and len(body['dates']) == len(DATES)
        assert 'come from the copy saved on' in ' '.join(body['notes'])
