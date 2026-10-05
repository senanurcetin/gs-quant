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

import json
import re
import shutil
import subprocess

import pytest

from gs_quant.apps.risk_dashboard.app import STATIC_DIR

HTML = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
APP = (STATIC_DIR / 'app.js').read_text(encoding='utf-8')
I18N = STATIC_DIR / 'i18n.js'
PLACEHOLDER = re.compile(r'\{(\w+)\}')


def _norm(text: str) -> str:
    return ' '.join(text.split())


def source_texts() -> dict[str, str]:
    """Every English text the page can show, with where it comes from"""
    found: dict[str, str] = {}
    for m in re.finditer(r'<(\w+)[^>]*\sdata-t(?:\s[^>]*)?>([^<>]+)</\1>', HTML):
        found.setdefault(_norm(m.group(2)), 'html')
    for m in re.finditer(r'<(\w+)[^>]*data-t-nodes[^>]*>(.*?)</\1>', HTML, re.S):
        inner = re.sub(r'<input[^>]*>', '', m.group(2))
        for piece in re.split(r'<(?:code|output|span)[^>]*>[^<]*</(?:code|output|span)>', inner):
            if _norm(piece):
                found.setdefault(_norm(piece), 'text node')
    for m in re.finditer(r'data-t-attr="([^"]+)"[^>]*', HTML):
        for attribute in m.group(1).split(','):
            value = re.search(rf'\s{attribute}="([^"]*)"', m.group(0))
            if value:
                found.setdefault(value.group(1), 'attribute')
    for m in re.finditer(r"""\bt\((['`])((?:(?!\1).|\\.)*)\1""", APP):
        found.setdefault(m.group(2), 'app.js')
    # labels that are translated where they are used, not where they are written
    for m in re.finditer(r"\['([A-Z][^']*)', \(r\) =>", APP):
        found.setdefault(m.group(1), 'comparison row')
    found.update({'Green': 'zone', 'Yellow': 'zone', 'Red': 'zone'})
    return found


def translations() -> dict[str, str]:
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')
    script = (
        "global.window = {}; global.localStorage = { getItem() { return null; }, setItem() {} };"
        f"require({json.dumps(str(I18N))});"
        "process.stdout.write(JSON.stringify(window.I18n.translations));"
    )
    out = subprocess.run([node, '-e', script], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def test_the_page_has_something_to_translate():
    assert len(source_texts()) > 200


def test_every_text_has_a_turkish_translation():
    missing = sorted(set(source_texts()) - set(translations()))

    assert missing == []


def test_translations_keep_their_placeholders_and_strong_parts():
    broken = []
    for english, turkish in translations().items():
        if sorted(PLACEHOLDER.findall(english)) != sorted(PLACEHOLDER.findall(turkish)) or english.count(
            '**'
        ) != turkish.count('**'):
            broken.append(english)

    assert broken == []


def test_no_translation_is_unused_or_empty():
    table = translations()
    texts = set(source_texts())
    # scenario titles and descriptions come from the server, and are looked up where they are shown
    from gs_quant.apps.risk_dashboard import analysis

    from_server = {text for p in analysis.SCENARIOS.values() for text in (p['title'], p['description'])}

    assert [k for k, v in table.items() if not v.strip()] == []
    unused = sorted(k for k in table if k not in texts and k not in from_server)
    assert unused == [], 'translations of texts that are not in the page any more'


def test_the_server_scenarios_are_translated():
    from gs_quant.apps.risk_dashboard import analysis

    table = translations()
    for scenario in analysis.SCENARIOS.values():
        assert scenario['title'] in table and scenario['description'] in table


def test_server_messages_are_matched_by_the_patterns():
    """Runs the real patterns under Node against the messages the Python side really produces"""
    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is not installed')
    from gs_quant.apps.risk_dashboard import analysis, marketdata, portfolio

    messages = [
        'At least 60 returns are needed for a meaningful analysis',
        'Equal weights (33.3% each) were assumed',
        'The portfolio is rebalanced to its weights every period',
        'Only 40 dates have prices for all of A, B; at least 61 are needed',
        'No exchange rate between USD and TRY is available',
        'Yahoo Finance is limiting requests: try again in a minute',
        'There is no such run',
        'There is no such portfolio',
        'Too many requests: try again in 12 seconds',
        'Too many failed attempts: try again in 300 seconds',
        'You can keep at most 50 portfolios: delete one first',
        'Prices are in TRY, converted at the daily rate of USDTRY=X',
        'The assets are quoted in different currencies, so prices were converted to TRY',
        'The rolling window (250) must be shorter than the series (100 returns)',
        'Scenario "Crash": unknown asset "Z"',
        'The 10-period figures scale the one-period value at risk and expected shortfall by the square root of the '
        'horizon, which assumes independent returns and no drift',
        'At least 30 periods in common with the benchmark are needed',
        'The benchmark does not vary, so there is nothing to compare against',
        'The benchmark needs the same number of observations as the assets',
        'XU100.IS: Got 300 dates for 250 values',
        'Prices of AAPL, USDTRY=X come from the copy saved on 2026-10-05 because Yahoo Finance could not be reached: they may be out of date',
    ]
    script = (
        "global.window = {}; global.localStorage = { getItem() { return 'tr'; }, setItem() {} };"
        f"require({json.dumps(str(I18N))});"
        "const messages = JSON.parse(process.argv[1]);"
        "process.stdout.write(JSON.stringify(messages.map((m) => window.I18n.server(m))));"
    )
    out = json.loads(
        subprocess.run([node, '-e', script, json.dumps(messages)], capture_output=True, text=True, check=True).stdout
    )

    assert all(a != b for a, b in zip(out, messages)), [b for a, b in zip(out, messages) if a == b]
    assert out[1] == 'Eşit ağırlık (her biri %33.3) varsayıldı'
    assert out[-2] == 'XU100.IS: 250 değer için 300 tarih verildi'
    assert (
        out[-1]
        == 'AAPL, USDTRY=X fiyatları, Yahoo Finance erişilemediği için 2026-10-05 tarihinde kaydedilen kopyadan alındı: güncel olmayabilir'
    )
    # a message nobody translated is returned as it came
    unknown = subprocess.run(
        [node, '-e', script, json.dumps(['Something new'])], capture_output=True, text=True, check=True
    ).stdout
    assert json.loads(unknown) == ['Something new']
    assert analysis and marketdata and portfolio  # the modules whose messages these are


def test_the_script_does_not_write_html():
    source = I18N.read_text(encoding='utf-8')

    assert 'innerHTML' not in source and 'insertAdjacentHTML' not in source and 'eval(' not in source


def test_the_glossary_matches_the_translations():
    """TR_TERMS.md says which Turkish term stands for which English one: it must not drift from i18n.js"""
    glossary = (STATIC_DIR.parent / 'TR_TERMS.md').read_text(encoding='utf-8')
    values = set(translations().values())
    rows = [
        [cell.strip() for cell in line.strip().strip('|').split('|')]
        for line in glossary.splitlines()
        if line.startswith('| ') and not line.startswith('| ---') and not line.startswith('| İngilizce')
    ]

    assert len(rows) >= 18
    missing = [(row[0], row[1]) for row in rows if row[1].split(' (ES)')[0] not in values and row[1] not in values]
    assert missing == [], 'the glossary names a Turkish text that is not in static/i18n.js'
