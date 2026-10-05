---
title: GS Quant Risk
emoji: 📈
colorFrom: blue
colorTo: gray
sdk: static
app_file: index.html
pinned: false
license: apache-2.0
short_description: Value at risk, expected shortfall and model validation
---

# GS Quant Risk: live demo

The risk analytics dashboard built on [GS Quant](https://github.com/senanurcetin/gs-quant), exported as one page that
runs in the browser without a server. It shows value at risk, expected shortfall and model validation for three simulated
scenarios (calm market, volatile market, regime shift), in English and Turkish.

Every result was calculated in advance by the Python code (`gs_quant.timeseries.risk_metrics`) and is embedded in the
page. It uses simulated data only and stores nothing; uploading your own prices or portfolio needs the server.

## Run the full application

```bash
docker run -p 8000:8000 -e RISK_APP_API_TOKEN=<16 or more characters> -v risk-data:/data \
  ghcr.io/senanurcetin/gs-quant-risk:latest
```

or `pip install "gs-quant[app]"` and `gs-quant-risk serve`. Source, documentation and deployment files:
https://github.com/senanurcetin/gs-quant
