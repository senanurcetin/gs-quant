# Risk analytics application

A web application on top of [`gs_quant.timeseries.risk_metrics`](../../timeseries/risk_metrics.py): value at risk, expected
shortfall and whether the VaR model can be trusted, for a simulated market, a CSV of your own returns or prices, or a
**portfolio** of several assets. Analyses can be saved, reopened and exported as stand-alone reports. It needs no Marquee
session. [Try the live demo](https://senanurcetin.github.io/gs-quant/) (simulated data, no server).

The application is part of this repository and is not on PyPI (`pip install gs-quant` installs Goldman Sachs' original
package, which does not have it). Install it from a checkout, in a virtual environment (Python 3.10 to 3.13):

```bash
git clone https://github.com/senanurcetin/gs-quant.git
cd gs-quant
python -m venv .venv
.venv/bin/pip install -e ".[app]"     # Windows: .venv\Scripts\pip install -e ".[app]"
.venv/bin/gs-quant-risk               # Windows: .venv\Scripts\gs-quant-risk   (http://127.0.0.1:8000)
```

A tagged release can also be installed without cloning, straight from the repository, or run as a container from
[the published image](#docker) (versions are listed in [`CHANGELOG.md`](CHANGELOG.md)):

```bash
pip install "gs-quant[app] @ git+https://github.com/senanurcetin/gs-quant@release-0.1.0"
docker run -p 8000:8000 -e RISK_APP_API_TOKEN=<16 or more characters> -v risk-data:/data ghcr.io/senanurcetin/gs-quant-risk:0.1.0
```

`python -m gs_quant.apps.risk_dashboard` does the same without needing the `Scripts` folder on the `PATH`, which is the usual
reason a freshly installed command is "not recognized" on Windows. It listens on `127.0.0.1` only unless you say otherwise
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
- **Market data**: load one symbol, or two to ten for a portfolio, from Yahoo Finance by symbol (`AAPL`, `^GSPC`,
  `THYAO.IS` for Borsa Istanbul). Daily closes adjusted for splits and dividends, up to ten years. Prices are cached for
  15 minutes, aligned on the dates all symbols traded, and analysed like an upload. A throttled request (429) is repeated
  once. Provider calls go to a fixed host with a size limit, a timeout and no redirects; symbols are validated first.
  **Currencies**: a portfolio's returns must be in one currency, so symbols quoted in different currencies (`THYAO.IS` in
  TRY, `AAPL` in USD) are converted at Yahoo's daily exchange rate (e.g. `USDTRY=X`, or the inverse pair; the last rate
  is carried over holidays for up to five days) into the currency you pick, or by default into the first symbol's. The
  converted returns are those of an investor holding in that currency, exchange rate moves included. Pence-quoted
  prices (`GBp`, London) are turned into pounds first. `base=TRY` on the API does the same. The conversion is stated in
  the notes of the analysis. Not covered: holiday calendars differ between markets, so only dates on which every symbol
  traded are used.
  **Saved copies**: the latest prices of every symbol fetched are also kept in the database (the `prices` table, at most 300
  symbols, the least recently fetched dropped first). If the provider cannot be reached (a timeout, a 429 or 5xx, not an
  unknown symbol) the saved copy is used instead, for the next minute at a time so a provider that is down is not asked at
  every request, and the page says so in the notes of the analysis, with the date of the copy: *Prices of AAPL come from
  the copy saved on 2026-10-05 because Yahoo Finance could not be reached: they may be out of date*. A copy is never used
  for a symbol the provider says it does not know. `/api/market/prices` lists them under `stale`.
  Daily closes only: there are no intraday or real-time prices. Switch it off with `RISK_APP_MARKET_DATA=off`.
