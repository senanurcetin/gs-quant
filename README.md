# GS Quant — risk analytics extension (Senanur Cetin fork)

This repository is a **fork of Goldman Sachs' open-source GS Quant library**, with an independently developed risk-analysis application and supporting tools. The GS Quant library itself is upstream work by Goldman Sachs; the additions described below belong to this fork. The original library introduction is preserved further down.

## What this fork adds

- **Risk calculations:** historical, parametric and Cornish–Fisher Value at Risk (VaR), expected shortfall, drawdown and risk-adjusted performance metrics in [`gs_quant/timeseries/risk_metrics.py`](gs_quant/timeseries/risk_metrics.py).
- **Model validation:** rolling and EWMA VaR backtests, Kupiec and Christoffersen coverage tests, Basel traffic-light analysis, and an explicit check of square-root-of-time scaling.
- **Usable application:** an installable [risk dashboard](gs_quant/apps/risk_dashboard/README.md) with a simulated-data walkthrough, CSV and portfolio analyses, scenarios, benchmarks, saved analyses, Excel/HTML exports, Turkish and English interfaces, and automated tests.
- **Agent-facing analytics:** risk calculation tools integrated into the existing MCP server, using the same underlying metrics as the app.

## Results, with their limits

In a **simulated** 1,000-period regime-shift series, 250-period rolling 95% VaR was breached **63 times** versus **37.5 expected**; the EWMA estimate was breached **41 times**. Over 75 non-overlapping ten-period windows, a square-root-of-time estimate was breached 8 times versus 3.75 expected. These examples demonstrate validation behavior; **they are not results from a real trading portfolio**. See the [application documentation](gs_quant/apps/risk_dashboard/README.md) for assumptions, reproducibility and limitations.

## Review the implementation

| Resource | Link |
| --- | --- |
| Portfolio case study | [GS Quant Risk Analytics](https://senanur-cetin.vercel.app/projects/gs-quant-risk-analytics) |
| Live static demonstration | [GitHub Pages](https://senanurcetin.github.io/gs-quant/) |
| Hugging Face demo | [GS Quant Risk](https://huggingface.co/spaces/senanurcetin/gs-quant-risk) |
| Installation and usage | [Risk dashboard README](gs_quant/apps/risk_dashboard/README.md) |
| Release notes and changes | [CHANGELOG](gs_quant/apps/risk_dashboard/CHANGELOG.md) |
| Tagged release | [0.1.1](https://github.com/senanurcetin/gs-quant/releases/tag/release-0.1.1) |

Install the **fork**, rather than expecting these extensions in upstream PyPI `gs-quant`:

```bash
git clone https://github.com/senanurcetin/gs-quant.git
cd gs-quant
python -m venv .venv
# Activate the virtual environment for your platform
python -m pip install -e ".[app]"
python -m gs_quant.apps.risk_dashboard
```

The app listens on localhost by default. Review the [security and deployment guidance](gs_quant/apps/risk_dashboard/README.md) before exposing it on a network.

---

## Upstream library (Goldman Sachs)

# GS Quant

**GS Quant** is a Python toolkit for quantitative finance, created on top of one of the world’s most powerful risk transfer platforms. Designed to accelerate development of quantitative trading strategies and risk management solutions, crafted over 25 years of experience navigating global markets.

It is created and maintained by quantitative developers (quants) at Goldman Sachs to enable the development of trading strategies and analysis of derivative products. GS Quant can be used to facilitate derivative structuring, trading, and risk management, or as a set of statistical packages for data analytics applications.

In order to access the APIs you will need a client id and secret.  These are available to institutional clients of Goldman Sachs.  Please speak to your sales coverage or Marquee Sales for further information. 

Please refer to [Goldman Sachs Developer](https://developer.gs.com/docs/gsquant/) for additional information.

## Requirements

* Python 3.10 or greater
* Access to PIP package manager

## Installation

```
pip install gs-quant
```

## Examples

You can find examples, guides and tutorials in the respective folders on [Goldman Sachs Developer](https://developer.gs.com/docs/gsquant/).


## Help

Please reach out to `gs-quant@gs.com` with any questions, comments or feedback.
