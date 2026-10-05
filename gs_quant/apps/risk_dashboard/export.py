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

import argparse
import json
from html import escape
from pathlib import Path
from typing import Optional

from gs_quant.timeseries.risk_metrics import VaRMethod

from . import analysis

PACKAGE_DIR = Path(__file__).parent
STATIC_DIR = PACKAGE_DIR / 'static'
DEFAULT_CONFIDENCES = (0.9, 0.95, 0.975, 0.99)
DEFAULT_WINDOW = 250
SHARED_KEYS = ('dates', 'returns', 'growth', 'drawdown')


def build_payload(
    n: int = 1000,
    seed: int = 7,
    window: int = DEFAULT_WINDOW,
    confidences: tuple[float, ...] = DEFAULT_CONFIDENCES,
) -> dict:
    """Run the backend analysis for every scenario, confidence level and method

    The return, growth and drawdown series do not depend on the settings, so they are stored once per scenario.
    """
    data: dict = {}
    for scenario in analysis.SCENARIOS:
        returns = analysis.simulate_returns(scenario, n, seed)
        variants: dict = {}
        shared: Optional[dict] = None
        for confidence in confidences:
            for method in VaRMethod:
                result = analysis.analyze(returns, confidence, method, window)
                if shared is None:
                    shared = {
                        **{k: result['series'][k] for k in SHARED_KEYS},
                        **{k: result[k] for k in ('histogram', 'qq', 'worst_drawdown', 'stress', 'conventions')},
                    }
                variants[f'{confidence}|{method.value}'] = {
                    'summary': result['summary'],
                    'backtest': result['backtest'],
                    'settings': result['settings'],
                    'assumptions': result['assumptions'],
                    'horizon': result['horizon'],
                    'ewma': result['ewma'],
                    **{k: v for k, v in result['series'].items() if k not in SHARED_KEYS},
                }
        data[scenario] = {'shared': shared, 'variants': variants}
    return {
        'confidences': list(confidences),
        'window': window,
        'scenarios': [
            {'id': key, 'title': p['title'], 'description': p['description']} for key, p in analysis.SCENARIOS.items()
        ],
        'data': data,
    }


def _script_safe(text: str) -> str:
    """Make text safe to embed in an inline <script> element"""
    return text.replace('</', '<\\/').replace('<!--', '<\\!--')


def render(payload: dict, title: Optional[str] = None) -> str:
    """A single self-contained HTML document: the dashboard with its scripts, styles and data inlined"""
    html = (STATIC_DIR / 'index.html').read_text(encoding='utf-8')
    css = (STATIC_DIR / 'styles.css').read_text(encoding='utf-8')
    app_js = (STATIC_DIR / 'app.js').read_text(encoding='utf-8')
    i18n_js = (STATIC_DIR / 'i18n.js').read_text(encoding='utf-8')
    static_api = (PACKAGE_DIR / 'static_api.js').read_text(encoding='utf-8')
    data = json.dumps(payload, separators=(',', ':'), allow_nan=False)

    replacements = {
        '<link rel="stylesheet" href="/static/styles.css">': f'<style>\n{css}\n</style>',
        '<script src="/static/i18n.js" defer></script>': f'<script>window.__RISK_DATA__ = {_script_safe(data)};</script>\n<script>\n{_script_safe(static_api)}\n</script>\n<script>\n{_script_safe(i18n_js)}\n</script>',
        '<script src="/static/app.js" defer></script>': f'<script>\n{_script_safe(app_js)}\n</script>',
    }
    for old, new in replacements.items():
        if old not in html:
            raise ValueError(f'Expected {old!r} in index.html')
        html = html.replace(old, new)
    if title:
        html = html.replace('<title data-t>Risk Analytics Dashboard</title>', f'<title data-t>{escape(title)}</title>')
    return html


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description='Export the dashboard as one self-contained HTML file')
    parser.add_argument('-o', '--output', default='risk_dashboard.html', type=Path)
    parser.add_argument('--observations', type=int, default=1000)
    parser.add_argument('--seed', type=int, default=7)
    args = parser.parse_args(argv)
    args.output.write_text(render(build_payload(args.observations, args.seed)), encoding='utf-8')
    print(f'Wrote {args.output} ({args.output.stat().st_size / 1e6:.1f} MB)')


if __name__ == '__main__':
    main()
