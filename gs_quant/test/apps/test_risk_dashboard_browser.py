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

import os
import pathlib
import socket
import threading
import time

import numpy as np
import pytest

# The browser tests are skipped where Playwright or a browser is missing, unless CI says they must run
REQUIRED = os.environ.get('RISK_APP_REQUIRE_BROWSER') == '1'

pytest.importorskip('starlette')
pytest.importorskip('uvicorn')
if REQUIRED:
    from playwright import sync_api
else:
    sync_api = pytest.importorskip('playwright.sync_api')

import uvicorn  # noqa: E402

from gs_quant.apps.risk_dashboard.app import create_app  # noqa: E402
from gs_quant.apps.risk_dashboard.settings import Settings  # noqa: E402
from gs_quant.test.apps.test_risk_dashboard_marketdata import DATES, fx_service, prices_for  # noqa: E402


def _chromium():
    """A browser the environment already has, else None for Playwright's own"""
    path = pathlib.Path(os.environ.get('PLAYWRIGHT_BROWSERS_PATH', '')) / 'chromium'
    return str(path) if path.is_file() else None


@pytest.fixture(scope='module')
def server(tmp_path_factory):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    settings = Settings(port=port, database=tmp_path_factory.mktemp('data') / 'runs.db', market_data='yahoo')
    app = create_app(settings)
    quotes = {
        'THYAO.IS': ('TRY', prices_for(1), DATES),
        'GARAN.IS': ('TRY', prices_for(2), DATES),
        'ASELS.IS': ('TRY', prices_for(3), DATES),
        'AAPL': ('USD', prices_for(4), DATES),
        'USDTRY=X': ('TRY', 30 + np.arange(len(DATES)) * 0.05, DATES),
    }
    app.state.application.market = fx_service(quotes)  # no network: the provider answers from memory
    instance = uvicorn.Server(uvicorn.Config(app, port=port, log_level='warning'))
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not instance.started and time.time() < deadline:
        time.sleep(0.05)
    yield f'http://127.0.0.1:{port}'
    instance.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope='module')
def browser():
    with sync_api.sync_playwright() as playwright:
        try:
            instance = playwright.chromium.launch(executable_path=_chromium(), args=['--no-sandbox'])
        except Exception as e:  # no browser installed
            if REQUIRED:
                raise
            pytest.skip(f'Chromium is not available: {e}')
        yield instance
        instance.close()


def test_portfolio_save_open_report_and_delete(server, browser, tmp_path):
    page = browser.new_page(accept_downloads=True)
    problems = []
    page.on('pageerror', lambda e: problems.append(str(e)))
    page.on('console', lambda m: problems.append(m.text) if m.type in ('error', 'warning') else None)

    page.goto(server)
    page.wait_for_selector('#results:not([hidden])')
    page.click('input[name=mode][value=portfolio]')
    page.click('#portfolio-sample')
    page.wait_for_selector('#portfolio-section:not([hidden])')
    assert page.locator('#table-assets tbody tr').count() == 4  # three assets and the portfolio
    assert page.locator('#table-stress tbody tr').count() == 3  # the worst 1, 5 and 20 periods
    assert page.locator('#table-stress thead th').count() == 7  # window, return, dates and three assets

    page.fill('#run-name', 'Browser test')
    page.click('#save-form button')
    page.wait_for_selector('#report:not([hidden])')
    assert 'Browser test' in page.inner_text('#history')

    with page.expect_download() as download:
        page.click('#report')
    report = tmp_path / 'report.html'
    download.value.save_as(report)

    page.reload()
    page.click('#history li button[data-action=open]')
    page.wait_for_selector('#portfolio-section:not([hidden])')

    saved = browser.new_page()
    saved.on('pageerror', lambda e: problems.append(str(e)))
    saved.on('console', lambda m: problems.append(m.text) if m.type in ('error', 'warning') else None)
    saved.goto(report.as_uri())
    saved.wait_for_selector('#results:not([hidden])')
    assert saved.is_visible('#portfolio-section') and not saved.is_visible('#controls-panel')
    assert 'Browser test' in saved.inner_text('#provenance')

    # a second analysis, with other weights, to compare against
    page.fill('#weight-0', '70')
    page.press('#weight-0', 'Tab')
    page.wait_for_selector('#results:not(.loading)')
    page.fill('#run-name', 'Browser test, 70% calm')
    page.click('#save-form button')
    page.locator('#history li').nth(1).wait_for()
    assert page.is_disabled('#compare')
    page.locator('#history input[data-compare]').nth(0).check()
    page.locator('#history input[data-compare]').nth(1).check()
    page.click('#compare')
    page.wait_for_selector('#compare-panel:not([hidden])')
    assert page.locator('#table-compare thead th').count() == 2
    assert page.locator('#table-compare tbody tr').count() >= 15
    page.click('#compare-close')
    assert not page.is_visible('#compare-panel')

    page.once('dialog', lambda dialog: dialog.accept())
    page.click('#history li button[data-action=delete]')
    page.locator('#history li').nth(1).wait_for(state='detached')

    assert problems == []  # no script error and no Content Security Policy violation, in the app or in the report


def test_loading_prices_by_symbol(server, browser):
    page = browser.new_page()
    problems = []
    page.on('pageerror', lambda e: problems.append(str(e)))
    page.on('console', lambda m: problems.append(m.text) if m.type in ('error', 'warning') else None)

    page.goto(server)
    page.wait_for_selector('#market-field:not([hidden])')
    assert 'Yahoo Finance' in page.inner_text('#market-hint')

    page.fill('#symbols', 'THYAO.IS, GARAN.IS')  # one symbol only in this mode
    page.click('#market-load')
    page.locator('#status.error').wait_for()
    assert 'one symbol' in page.inner_text('#status')

    page.fill('#symbols', 'THYAO.IS')
    page.select_option('#market-history', 'all')
    page.click('#market-load')
    page.locator('#provenance').filter(has_text='prices from Yahoo Finance').wait_for()
    provenance = page.inner_text('#provenance').lower()
    assert 'thyao.is' in provenance and 'market data' in provenance

    page.click('input[name=mode][value=portfolio]')
    page.fill('#symbols', 'THYAO.IS, GARAN.IS, ASELS.IS')
    page.click('#market-load')
    page.wait_for_selector('#portfolio-section:not([hidden])')
    assert page.locator('#table-assets tbody tr').count() == 4
    assert 'ASELS.IS' in page.inner_text('#table-assets')

    # assets quoted in different currencies are converted to one
    page.fill('#symbols', 'THYAO.IS, AAPL')
    page.click('#market-load')
    page.locator('#provenance').filter(has_text='THYAO.IS, AAPL in TRY').wait_for()
    assert 'USDTRY=X' in page.text_content('#notes') and 'different currencies' in page.text_content('#notes')
    page.select_option('#market-base', 'USD')
    page.click('#market-load')
    page.locator('#provenance').filter(has_text='in USD').wait_for()
    page.select_option('#market-base', '')

    page.fill('#symbols', 'NOPE.IS')
    page.click('#market-load')
    page.locator('#status.error').filter(has_text='at least two').wait_for()

    assert problems == []
