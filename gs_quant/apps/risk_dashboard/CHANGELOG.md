# Changelog

The risk analytics application in `gs_quant/apps/risk_dashboard/`. Releases are tagged `release-X.Y.Z`; the notes of a
release are the section of that version below, and are published with it.

## [Unreleased]

### Fixed
- The exported dashboard (`gs-quant-risk export`) stopped at start-up in a browser, because a listener was attached to a
  form that the export removes. It now works, and a browser test opens it.

### Added
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
