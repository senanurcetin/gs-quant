/*
 * Stand-in for the server API in the static export: every result was computed by the Python backend in advance and
 * embedded in the page as window.__RISK_DATA__. Nothing is calculated in the browser.
 */
(() => {
  'use strict';
  const data = window.__RISK_DATA__;
  const key = (confidence, method) => `${confidence}|${method}`;

  window.RiskApi = {
    staticMode: true,
    confidences: data.confidences,
    window: data.window,
    async scenarios() {
      return data.scenarios;
    },
    async loadScenario(id, title) {
      return { id, title, simulated: true, kind: 'returns' };
    },
    async analyze(dataset, settings) {
      const scenario = data.data[dataset.id];
      const variant = scenario && scenario.variants[key(settings.confidence, settings.method)];
      if (!variant) throw new Error('No precomputed result for these settings.');
      return {
        summary: variant.summary,
        backtest: variant.backtest,
        settings: variant.settings,
        histogram: scenario.shared.histogram,
        qq: scenario.shared.qq,
        worst_drawdown: scenario.shared.worst_drawdown,
        assumptions: variant.assumptions,
        conventions: scenario.shared.conventions,
        series: {
          dates: scenario.shared.dates,
          returns: scenario.shared.returns,
          growth: scenario.shared.growth,
          drawdown: scenario.shared.drawdown,
          var: variant.var,
          expected_shortfall: variant.expected_shortfall,
          breach: variant.breach,
        },
      };
    },
  };
})();
