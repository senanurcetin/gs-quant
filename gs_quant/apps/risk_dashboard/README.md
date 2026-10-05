# Risk analytics application

A web application on top of [`gs_quant.timeseries.risk_metrics`](../../timeseries/risk_metrics.py): value at risk, expected
shortfall and whether the VaR model can be trusted, for a simulated market, a CSV of your own returns or prices, or a
**portfolio** of several assets. Analyses can be saved, reopened and exported as stand-alone reports. It needs no Marquee
session.

```bash
pip install "gs-quant[app]"      # Starlette, Pydantic and uvicorn
gs-quant-risk                    # http://127.0.0.1:8000
```

or, from a checkout, `python -m gs_quant.apps.risk_dashboard`. It listens on `127.0.0.1` only unless you say otherwise
(see [Running it for other people](#running-it-for-other-people)).

## What it does

- **Risk at a glance**: annualized return and volatility, VaR and expected shortfall at the chosen confidence, maximum
  drawdown, Sortino, Calmar, skewness and excess kurtosis.
- **Model validation**: the Kupiec frequency test, the Christoffersen independence and conditional coverage tests and the
  Basel traffic light, with a plain-language verdict computed from the results. Each VaR forecast is made from the
  previous window only and compared with the return that followed (no look-ahead).
- **Portfolio**: upload a CSV with one column per asset (`date,A,B,C`, returns or prices, 2 to 10 assets), set the
  weights and the portfolio is analysed as above, held at constant weights and rebalanced every period. The page adds
  each asset's *share of volatility* and *share of expected shortfall* (Euler allocations, exact: they add up to 100%),
  the diversification ratio and the correlation matrix.
- **Market data** (opt in with `RISK_APP_MARKET_DATA`): load one symbol, or two to ten for a portfolio, straight from Stooq or
  Yahoo Finance. Prices are cached for 15 minutes, aligned on the dates all symbols traded, and analysed like an upload.
  Provider calls go to a fixed host with a size limit, a timeout and no redirects; symbols are validated first.
- **Stress**: the worst 1, 5 and 20 consecutive periods that actually occurred in the data, with their dates, how many
  times the VaR the worst period was and, for a portfolio, what each asset did over the same dates.
- **Saved analyses**: name an analysis and it is kept in a SQLite file. Opening it recomputes it, so it always reflects
  the current model code. Each one can be downloaded as a **report**: one HTML file with its charts and numbers that opens
  without a server, offline. Tick two to four saved analyses to compare them side by side (for instance a portfolio before
  and after a change of weights).
- **Charts**: growth and drawdown, daily returns against the VaR forecast with the breaches highlighted, the distribution
  with the normal fit and a QQ plot of the tails. Download the calculated series as CSV.

The sample scenarios are simulated (GARCH(1,1) with Student-t innovations). One of them, *Regime shift*, is a calm market
that turns turbulent, which a trailing-window VaR model is slow to notice.

## Configuration

Environment variables; a command line option overrides the matching one.

| Variable | Default | |
| --- | --- | --- |
| `RISK_APP_HOST` | `127.0.0.1` | Interface to bind to |
| `RISK_APP_PORT` | `8000` | |
| `RISK_APP_DATABASE` | `~/.local/share/gs-quant-risk/runs.db` | SQLite file of saved analyses, created on first save |
| `RISK_APP_API_TOKEN` | none | At least 16 characters. When set, every `/api/` endpoint except the probes needs `Authorization: Bearer <token>`, and the page asks for it |
| `RISK_APP_MAX_BODY_BYTES` | `1000000` | Largest request body |
| `RISK_APP_MAX_RUNS` | `200` | Saved analyses kept; the oldest are dropped |
| `RISK_APP_MARKET_DATA` | off | `stooq` or `yahoo`: lets the page load daily closing prices by symbol (`THYAO.IS`, `spy.us`). The server then needs outbound HTTPS to that provider |
| `RISK_APP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

## Running it for other people

Anyone who can reach the port can read and delete the saved analyses, so the application **refuses to listen on anything
but localhost without a token**:

```bash
export RISK_APP_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
gs-quant-risk serve --host 0.0.0.0
```

Put it behind a TLS terminating proxy: the token and the data travel in clear text otherwise. `--no-auth` overrides the
check for a network you trust.

### Docker

```bash
docker build -t gs-quant-risk .
docker run -p 8000:8000 -e RISK_APP_API_TOKEN=<16 or more characters> -v risk-data:/data gs-quant-risk
```

The image runs as an unprivileged user, keeps the saved analyses in the `/data` volume and has a health check on
`/api/health`. Without a token the container stops and says why.

### Operations

- `GET /api/health` is liveness and reports the version; `GET /api/ready` checks that the store can be opened (`503`
  otherwise). Neither needs the token.
- Every response carries an `X-Request-ID` (a sane one sent by the caller is kept). Each request is logged on one line
  with the method, path, status, duration and that id; query strings and bodies are never logged. An unexpected error is
  logged with its traceback and the caller gets a JSON `500` that holds the request id and nothing else.
- Saved analyses are the request only (compressed), so the database stays small; back it up by copying the file.

## API

| Endpoint | |
| --- | --- |
| `GET /api/config` | Limits, and whether a token is needed |
| `GET /api/market/prices?symbols=a,b&start=` | Closing prices by symbol from the configured provider (404 when none is configured); the answer can be sent as `prices` to `/api/analyze` or `/api/portfolio` |
| `GET /api/scenarios`, `GET /api/sample?scenario=&n=&seed=` | The sample scenarios and their simulated returns |
| `POST /api/analyze` | Body: `returns` or `prices`, optional `dates`, `confidence` (0.8 to 0.999), `method` (`historical`, `parametric`, `cornish_fisher`), `window`, `minimum_acceptable_return`, `periods_per_year`. At most 5,000 observations. |
| `POST /api/portfolio` | Body: `assets` (name to values), `kind` (`returns` or `prices`), optional `weights` (name to weight, equal weights if omitted, scaled to sum to 1) and the same settings. Answers like `/api/analyze` plus a `portfolio` section. |
| `GET /api/runs`, `POST /api/runs` | List the saved analyses; save one: `{name, kind: "single" or "portfolio", request}`, where `request` is the body of the matching analysis endpoint. The request is analysed first, so only valid ones are stored. |
| `GET /api/runs/compare?ids=a,b,c` | The headline figures of two to four saved analyses, recomputed, in the order asked for |
| `GET /api/runs/{id}`, `DELETE /api/runs/{id}` | Open (recomputed) or delete a saved analysis |
| `GET /api/runs/{id}/report` | The stand-alone HTML report, as a download |

Invalid input gets a `422` with a message that says what is wrong.

## Layout

| File | Purpose |
| --- | --- |
| `analysis.py` | Framework-free analysis: simulation, input validation and everything the page shows |
| `portfolio.py` | Portfolio returns and the decomposition of risk by asset |
| `store.py` | SQLite store of saved analyses |
| `settings.py` | Configuration from the environment |
| `app.py` | Starlette app: JSON API, static files, token check, request ids, security headers |
| `report.py`, `export.py`, `static_api.js` | The self-contained HTML report and the static demo export |
| `static/` | The page: `index.html`, `styles.css` and `app.js`. No framework, no third party code |
| `__main__.py` | The `gs-quant-risk` command |

Tests are in `gs_quant/test/apps`: `python -m pytest gs_quant/test/apps`. The browser test there needs Playwright and
Chromium and is skipped without them.

## Static export

```bash
gs-quant-risk export -o risk_dashboard.html
```

writes a single HTML file, about 1 MB, that runs without a server. The results are calculated by the Python backend in
advance for every scenario, method and a grid of confidence levels and embedded in the page: nothing is calculated in the
browser, and a test checks that the embedded results equal what the backend returns. Uploading your own data needs the
server.

## Security notes

The page is served with a strict Content Security Policy (`default-src 'none'`, scripts and styles only from the same
origin), so it has no inline script or style and loads nothing from third parties. Text that comes from an uploaded file,
an asset name or the name of a saved analysis is only ever inserted into the page as text. The report is the one document
with inline code: its policy allows exactly those script and style elements by SHA-256 hash, the data inside it cannot
close its script element, and its title is escaped. The token is compared in constant time and kept in `sessionStorage`
(this browser tab) only. The CSV export contains only numbers and dates that were validated as `YYYY-MM-DD`, and
spreadsheet formulas are neutralised. Request bodies are limited and counted as they are read, not trusted from the
`Content-Length` header. Saved analyses are fetched by a 32 character hexadecimal id only, so no path is ever built from
user input. The tests check the headers, the absence of inline code and of HTML writing, the body limit, the token and
the report policy.
