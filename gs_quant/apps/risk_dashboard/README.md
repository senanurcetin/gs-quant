# Risk analytics dashboard

An example application built on [`gs_quant.timeseries.risk_metrics`](../../gs_quant/timeseries/risk_metrics.py): a small
web app that shows value at risk, expected shortfall and whether the VaR model can be trusted, for a simulated market or a
CSV of your own returns or prices. It needs no Marquee session.

It is an example, not part of the library: it lives outside the `gs_quant` package and is not installed with it.

```bash
pip install "gs-quant[mcp]"        # brings Starlette, Pydantic and uvicorn
python -m examples.risk_dashboard  # http://127.0.0.1:8000
```

Run it from the root of the repository. It binds to `127.0.0.1` only unless you pass `--host`.

## What it shows

- **Risk at a glance**: annualized return and volatility, VaR and expected shortfall at the chosen confidence, maximum
  drawdown, Sortino, Calmar, skewness and excess kurtosis.
- **Model validation**: the Kupiec frequency test, the Christoffersen independence and conditional coverage tests and the
  Basel traffic light, with a plain-language verdict computed from the results.
- **Charts**: growth and drawdown with the deepest episode marked, daily returns against the VaR forecast with the
  breaches highlighted, the distribution with the normal fit, and a QQ plot of the tails.
- **Download** of the calculated series as CSV.

Each VaR forecast is made from the previous window only and compared with the return that followed (no look-ahead).

The sample scenarios are simulated (GARCH(1,1) with Student-t innovations). One of them, *Regime shift*, is a calm market
that turns turbulent, which a trailing-window VaR model is slow to notice.

## Layout

| File | Purpose |
| --- | --- |
| `analysis.py` | Framework-free analysis: simulation, input validation and everything the page shows |
| `app.py` | Starlette app: JSON API, static files, security headers |
| `static/` | The page: `index.html`, `styles.css` and `app.js`. No framework, no third party code |
| `export.py`, `static_api.js` | Export the dashboard as one self-contained HTML file |
| `test_*.py` | Tests, run with `pytest examples` |

## API

| Endpoint | |
| --- | --- |
| `GET /api/scenarios` | The sample scenarios |
| `GET /api/sample?scenario=&n=&seed=` | Simulated returns |
| `POST /api/analyze` | Body: `returns` or `prices`, optional `dates`, `confidence` (0.8 to 0.999), `method` (`historical`, `parametric`, `cornish_fisher`), `window`, `minimum_acceptable_return`, `periods_per_year`. At most 5,000 observations. |
| `GET /api/health` | Liveness |

Invalid input gets a `422` with a message that says what is wrong.

## Static export

```bash
python -m examples.risk_dashboard.export -o risk_dashboard.html
```

writes a single HTML file, about 1 MB, that runs without a server. The results are calculated by the Python backend in
advance for every scenario, method and a grid of confidence levels and embedded in the page: nothing is calculated in the
browser, and a test checks that the embedded results equal what the backend returns. Uploading your own data needs the
server.

## Security notes

The page is served with a strict Content Security Policy (`default-src 'none'`, scripts and styles only from the same
origin), so it has no inline script or style and loads nothing from third parties. Text that comes from an uploaded file is
only ever inserted into the page as text, and the CSV export contains only numbers and dates that were validated as
`YYYY-MM-DD`. Request bodies are limited to 1 MB. The tests check the headers, the absence of inline code and of HTML
writing, and the body limit.
