# Changelog

The risk analytics application in `gs_quant/apps/risk_dashboard/`. Releases are tagged `release-X.Y.Z`; the notes of a
release are the section of that version below, and are published with it.

## [Unreleased]

### Changed
- Turkish: "Growth of 100" reads naturally ("100 birimlik yatırımın değeri"), and the Christoffersen test is named as a test.
  `TR_TERMS.md` lists the finance terms of the Turkish interface and the ones that need a finance reader's decision.

### Fixed
- The exported dashboard (`gs-quant-risk export`) stopped at start-up in a browser, because a listener was attached to a
  form that the export removes. It now works, and a browser test opens it.

### Added
- Benchmark for a single series and in CSV files (a third column, or a column headed Benchmark), up and down capture
  ratios, and a rolling beta chart.
- Horizon method: filtered historical simulation as an alternative to the square-root rule, a multi-period check of the
  square-root figures over non-overlapping stretches, and a setting for the EWMA decay.
- Saved copies of prices: if the market data provider cannot be reached, the latest prices fetched are used, and the notes of
  the analysis say so with their date (database version 3).
- `gs-quant-risk check-portfolio`: a whole analysis on live data, step by step, to run on the machine that serves the
  application.
- A live demo on GitHub Pages: the exported dashboard with simulated data, rebuilt when the application changes.

## [0.1.0] - 2026-10-05

First release.

### Analysis
- Value at risk (historical, parametric, Cornish-Fisher) and expected shortfall over a rolling window, with Kupiec,
  Christoffersen independence and conditional coverage tests and the Basel traffic light. Each forecast is judged on the
  return that followed it.
- Multi-period horizon by the square-root-of-time rule, with its assumptions stated in the notes.
- An exponentially weighted (EWMA) volatility and a normal VaR from it, backtested over the same periods as the rolling
  window.
- Portfolios of two to ten assets at constant weights: Euler shares of volatility and of expected shortfall,
  diversification ratio, correlation matrix.
- Benchmark statistics for a portfolio: beta, correlation, R-squared, alpha, active return, tracking error, information
  ratio.
- Stress windows (worst 1, 5 and 20 periods) and what-if scenarios with shocks of your own.

### Data
- Daily closes by symbol from Yahoo Finance, adjusted, cached for 15 minutes, with a `check-data` command to test a
  provider from the machine that will serve the application.
- Symbols quoted in different currencies are converted into one, at the daily exchange rate.
- CSV upload of returns or prices; simulated sample scenarios.

### Application
- Saved analyses and named portfolios in a SQLite file with versioned migrations and a backup before each one.
- Side-by-side comparison of two to four saved analyses.
- Stand-alone HTML reports, Excel workbooks, and a print stylesheet for PDF.
- English and Turkish interface, Turkish number format.

### Operations
- Optional bearer token (required when listening beyond localhost), rate limit and lockout after failed attempts,
  security headers with a strict Content-Security-Policy, health and readiness probes.
- Docker image, Docker Compose with Caddy for HTTPS, and a systemd unit.