- **Horizon**: the *Horizon* setting (1 to 60 periods) adds the multi-period VaR and expected shortfall to the headline.
  They are the one-period figures times the square root of the horizon, capped at a loss of 100%. That rule is an
  approximation that assumes independent returns and no drift: it understates the risk when returns trend or when
  volatility clusters. The assumption is stated in the notes of the analysis whenever the horizon is more than one period.
  The **horizon method** can instead be a *filtered simulation* (filtered historical simulation): each return is divided by
  the EWMA volatility forecast made before it, 10,000 paths are simulated from today's volatility by drawing those
  standardised returns and moving the volatility on with the EWMA recursion, and the figures are the quantile and the tail
  mean of the compounded paths. It follows the current market where the square-root rule, which scales a figure from a long
  window, lags (on the *Regime shift* sample the 10-period 95% VaR is 12.0% by simulation against 4.9% by the rule), and
  keeps the fat tails of the history. It is an approximation too, with zero mean, and uses a fixed seed so that the same
  analysis gives the same figures. For the square-root rule the page also shows a **multi-period check**: the figures
  against what happened over stretches of the horizon that do not overlap (overlapping ones share returns and break the
  independence the Kupiec test needs), judged against the one-period VaR known just before each stretch times the square
  root of the horizon. It needs at least 20 stretches; on the same sample it rejects the rule (8 breaches in 75 stretches, 3.75
  expected). The **EWMA decay** (0.80 to 0.99, 0.94 by default) is a setting.
- **Rolling window against a filtered estimate**: next to the rolling-window figures, the page shows an exponentially
  weighted (EWMA, RiskMetrics decay 0.94, zero mean) volatility, a normal VaR from it, and how that VaR fared against the
  periods that followed (Kupiec test over the same periods as the rolling estimate). The filtered line is drawn on the VaR
  chart. It reacts faster than a long window: on the *Regime shift* sample (1,000 periods, seed 7) the 250-period rolling VaR at
  95% is breached 63 times and the filtered one 41 times, against 37.5 expected. The table also says whether recent periods
  were calmer or more turbulent than the window as a whole.
- **Benchmark**: a benchmark symbol (`XU100.IS`, `^GSPC`), for one symbol or for a portfolio loaded by symbol, adds beta, correlation,
  R-squared, annualized alpha, active return, tracking error and the information ratio against it, the **up and down
  capture ratios** (the average return over the periods the benchmark rose, and over those it fell, against the
  benchmark's own: more than 100% on the way up and less on the way down is the way round to want; needs five such
  periods) and a **rolling beta** chart (the beta over the analysis window, at each date, against the whole-history beta).
  It also works with files: a dated CSV with a third column (`date,value,Index`) compares the series with that column, and a
  portfolio CSV with a column headed `Benchmark` (or `Kıyas`) compares the portfolio with it, the column not being an asset. Beta
  is the covariance with the benchmark over its variance, over the periods both have; the benchmark is converted to the
  same currency as the assets. The API takes `benchmark` (values of the same kind and on the same dates as the data, in `/api/analyze` and in
  `/api/portfolio`) and `benchmark_name`. A named portfolio keeps its benchmark symbol.
- **Turkish and English**: the page opens in the language of the browser and the button in the header switches it (the
  choice is remembered in the browser). Turkish writes numbers its own way: a decimal comma and the percent sign in front,
  `−%0,92`. Assumptions and the usual error messages that come from the server are translated by the page too; a message it
  does not know stays in English. The texts are in `static/i18n.js`: the page is written in English and a test checks that
  every text has a Turkish translation with the same placeholders. To add a language, add a table there.
- **Stress**: the worst 1, 5 and 20 consecutive periods that actually occurred in the data, with their dates, how many
  times the VaR the worst period was and, for a portfolio, what each asset did over the same dates.
- **What if**: up to five scenarios of your own, each saying how much every asset moves at once in percent (`-10` is a
  fall of 10%; an asset left at 0 stays put; for a single series, one shock). The effect on the portfolio is the weighted
  sum at its weights, shown beside how many times the VaR and the expected shortfall that is. It is a first-order answer,
  made in the same way for any asset: no betas or correlations are assumed, so a "market falls 10%" scenario means entering
  the fall of each asset yourself. Scenarios are saved with the analysis and appear, read-only, in its report.
