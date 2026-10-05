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
from pathlib import Path

import pytest

from gs_quant.apps.risk_dashboard import analysis, export
from gs_quant.timeseries.risk_metrics import VaRMethod

CONFIDENCES = (0.95, 0.99)
WINDOW = 100


@pytest.fixture(scope='module')
def payload() -> dict:
    return export.build_payload(n=400, seed=5, window=WINDOW, confidences=CONFIDENCES)


class TestPayload:
    def test_has_every_scenario_confidence_and_method(self, payload):
        assert payload['confidences'] == list(CONFIDENCES) and payload['window'] == WINDOW
        assert {s['id'] for s in payload['scenarios']} == set(analysis.SCENARIOS)
        for scenario in analysis.SCENARIOS:
            variants = payload['data'][scenario]['variants']
            assert set(variants) == {f'{c}|{m.value}' for c in CONFIDENCES for m in VaRMethod}

    def test_settings_independent_series_are_stored_once_per_scenario(self, payload):
        entry = payload['data']['calm']

        assert set(entry['shared']) >= {
            'dates',
            'returns',
            'growth',
            'drawdown',
            'histogram',
            'qq',
            'worst_drawdown',
            'stress',
        }
        for variant in entry['variants'].values():
            assert not {'dates', 'returns', 'growth', 'drawdown'} & set(variant)
            assert {'var', 'expected_shortfall', 'breach', 'summary', 'backtest'} <= set(variant)

    def test_is_strict_json(self, payload):
        json.dumps(payload, allow_nan=False)

    def test_variants_are_what_the_backend_computes(self, payload):
        returns = analysis.simulate_returns('volatile', 400, 5)

        expected = analysis.analyze(returns, 0.99, VaRMethod.CORNISH_FISHER, WINDOW)

        variant = payload['data']['volatile']['variants']['0.99|cornish_fisher']
        assert variant['summary'] == expected['summary']
        assert variant['backtest'] == expected['backtest']
        assert variant['var'] == expected['series']['var']


@pytest.fixture(scope='module')
def html(payload) -> str:
    return export.render(payload)


class TestRender:
    def test_is_one_self_contained_document(self, html):
        assert html.startswith('<!doctype html>')
        # the only <link> left is the favicon, embedded as a data URI rather than fetched
        assert all('href="data:' in tag for tag in re.findall(r'<link[^>]*>', html))
        assert 'src="/static' not in html
        assert 'href="/static' not in html
        assert html.count('<script>') == 3 and '<style>' in html

    def test_makes_no_network_requests(self, html):
        # the only URL that may appear is the link to the project page in the footer
        urls = set(re.findall(r'https?://[^\s"\'<>)]+', html))
        assert all(
            url.startswith(('https://github.com/goldmansachs/gs-quant', 'http://www.w3.org/2000/svg')) for url in urls
        )
        assert 'fetch(' in html  # the live client is still there, but never reached in static mode
        assert 'window.RiskApi' in html

    def test_embedded_data_round_trips(self, payload, html):
        match = re.search(r'window\.__RISK_DATA__ = (.*?);</script>', html, flags=re.DOTALL)

        assert json.loads(match.group(1).replace('<\\/', '</')) == payload

    def test_text_that_could_close_the_script_element_is_escaped(self):
        assert '</script>' not in export._script_safe('a</script><!--b')
        assert export._script_safe('a</script>') == 'a<\\/script>'

    def test_fails_loudly_if_the_page_no_longer_has_the_expected_tags(self, monkeypatch, payload, tmp_path):
        (tmp_path / 'index.html').write_text('<html></html>', encoding='utf-8')
        (tmp_path / 'styles.css').write_text('', encoding='utf-8')
        (tmp_path / 'app.js').write_text('', encoding='utf-8')
        monkeypatch.setattr(export, 'STATIC_DIR', tmp_path)

        with pytest.raises(ValueError, match='Expected'):
            export.render(payload)

    def test_main_writes_the_file(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setattr(export, 'build_payload', lambda n, seed: {'confidences': [0.95]})
        monkeypatch.setattr(export, 'render', lambda payload: '<html>demo</html>')
        target = tmp_path / 'out.html'

        export.main(['-o', str(target)])

        assert target.read_text(encoding='utf-8') == '<html>demo</html>'
        assert 'Wrote' in capsys.readouterr().out


@pytest.mark.skipif(shutil.which('node') is None, reason='Node.js is not installed')
class TestStaticApiInTheBrowserRuntime:
    """Runs the real static_api.js under Node and checks it hands the page exactly what the backend computed"""

    @staticmethod
    def _run(payload: dict, calls: list[dict]) -> list:
        script = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const sandbox = { window: {}, console };
sandbox.window.__RISK_DATA__ = input.payload;
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(input.api, 'utf8'), sandbox);
(async () => {
  const api = sandbox.window.RiskApi;
  const out = [];
  for (const call of input.calls) {
    try {
      out.push({ ok: await api.analyze(await api.loadScenario(call.id, call.id), call.settings) });
    } catch (e) {
      out.push({ error: e.message });
    }
  }
  console.log(JSON.stringify({ meta: [api.staticMode, api.confidences, api.window], out }));
})();
"""
        completed = subprocess.run(
            ['node', '-e', script],
            input=json.dumps(
                {'payload': payload, 'api': str(Path(export.PACKAGE_DIR / 'static_api.js')), 'calls': calls}
            ),
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        return json.loads(completed.stdout)

    def test_static_results_equal_the_backend_results(self, payload):
        cases = [
            ('calm', 0.95, VaRMethod.HISTORICAL),
            ('regime_shift', 0.99, VaRMethod.PARAMETRIC),
            ('volatile', 0.95, VaRMethod.CORNISH_FISHER),
        ]
        calls = [{'id': i, 'settings': {'confidence': c, 'method': m.value, 'window': WINDOW}} for i, c, m in cases]

        result = self._run(payload, calls)

        assert result['meta'] == [True, list(CONFIDENCES), WINDOW]
        for (scenario, confidence, method), outcome in zip(cases, result['out']):
            expected = analysis.analyze(analysis.simulate_returns(scenario, 400, 5), confidence, method, WINDOW)
            assert outcome['ok'] == json.loads(json.dumps(expected, allow_nan=False)), scenario

    def test_unavailable_settings_are_reported_not_invented(self, payload):
        result = self._run(
            payload, [{'id': 'calm', 'settings': {'confidence': 0.5, 'method': 'historical', 'window': WINDOW}}]
        )

        assert 'No precomputed result' in result['out'][0]['error']
