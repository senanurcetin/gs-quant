---
title: GS Quant Risk
emoji: 📈
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 8000
pinned: false
license: apache-2.0
short_description: Risk analytics dashboard built on GS Quant
---

# GS Quant Risk

Risk analytics application built on [GS Quant](https://github.com/senanurcetin/gs-quant).
The Space builds the repository's `Dockerfile` and serves the application on port 8000.

## Configuration

Set these under **Settings → Variables and secrets** of the Space:

| Name | Kind | Purpose |
| --- | --- | --- |
| `RISK_APP_API_TOKEN` | Secret | Required. At least 16 characters; the container stops without it. |
| `RISK_APP_MARKET_DATA` | Variable | Optional market data source (`yahoo`, or `off`). |

The run database lives in `/data/runs.db` and is lost when the Space restarts unless persistent storage is attached.