- **My portfolios**: a portfolio loaded by symbol can be saved under a name (symbols, weights, benchmark, currency and the
  length of history, not the prices). Opening one fetches fresh prices and applies the saved weights, so the same portfolio can be
  looked at again next month without typing it. Saving under an existing name (case ignored) replaces it. Portfolios from an
  uploaded CSV have no symbols and cannot be saved this way: save the analysis instead.
- **Saved analyses**: name an analysis and it is kept in a SQLite file. Opening it recomputes it, so it always reflects
  the current model code. Each one can be downloaded as a **report**: one HTML file with its charts and numbers that opens
  without a server, offline. Tick two to four saved analyses to compare them side by side (for instance a portfolio before
  and after a change of weights).
- **Excel and PDF**: a saved analysis can be downloaded as an Excel workbook (`GET /api/runs/{id}/xlsx`): a Summary
  sheet (headline, horizon, filtered estimate, settings and notes), Backtest, Series (one row per period), Stress and,
  where they apply, Portfolio, What-if and Benchmark. Figures are numbers with a percent or ratio format, not text, so they
  can be used in formulas; text that starts with `=`, `+`, `-` or `@` (an asset or run name) is stored as text and never
  becomes a formula. *Print or save as PDF* uses the browser's print dialog: the page has a print stylesheet (A4, light
  colours whatever the screen theme, controls hidden, sections kept whole), and the offline HTML report prints the same way.
  No server-side PDF library is used, so the image stays small. The workbook is in English whatever the page language.
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
| `RISK_APP_MARKET_DATA` | `yahoo` | Where the page can load daily prices by symbol (`THYAO.IS`, `AAPL`): `yahoo`, `stooq` or `off`. Needs outbound HTTPS to that provider. Stooq now asks for an API key and does not work at present |
| `RISK_APP_MAX_PORTFOLIOS` | `50` | Named portfolios kept; saving one more is refused (they are never dropped silently) |
| `RISK_APP_RATE_LIMIT` | `600` | Requests per minute from one caller to `/api/`; more get a `429` with `Retry-After`. `0` for no limit. The page itself makes a few requests per second while a slider is dragged |
| `RISK_APP_MAX_AUTH_FAILURES` | `10` | Wrong or missing tokens from one caller within the lockout time before it is locked out (`429`, even for the right token). `0` for never |
| `RISK_APP_LOCKOUT_SECONDS` | `300` | How long the failures count, and so how long a lockout lasts |
| `RISK_APP_TRUST_PROXY` | off | Take the caller's address from `X-Forwarded-For`: only behind a reverse proxy |
| `RISK_APP_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR` |

## Running it for other people

Anyone who can reach the port can read and delete the saved analyses, so the application **refuses to listen on anything
but localhost without a token**:

```bash
export RISK_APP_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
gs-quant-risk serve --host 0.0.0.0
```

The token and the data travel in clear text without TLS, so put it behind a reverse proxy that serves HTTPS and tell the
application to trust it (`RISK_APP_TRUST_PROXY=1`, so that the address of each caller is the one the proxy saw, which the
rate limit and the lockout below depend on). Only set that when the application cannot be reached except through the
proxy: otherwise a caller could write the header itself. The last address in `X-Forwarded-For` is the one used, as that is
the one the proxy wrote. `--no-auth` overrides the token check for a network you trust.

`deploy/` has what is needed: `docker-compose.yml` runs the application and Caddy (which obtains and renews a certificate
for your domain by itself), `Caddyfile`, and `gs-quant-risk.service` for running without Docker. For nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;   # adds the caller's address at the end
    client_max_body_size 1m;
}
```

The files in `deploy/` have not been run end to end by the author: the compose file and the unit are checked for syntax
only, so try them on a test machine first.

### Docker

```bash
docker run -p 8000:8000 -e RISK_APP_API_TOKEN=<16 or more characters> -v risk-data:/data \
    ghcr.io/senanurcetin/gs-quant-risk:0.1.0           # a published release: 0.1.0, 0.1 or latest
