# Downside and Tail Risk with `risk_metrics`

`gs_quant.timeseries.risk_metrics` computes risk statistics for any return or price series held in a pandas `Series`.
It needs **no Marquee session**, so it works offline and on data from any source.

```python
import numpy as np
import pandas as pd

from gs_quant.timeseries.risk_metrics import (
    VaRMethod,
    expected_shortfall,
    risk_summary,
    value_at_risk,
    var_backtest,
)

dates = pd.bdate_range('2022-01-03', periods=750)
daily_returns = pd.Series(np.random.default_rng(0).normal(0.0004, 0.01, 750), index=dates)
```

Import from `gs_quant.timeseries.risk_metrics` explicitly. It is deliberately **not** re-exported by
`gs_quant.timeseries`, because `sortino_ratio`, `calmar_ratio`, `tracking_error` and `information_ratio` already exist
there as report-based measures that take a portfolio report, not a series.

## Conventions

- Results are **fractions** (`0.02` is 2%), unlike `volatility()` which returns percent.
- A **loss is negative**. A 95% VaR of `-0.02` means a one period return worse than -2% is expected on 5% of periods.
- Inputs are *simple returns* unless the function says prices (`drawdown`, `ulcer_index`, `calmar_ratio` take prices).
- Rolling functions take `w` as an int, a relative date such as `'3m'`, or `Window(size, ramp)`. The default is the whole
  series (an expanding calculation). As elsewhere in the package, an int window is also the ramp up, so the first `w`
  results are dropped.
- Annualized measures infer the frequency from the dates (`252` daily, `52` weekly, `12` monthly). With an index that
  is not made of dates, pass `annualization_factor=`.

## Headline statistics in one call

```python
summary = risk_summary(daily_returns, confidence=0.95)

summary.annualized_volatility
summary.var_historical, summary.var_parametric, summary.var_cornish_fisher
summary.expected_shortfall_historical
summary.sortino_ratio, summary.max_drawdown, summary.calmar_ratio
summary.to_dict()  # JSON friendly: statistics that are undefined are None
```

## Value at risk and expected shortfall

```python
# rolling 1 year, 99% one day VaR, three ways
var_hist = value_at_risk(daily_returns, 0.99, VaRMethod.HISTORICAL, w=250)
var_norm = value_at_risk(daily_returns, 0.99, VaRMethod.PARAMETRIC, w=250)
var_cf = value_at_risk(daily_returns, 0.99, VaRMethod.CORNISH_FISHER, w=250)

es = expected_shortfall(daily_returns, 0.99, w=250)  # never better than VaR at the same confidence
```

Which method:

| Method | Use when |
| --- | --- |
| `HISTORICAL` | Default. Makes no distributional assumption, but is noisy in the far tail with short windows. |
| `PARAMETRIC` | Returns are close to normal, or you need a smooth estimate from little data. Understates fat tails. |
| `CORNISH_FISHER` | Returns are skewed or fat tailed, but only moderately so. Needs at least four observations per window. |

Expected shortfall supports `HISTORICAL` and `PARAMETRIC`. It is preferred over VaR when tail severity matters, as it
is a coherent risk measure.

## Backtesting a VaR model

A rolling VaR includes the return of the day it is stamped, so **lag it by one period** before comparing it with
returns, or the backtest is contaminated by look-ahead:

```python
forecast = value_at_risk(daily_returns, 0.99, VaRMethod.PARAMETRIC, w=250).shift(1)
result = var_backtest(daily_returns, forecast, confidence=0.99)

result.observations, result.exceedances, result.observed_rate
result.p_value  # small: the number of exceedances is unlikely if the model were calibrated
result.reject  # True if rejected at the 5% level
```

`var_backtest` is the Kupiec proportion of failures test. It rejects both too many exceedances (risk understated) and too
few (risk overstated). It checks the *count* only, not whether exceedances cluster in time.

## Other measures

```python
from gs_quant.timeseries.risk_metrics import (
    calmar_ratio,
    downside_deviation,
    drawdown,
    information_ratio,
    omega_ratio,
    sortino_ratio,
    tracking_error,
    ulcer_index,
)

prices = 100 * (1 + daily_returns).cumprod()
benchmark = pd.Series(np.random.default_rng(1).normal(0.0004, 0.01, 750), index=dates)

drawdown(prices)                        # fall from the running peak, <= 0
ulcer_index(prices, w='6m')             # root mean square drawdown
calmar_ratio(prices, w=250)             # annualized return / |max drawdown|
sortino_ratio(daily_returns, mar=0.0)   # excess return per unit of downside deviation
downside_deviation(daily_returns, mar=0.0)
omega_ratio(daily_returns, threshold=0.0)
tracking_error(daily_returns, benchmark)
information_ratio(daily_returns, benchmark, w=250)
```

Ratios are `NaN` where they are undefined, for example a Sortino ratio for a window with no return below the target.

## Common pitfalls

- **Passing prices where returns are expected.** `value_at_risk(prices)` silently computes the VaR *of the prices*.
  Convert first with `gs_quant.timeseries.econometrics.returns` or `prices.pct_change()`.
- **Comparing a percentage with a fraction.** `volatility()` is in percent, everything in this module is a fraction.
- **Mixing frequencies.** Annualization is inferred from the dates. Resample first if the series has irregular gaps.
- **Using a short window for a high confidence level.** A 99% historical VaR from 60 observations is determined by
  the worst one or two returns.

## Using it from an AI agent

The same analytics are exposed as MCP tools in `gs_quant.mcp.tools.analytics`, for callers that only have numbers:
`risk_summary_from_returns`, `backtest_value_at_risk`, `compare_with_benchmark`, and `asset_risk_summary`, which pulls
prices for a BBID from a Marquee dataset first. Enable them on a server with `--enable-tags analytics`.