docker build -t gs-quant-risk . && docker run ...      # or build it from a checkout
```

`deploy/docker-compose.image.yml` runs the published image behind Caddy without a checkout of the repository (it and the
`Caddyfile` are all that is needed). An image built from a checkout reports the version `0+unknown`; a release build is
given the version (`--build-arg VERSION=1.2.3`) and `/api/health` reports it.

**Releasing** (for the maintainer): add a section `## [X.Y.Z] - date` to `CHANGELOG.md`, merge it, then push the tag
`release-X.Y.Z`. The workflow `.github/workflows/release.yml` runs the checks of the CI, builds the image with that
version, starts it once to check what it reports, pushes it to `ghcr.io` as `X.Y.Z`, `X.Y` and `latest`, and creates the
GitHub release with the notes of that section. It has not been run yet: the first tag is its first test, and the package
must be made public once in the repository's package settings for others to pull it without logging in.

The image runs as an unprivileged user, keeps the saved analyses in the `/data` volume and has a health check on
`/api/health`. Without a token the container stops and says why.

### Operations

- `GET /api/health` is liveness and reports the version; `GET /api/ready` checks that the store can be opened (`503`
  otherwise). Neither needs the token.
- Every response carries an `X-Request-ID` (a sane one sent by the caller is kept). Each request is logged on one line
  with the method, path, status, duration and that id; query strings and bodies are never logged. An unexpected error is
  logged with its traceback and the caller gets a JSON `500` that holds the request id and nothing else.
- Saved analyses are the request only (compressed), so the database stays small; back it up by copying the file.
- The database has a version (SQLite's `user_version`). When a release needs a change to the tables, the file is copied
  aside first (`runs.db.bak-v0`, named after the version it had) and then brought up one step at a time, all or nothing, so
  a failed upgrade leaves the data as it was. A database written by a **newer** release is refused, not touched: the
  application says so at start and exits. `GET /api/ready` reports the version.
- At start the database is opened before anything is served, so a file that cannot be used (a directory that cannot be
  created, a newer version) is reported then, not at the first request.
- Limits per caller: the request rate, and a lockout after repeated wrong tokens (a log line says who was locked out).
  What is remembered about callers is bounded, so it cannot be used to fill the memory.

### Checking the market data providers

```bash
python -m gs_quant.apps.risk_dashboard check-data                      # both providers, AAPL
python -m gs_quant.apps.risk_dashboard check-data --provider yahoo --symbol THYAO.IS
python -m gs_quant.apps.risk_dashboard check-data --provider yahoo --symbol USDTRY=X     # an exchange rate
```

fetches one symbol from the real service and prints what came back (number of daily closes, first and last date, last
close), or why it failed. It exits with status 1 if any provider failed, so it also serves as a deployment check. Run it
from the machine that will serve the application: a provider can answer from one network and refuse from another (a
cloud server may be treated differently from a home connection, and Yahoo answers 429 to clients that ask too often).

`gs-quant-risk check-portfolio` goes further: it runs a whole analysis on live data (several symbols quoted in different
currencies, converted into one, with a benchmark) and prints what each step produced: the dates in common, which exchange
rate converted which symbol, the volatility and VaR, each asset's share of the risk, the beta and tracking error. It warns
about what looks wrong (a one-day move of more than 25% is probably a missed split, a short history, a benchmark that does
not move with the portfolio) and exits with status 1 if a step fails. Defaults are `THYAO.IS,GARAN.IS,AAPL` against
`XU100.IS` in TRY over three years; change them with `--symbols`, `--benchmark` (`none` for no benchmark), `--base` (`auto`
to follow the first symbol) and `--years` (`0` for all). Run it on the machine that will serve the application and read the
output once: the tests of this repository use a provider that answers from memory, so this is what checks the real thing.

Checked against the live services from a Windows PC: Yahoo Finance returned ten years of daily closes for `AAPL` and
`THYAO.IS`; Stooq answered that it needs an API key, which this application does not support. Intraday and real-time
prices are not covered, both sources being used for daily closes.

## API

| Endpoint | |
| --- | --- |
| `GET /api/config` | Limits, and whether a token is needed |
| `GET /api/market/prices?symbols=a,b&start=&base=` | Closing prices by symbol from the configured provider (404 when none is configured); the answer can be sent as `prices` to `/api/analyze` or `/api/portfolio` |
| `GET /api/scenarios`, `GET /api/sample?scenario=&n=&seed=` | The sample scenarios and their simulated returns |
| `POST /api/analyze` | Body: `returns` or `prices`, optional `dates`, `benchmark` and `benchmark_name`, `scenarios` (a list of `{name, shocks}`, shocks by asset name as fractions, `series` for a single series; at most five), `confidence` (0.8 to 0.999), `method` (`historical`, `parametric`, `cornish_fisher`), `window`, `horizon` (1 to 60), `minimum_acceptable_return`, `periods_per_year`. At most 5,000 observations. |
| `POST /api/portfolio` | Body: `assets` (name to values), `kind` (`returns` or `prices`), optional `weights` (name to weight, equal weights if omitted, scaled to sum to 1), optional `benchmark` and `benchmark_name`, and the same settings. Answers like `/api/analyze` plus a `portfolio` section (and `benchmark` when one was given). |
| `GET /api/portfolios`, `POST /api/portfolios` | List the named portfolios; keep one, `{name, symbols, weights, base, years}` (2 to 10 symbols, weights for exactly those, `years` 1, 3, 5, 10 or null for all). A name that exists is replaced (`200`, else `201`); beyond the limit `409` |
| `GET /api/portfolios/{id}`, `DELETE /api/portfolios/{id}` | The definition of one, or delete it |
| `GET /api/runs`, `POST /api/runs` | List the saved analyses; save one: `{name, kind: "single" or "portfolio", request}`, where `request` is the body of the matching analysis endpoint. The request is analysed first, so only valid ones are stored. |
| `GET /api/runs/compare?ids=a,b,c` | The headline figures of two to four saved analyses, recomputed, in the order asked for |
| `GET /api/runs/{id}`, `DELETE /api/runs/{id}` | Open (recomputed) or delete a saved analysis |
| `GET /api/runs/{id}/xlsx` | The saved run as an Excel workbook (recomputed, like the report) |
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
| `static/` | The page: `index.html`, `styles.css`, `app.js` and the translations in `i18n.js`. No framework, no third party code |
| `__main__.py` | The `gs-quant-risk` command |

**Accessibility** is checked in a real browser with axe-core (`axe-playwright-python`): the rules of WCAG 2 A and AA and its
best practices, including colour contrast, over a series, a portfolio with a what-if scenario, the filtered estimate and the
multi-period check, in light and dark themes, in English and in Turkish, and on a phone-sized screen (which also must not
scroll sideways). The test found two things that are fixed: a section whose landmark name repeated that of its table, and a table column
of buttons with no heading for a screen reader. It does not replace a person using a screen reader, which I have not done.
**Dependencies and image**: `.github/dependabot.yml` asks for a pull request a week, at most three, for the actions and for the
Python packages, grouped; the CI scans the image with Trivy and lists high and critical findings that have a fix, without
failing the build (a finding in the base image is for you to weigh, not to be hidden by a red build).

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

### Live demo

The same file is published on GitHub Pages: **https://senanurcetin.github.io/gs-quant/**. It uses simulated data only (three
sample scenarios, the confidence levels and methods of the export, English and Turkish) and does not store anything: it
cannot load prices, take a CSV, save an analysis or analyse a portfolio, which need the server. It is rebuilt by
`.github/workflows/pages.yml` when the application changes; for that to work, set *Settings, Pages, Source* to *GitHub
Actions* once.

The demo is also published as a free static Space on Hugging Face: **https://huggingface.co/spaces/senanurcetin/gs-quant-risk**
(the same export). A Docker Space for the server itself needs a Hugging Face PRO subscription, so the Space carries the
demo only. `deploy/huggingface/publish.sh` builds the export and pushes it with the Space card
(`HF_TOKEN=<write token> deploy/huggingface/publish.sh`).

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
