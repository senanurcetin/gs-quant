/*
 * Risk Analytics Dashboard: front end.
 * Copyright 2026 Senanur Çetin. Licensed under the Apache License, Version 2.0.
 *
 * No framework and no third party code: charts are drawn as SVG at the pixel width of their container, so text stays
 * legible on small screens. The page is served with a strict Content Security Policy (no inline script or style), and
 * text that came from a file is only ever inserted as text.
 */
(() => {
  'use strict';

  const { t } = window.I18n;
  const isTurkish = () => window.I18n.lang === 'tr';
  const SVG_NS = 'http://www.w3.org/2000/svg';
  const MAX_ROWS = 5000;
  const MINUS = '−';
  const DASH = '—';
  const methodHint = (method) =>
    ({
      historical: t('The empirical quantile of the window. No distribution assumed; noisy in the far tail.'),
      parametric: t('A normal distribution fitted to the window. Smooth, but understates fat tails.'),
      cornish_fisher: t('A normal quantile corrected for skewness and kurtosis. Suits moderately fat tails.'),
    })[method];
  const methodName = (method) => ({ historical: t('historical'), parametric: t('parametric'), cornish_fisher: 'Cornish-Fisher' })[method] || method;

  const $ = (selector) => document.querySelector(selector);

  // ------------------------------------------------------------------------------------------------------------------
  // API. The static export replaces this with precomputed results by defining window.RiskApi.
  // ------------------------------------------------------------------------------------------------------------------

  const TOKEN_KEY = 'risk-app-token';
  let token = '';
  try {
    token = sessionStorage.getItem(TOKEN_KEY) || '';
  } catch (error) {
    /* storage can be unavailable (private windows, blocked cookies): the token then lives in memory only */
  }

  function setToken(value) {
    token = value;
    try {
      if (value) sessionStorage.setItem(TOKEN_KEY, value);
      else sessionStorage.removeItem(TOKEN_KEY);
    } catch (error) {
      /* see above */
    }
  }

  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.status = status;
    }
  }

  async function request(url, options = {}) {
    const headers = { ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    let response;
    try {
      response = await fetch(url, { ...options, headers });
    } catch (error) {
      throw new ApiError(t('Could not reach the server. Is it still running?'), 0);
    }
    if (!response.ok) {
      let payload = null;
      try {
        payload = await response.json();
      } catch (error) {
        /* not JSON */
      }
      const fallback = response.status === 401 ? t('A valid access token is required.') : t('The server answered with status {status}', { status: response.status });
      throw new ApiError(window.I18n.server((payload && payload.error) || fallback), response.status);
    }
    return response;
  }

  async function requestJson(url, options) {
    const response = await request(url, options);
    return response.status === 204 ? null : response.json();
  }

  const jsonBody = (body) => ({ headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

  // What the server is sent for a dataset and the model settings: the same body is analysed and saved
  function requestBody(dataset, settings) {
    const body = { confidence: settings.confidence, method: settings.method, window: settings.window };
    if (dataset.portfolio) {
      body.assets = dataset.assets;
      body.kind = dataset.kind;
      if (dataset.weights) body.weights = dataset.weights;
    } else {
      body[dataset.kind] = dataset.values;
    }
    if (dataset.dates) body.dates = dataset.dates;
    if (dataset.scenarios && dataset.scenarios.length) body.scenarios = dataset.scenarios.map(({ name, shocks }) => ({ name, shocks }));
    return body;
  }

  const liveApi = {
    staticMode: false,
    config: () => requestJson('/api/config'),
    scenarios: () => requestJson('/api/scenarios'),
    async loadScenario(id, title, seed) {
      const sample = await requestJson(`/api/sample?scenario=${encodeURIComponent(id)}${seed ? `&seed=${seed}` : ''}`);
      return { id, title, simulated: true, kind: 'returns', dates: sample.dates, values: sample.returns };
    },
    analyze(dataset, settings) {
      return requestJson(dataset.portfolio ? '/api/portfolio' : '/api/analyze', {
        method: 'POST',
        ...jsonBody(requestBody(dataset, settings)),
      });
    },
    listRuns: () => requestJson('/api/runs'),
    saveRun: (name, dataset, settings) =>
      requestJson('/api/runs', {
        method: 'POST',
        ...jsonBody({ name, kind: dataset.portfolio ? 'portfolio' : 'single', request: requestBody(dataset, settings) }),
      }),
    openRun: (id) => requestJson(`/api/runs/${id}`),
    marketPrices: (symbols, start, base) =>
      requestJson(`/api/market/prices?symbols=${encodeURIComponent(symbols.join(','))}${start ? `&start=${start}` : ''}${base ? `&base=${base}` : ''}`),
    compareRuns: (ids) => requestJson(`/api/runs/compare?ids=${ids.join(',')}`),
    deleteRun: (id) => requestJson(`/api/runs/${id}`, { method: 'DELETE' }),
    async reportBlob(id) {
      return (await request(`/api/runs/${id}/report`)).blob();
    },
  };
  const api = window.RiskApi || liveApi;

  // ------------------------------------------------------------------------------------------------------------------
  // Formatting: one convention throughout. Percentages to two decimals, ratios to two, a true minus sign.
  // ------------------------------------------------------------------------------------------------------------------

  const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
  const signed = (text) => text.replace(/^-(0\.0+)$/, '$1').replace('-', MINUS);
  // Turkish writes a decimal comma and puts the percent sign in front of the number: −%0,92
  const decimal = (text) => (isTurkish() ? text.replace('.', ',') : text);
  const percentText = (value, digits) => {
    const text = signed(value.toFixed(digits));
    if (!isTurkish()) return `${text}%`;
    const negative = text.startsWith(MINUS);
    return `${negative ? MINUS : ''}%${decimal(negative ? text.slice(1) : text)}`;
  };
  const pct = (v, digits = 2) => (isNumber(v) ? percentText(v * 100, digits) : DASH);
  const num = (v, digits = 2) => (isNumber(v) ? decimal(signed(v.toFixed(digits))) : DASH);
  const pValue = (p) => (p < 0.001 ? decimal('<0.001') : decimal(p.toFixed(3)));
  const confidenceLabel = (c) => percentText(c * 100, 1);
  const integer = (v) => Math.round(v).toLocaleString(isTurkish() ? 'tr-TR' : 'en-US');

  function element(tag, { className, text, attributes } = {}, children = []) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    for (const [key, value] of Object.entries(attributes || {})) node.setAttribute(key, value);
    for (const child of children) node.append(child);
    return node;
  }

  // ------------------------------------------------------------------------------------------------------------------
  // SVG helpers
  // ------------------------------------------------------------------------------------------------------------------

  function svgEl(name, attributes = {}, text) {
    const node = document.createElementNS(SVG_NS, name);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function linearScale(domainMin, domainMax, rangeMin, rangeMax) {
    const span = domainMax - domainMin || 1;
    return (v) => rangeMin + ((v - domainMin) / span) * (rangeMax - rangeMin);
  }

  function niceStep(rough) {
    const magnitude = Math.pow(10, Math.floor(Math.log10(rough)));
    const fraction = rough / magnitude;
    const nice = fraction <= 1 ? 1 : fraction <= 2 ? 2 : fraction <= 5 ? 5 : 10;
    return nice * magnitude;
  }

  function niceTicks(min, max, count = 5) {
    if (!(max > min)) max = min + 1;
    const step = niceStep((max - min) / Math.max(count - 1, 1));
    const first = Math.floor(min / step) * step;
    const last = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = first; v <= last + step / 2; v += step) ticks.push(Math.abs(v) < step * 1e-9 ? 0 : v);
    return { ticks, min: first, max: last };
  }

  function extent(arrays) {
    let min = Infinity;
    let max = -Infinity;
    for (const values of arrays) {
      for (const v of values) {
        if (isNumber(v)) {
          if (v < min) min = v;
          if (v > max) max = v;
        }
      }
    }
    return isNumber(min) ? [min, max] : [0, 1];
  }

  function linePath(values, x, y) {
    let d = '';
    let pen = false;
    values.forEach((v, i) => {
      if (!isNumber(v)) {
        pen = false;
        return;
      }
      d += `${pen ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`;
      pen = true;
    });
    return d;
  }

  function areaPath(values, x, y, baseline) {
    const points = values.map((v, i) => (isNumber(v) ? [x(i), y(v)] : null)).filter(Boolean);
    if (!points.length) return '';
    const line = points.map(([px, py]) => `L${px.toFixed(1)} ${py.toFixed(1)}`).join('');
    return `M${points[0][0].toFixed(1)} ${baseline}${line}L${points[points.length - 1][0].toFixed(1)} ${baseline}Z`;
  }

  function gridAndYAxis(svg, { left, right, top, bottom, y, ticks, format }) {
    const grid = svgEl('g', { class: 'grid' });
    const axis = svgEl('g', { class: 'axis' });
    for (const tick of ticks) {
      const py = y(tick);
      if (py < top - 1 || py > bottom + 1) continue;
      grid.appendChild(svgEl('line', { x1: left, x2: right, y1: py.toFixed(1), y2: py.toFixed(1) }));
      axis.appendChild(svgEl('text', { x: left - 8, y: (py + 4).toFixed(1), 'text-anchor': 'end' }, format(tick)));
    }
    svg.appendChild(grid);
    svg.appendChild(axis);
  }

  function xAxisNumeric(svg, { ticks, x, left, right, y, format }) {
    const axis = svgEl('g', { class: 'axis' });
    axis.appendChild(svgEl('line', { x1: left, x2: right, y1: y, y2: y }));
    for (const tick of ticks) {
      axis.appendChild(svgEl('text', { x: x(tick).toFixed(1), y: y + 16, 'text-anchor': 'middle' }, format(tick)));
    }
    svg.appendChild(axis);
  }

  function dateAxis(svg, { labels, x, left, right, y }) {
    const axis = svgEl('g', { class: 'axis' });
    axis.appendChild(svgEl('line', { x1: left, x2: right, y1: y, y2: y }));
    const wanted = Math.max(2, Math.min(7, Math.floor((right - left) / 90)));
    for (let k = 0; k < wanted; k++) {
      const i = Math.round((k * (labels.length - 1)) / (wanted - 1));
      const text = /^\d{4}-\d{2}-\d{2}$/.test(labels[i]) ? labels[i].slice(0, 7) : labels[i];
      const anchor = k === 0 ? 'start' : k === wanted - 1 ? 'end' : 'middle';
      axis.appendChild(svgEl('text', { x: x(i).toFixed(1), y: y + 16, 'text-anchor': anchor }, text));
    }
    svg.appendChild(axis);
  }

  function axisTitle(svg, text, { x, y, rotate = false }) {
    const attributes = { x, y, class: 'axis-title', 'text-anchor': 'middle' };
    if (rotate) attributes.transform = `rotate(-90 ${x} ${y})`;
    svg.appendChild(svgEl('text', attributes, text));
  }

  const legendOffset = (item) => (item.kind === 'line' || !item.kind ? 22 : 16);
  const legendWidth = (item) => legendOffset(item) + item.label.length * 6.6 + 18;

  // Lay legend items out left to right, wrapping onto a new row rather than running off a narrow chart
  function legendLayout(items, x, maxRight) {
    const placed = [];
    let cursor = x;
    let row = 0;
    for (const item of items) {
      if (cursor > x && cursor + legendWidth(item) > maxRight) {
        row += 1;
        cursor = x;
      }
      placed.push({ item, x: cursor, row });
      cursor += legendWidth(item);
    }
    return { placed, rows: row + 1 };
  }

  const LEGEND_ROW_HEIGHT = 18;

  function legend(svg, items, x, y, maxRight) {
    const group = svgEl('g', { class: 'legend' });
    for (const { item, x: cursor, row } of legendLayout(items, x, maxRight).placed) {
      const baseline = y + row * LEGEND_ROW_HEIGHT;
      if (item.kind === 'bar') {
        group.appendChild(svgEl('rect', { x: cursor, y: baseline - 10, width: 12, height: 10, class: item.className || 'bar' }));
      } else if (item.kind === 'dot') {
        group.appendChild(svgEl('circle', { cx: cursor + 6, cy: baseline - 4, r: 3, class: `dot ${item.className || ''}` }));
      } else {
        group.appendChild(svgEl('line', { x1: cursor, x2: cursor + 16, y1: baseline - 4, y2: baseline - 4, class: `line ${item.className || ''}` }));
      }
      group.appendChild(svgEl('text', { x: cursor + legendOffset(item), y: baseline }, item.label));
    }
    svg.appendChild(group);
  }

  // Top of the plot area below a legend that takes the given number of rows
  const plotTop = (rows) => 14 + (rows - 1) * LEGEND_ROW_HEIGHT + 20;

  // ------------------------------------------------------------------------------------------------------------------
  // Chart plumbing: responsive redraw and an inspectable crosshair (pointer and keyboard)
  // ------------------------------------------------------------------------------------------------------------------

  const charts = [];
  const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
      const chart = charts.find((c) => c.container === entry.target);
      const width = Math.floor(entry.contentRect.width);
      if (chart && chart.draw && width > 0 && Math.abs(width - chart.width) > 1) chart.redraw();
    }
  });

  function registerChart(container, draw) {
    let chart = charts.find((c) => c.container === container);
    if (!chart) {
      chart = { container, width: 0 };
      charts.push(chart);
      resizeObserver.observe(container);
    }
    chart.draw = draw;
    chart.redraw = () => {
      chart.width = Math.floor(container.clientWidth);
      container.replaceChildren();
      if (chart.width > 0) draw(chart.width);
    };
    chart.redraw();
  }

  function attachCrosshair({ container, svg, count, left, right, top, bottom, x, describe }) {
    const tooltip = element('div', { className: 'tooltip', attributes: { 'aria-hidden': 'true' } });
    tooltip.hidden = true;
    container.appendChild(tooltip);
    const line = svgEl('line', { class: 'crosshair', y1: top, y2: bottom, visibility: 'hidden' });
    svg.appendChild(line);
    const overlay = svgEl('rect', { x: left, y: top, width: right - left, height: bottom - top, fill: 'transparent' });
    svg.appendChild(overlay);
    let current = null;

    function show(index) {
      current = Math.max(0, Math.min(count - 1, index));
      const px = x(current);
      line.setAttribute('x1', px);
      line.setAttribute('x2', px);
      line.setAttribute('visibility', 'visible');
      tooltip.replaceChildren();
      for (const [label, value] of describe(current)) {
        const row = element('div');
        if (value === undefined) {
          row.textContent = label;
        } else {
          row.append(`${label} `, element('b', { text: value }));
        }
        tooltip.appendChild(row);
      }
      tooltip.hidden = false;
      const width = container.clientWidth;
      const tipWidth = tooltip.offsetWidth;
      tooltip.style.left = `${Math.max(0, Math.min(width - tipWidth, px + 12))}px`;
      tooltip.style.top = `${top}px`;
    }

    function hide() {
      current = null;
      line.setAttribute('visibility', 'hidden');
      tooltip.hidden = true;
    }

    overlay.addEventListener('pointermove', (event) => {
      const box = svg.getBoundingClientRect();
      const px = ((event.clientX - box.left) / box.width) * Number(svg.getAttribute('width'));
      show(Math.round(((px - left) / (right - left)) * (count - 1)));
    });
    overlay.addEventListener('pointerleave', hide);
    container.tabIndex = 0;
    container.addEventListener('keydown', (event) => {
      const step = event.shiftKey ? 20 : 1;
      if (event.key === 'ArrowRight') show((current === null ? 0 : current) + step);
      else if (event.key === 'ArrowLeft') show((current === null ? count - 1 : current) - step);
      else if (event.key === 'Escape') hide();
      else return;
      event.preventDefault();
    });
    container.addEventListener('blur', hide);
  }

  function makeSvg(width, height, label) {
    const svg = svgEl('svg', { width, height, viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': label });
    svg.appendChild(svgEl('title', {}, label));
    return svg;
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Derived facts. Every sentence on the page is computed from the result, never written for a particular dataset.
  // ------------------------------------------------------------------------------------------------------------------

  function headlineRisk(result) {
    const { summary, settings } = result;
    const varKey = { historical: 'var_historical', parametric: 'var_parametric', cornish_fisher: 'var_cornish_fisher' }[settings.method];
    const esKey = settings.method === 'historical' ? 'expected_shortfall_historical' : 'expected_shortfall_parametric';
    return { var: summary[varKey], es: summary[esKey] };
  }

  function breachFacts(result) {
    const test = result.backtest;
    const ind = test.independence;
    const expected = test.expected_rate * test.observations;
    const afterBreach = ind.n10 + ind.n11 > 0 ? ind.n11 / (ind.n10 + ind.n11) : null;
    const afterQuiet = ind.n00 + ind.n01 > 0 ? ind.n01 / (ind.n00 + ind.n01) : null;
    return { test, ind, expected, afterBreach, afterQuiet, tooMany: test.observed_rate > test.expected_rate };
  }

  const zoneName = (zone) => t(zone[0].toUpperCase() + zone.slice(1));

  function verdictSentence(result) {
    const { test, ind, expected, afterBreach, afterQuiet, tooMany } = breachFacts(result);
    const light = test.traffic_light;
    const count = t('{n} breaches in {periods} periods against {expected} expected', { n: test.exceedances, periods: integer(test.observations), expected: num(expected, 1) });
    const clauses = [];
    if (test.reject) {
      clauses.push(tooMany ? t('{count}: the model understates risk (Kupiec p {p}).', { count, p: pValue(test.p_value) }) : t('{count}: the model overstates risk (Kupiec p {p}).', { count, p: pValue(test.p_value) }));
    } else {
      clauses.push(t('{count}: consistent with the confidence level (Kupiec p {p}).', { count, p: pValue(test.p_value) }));
    }
    if (ind.independence_reject && isNumber(afterBreach) && isNumber(afterQuiet)) {
      clauses.push(t('Breaches cluster: the chance of one the day after a breach is {after}, against {otherwise} otherwise.', { after: pct(afterBreach, 0), otherwise: pct(afterQuiet, 0) }));
    } else if (test.exceedances > 0) {
      clauses.push(t('No evidence that breaches cluster in time.'));
    }
    if (light.zone !== 'green') clauses.push(t('Basel traffic light: {zone}.', { zone: zoneName(light.zone) }));
    return clauses.join(' ');
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Tables and text
  // ------------------------------------------------------------------------------------------------------------------

  function renderHeadline(result) {
    const { summary, settings } = result;
    const conf = confidenceLabel(settings.confidence);
    const risk = headlineRisk(result);
    const items = [
      [t('Annualized return'), pct(summary.annualized_return), t('compound')],
      [t('Annualized volatility'), pct(summary.annualized_volatility), t('{n} periods per year', { n: settings.periods_per_year })],
      [t('{conf} value at risk', { conf }), pct(risk.var), t('one period, {method}', { method: methodName(settings.method) })],
      [t('{conf} expected shortfall', { conf }), pct(risk.es), t('average return on breach periods')],
    ];
    const list = $('#headline');
    list.replaceChildren();
    for (const [name, value, sub] of items) {
      list.appendChild(
        element('div', {}, [element('dt', { text: name }), element('dd', {}, [value, element('span', { className: 'sub', text: sub })])]),
      );
    }
  }

  function fillTable(table, caption, rows) {
    table.replaceChildren(element('caption', { text: caption }));
    const body = element('tbody');
    for (const [name, value] of rows) {
      body.appendChild(element('tr', {}, [element('th', { text: name, attributes: { scope: 'row' } }), element('td', { text: value })]));
    }
    table.appendChild(body);
  }

  function renderTables(result) {
    const s = result.summary;
    fillTable($('#table-drawdown'), t('Drawdown and risk-adjusted return'), [
      [t('Maximum drawdown'), pct(s.max_drawdown)],
      [t('Worst period'), pct(s.worst_period)],
      [t('Sortino ratio'), num(s.sortino_ratio)],
      [t('Calmar ratio'), num(s.calmar_ratio)],
      [t('Ulcer index'), pct(s.ulcer_index)],
    ]);
    fillTable($('#table-shape'), t('Shape of the distribution'), [
      [t('Skewness'), num(s.skewness)],
      [t('Excess kurtosis (0 = normal)'), num(s.excess_kurtosis)],
      [t('Best period'), pct(s.best_period)],
      [t('Downside deviation (annualized)'), pct(s.downside_deviation)],
      [t('Omega ratio'), num(s.omega_ratio)],
    ]);
  }

  function resultCell(rejected) {
    return element('span', {
      className: `result ${rejected ? 'bad' : 'ok'}`,
      text: rejected ? t('✕ Rejected') : t('✓ Not rejected'),
    });
  }

  function renderTests(result) {
    const { test, ind, expected } = breachFacts(result);
    const light = test.traffic_light;
    const zoneClass = { green: 'ok', yellow: 'warn', red: 'bad' }[light.zone];
    const rows = [
      ['Kupiec', t('Number of breaches against the confidence level'), `LR ${num(test.lr_statistic)}`, pValue(test.p_value), resultCell(test.reject)],
      [
        t('Christoffersen independence'),
        t('Do breaches cluster? ({n} of {total} breaches were followed by another)', { n: ind.n11, total: ind.n10 + ind.n11 }),
        `LR ${num(ind.independence_lr)}`,
        pValue(ind.independence_p_value),
        resultCell(ind.independence_reject),
      ],
      [
        t('Conditional coverage'),
        t('Number and timing of breaches together'),
        `LR ${num(ind.conditional_coverage_lr)}`,
        pValue(ind.conditional_coverage_p_value),
        resultCell(ind.conditional_coverage_reject),
      ],
      [
        t('Basel traffic light'),
        t('{n} breaches against {expected} expected', { n: test.exceedances, expected: num(expected, 1) }),
        `F = ${pct(light.cumulative_probability, 3)}`,
        DASH,
        element('span', { className: `result ${zoneClass}`, text: zoneName(light.zone) }),
      ],
    ];
    const table = $('#table-tests');
    table.replaceChildren();
    const head = element('tr', {}, [t('Test'), t('Statistic'), t('p-value'), t('Result')].map((h) => element('th', { text: h, attributes: { scope: 'col' } })));
    table.appendChild(element('thead', {}, [head]));
    const body = element('tbody');
    for (const [name, what, statistic, p, outcome] of rows) {
      body.appendChild(
        element('tr', {}, [
          element('th', { attributes: { scope: 'row' } }, [name, element('span', { className: 'what', text: what })]),
          element('td', { className: 'num', text: statistic }),
          element('td', { className: 'num', text: p }),
          element('td', {}, [outcome]),
        ]),
      );
    }
    table.appendChild(body);
    $('#verdict').textContent = verdictSentence(result);
  }

  function renderProvenance(result) {
    const { dates } = result.series;
    const dataset = state.dataset;
    const simulated = dataset && dataset.simulated;
    const saved = dataset && dataset.saved;
    const market = dataset && dataset.market;
    const tagText = saved ? t('Saved report') : market ? t('Market data') : simulated ? t('Simulated data') : t('Your data');
    const tag = element('span', { className: `tag${simulated ? '' : ' real'}`, text: tagText });
    const period = /^\d{4}-\d{2}-\d{2}$/.test(dates[0]) ? t('{from} to {to}', { from: dates[0], to: dates[dates.length - 1] }) : t('{n} observations', { n: dates.length });
    const assets = result.portfolio ? t('{n} assets', { n: result.portfolio.assets.length }) : '';
    let label = t('Uploaded series');
    if (dataset && dataset.title) label = simulated ? t('{title} scenario', { title: t(dataset.title) }) : dataset.title;
    else if (assets) label = t('Uploaded portfolio');
    const parts = [label, assets, t('{n} returns', { n: integer(result.summary.observations) }), period];
    if (saved && dataset.createdAt) parts.push(t('saved {date}', { date: dataset.createdAt.slice(0, 10) }));
    if (market) parts.push(t('prices from {source}', { source: market }));
    $('#provenance').replaceChildren(tag, parts.filter(Boolean).join(' · '));
  }

  function renderNotes(result) {
    const notes = [
      t('Rolling window of {window} periods, {n} periods per year.', { window: result.settings.window, n: result.settings.periods_per_year }),
      t('Every figure is a fraction of the portfolio, and losses are negative.'),
      ...((state.dataset && state.dataset.notes) || []).map(window.I18n.server),
      ...result.assumptions.map(window.I18n.server),
    ];
    const list = $('#notes');
    list.replaceChildren();
    for (const note of notes) list.appendChild(element('li', { text: note }));
  }

  // Text with **strong** parts, so that a translation can put them wherever its word order needs them
  function setTakeaway(id, text) {
    const node = $(id);
    node.replaceChildren();
    text.split('**').forEach((piece, i) => {
      if (i % 2) node.append(element('strong', { text: piece }));
      else if (piece) node.append(piece);
    });
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Portfolio: where the risk comes from
  // ------------------------------------------------------------------------------------------------------------------

  function shareCell(value) {
    const width = isNumber(value) ? Math.min(Math.abs(value), 1) * 100 : 0;
    const bar = element('span', { className: `bar${value < 0 ? ' negative' : ''}`, attributes: { 'aria-hidden': 'true' } });
    bar.style.width = `${width.toFixed(1)}%`; // set through the CSSOM: inline style attributes are blocked by the policy
    return element('td', {}, [element('span', { className: 'share' }, [bar, element('span', { text: pct(value, 1) })])]);
  }

  function correlationCell(value) {
    const cell = element('td', { text: num(value, 2) });
    if (isNumber(value)) {
      const strength = 0.06 + 0.5 * Math.abs(value);
      cell.style.backgroundColor = value >= 0 ? `rgba(31, 95, 191, ${strength.toFixed(2)})` : `rgba(179, 100, 15, ${strength.toFixed(2)})`;
    }
    return cell;
  }

  function portfolioTakeaway(details, conf) {
    const lessVolatile = 1 - 1 / details.diversification_ratio;
    let text = t('Diversification ratio **{ratio}**: the portfolio is {less} less volatile than the weighted average of its assets.', { ratio: num(details.diversification_ratio, 2), less: pct(lessVolatile, 0) });
    const tail = [...details.assets].filter((a) => isNumber(a.es_contribution));
    const worst = tail.sort((x, y) => y.es_contribution - y.weight - (x.es_contribution - x.weight))[0];
    if (worst && worst.es_contribution - worst.weight > 0.05) {
      text += ' ' + t('**{name}** is {weight} of the portfolio but {loss} of the loss on the {n} worst periods (the {conf} tail).', { name: worst.name, weight: pct(worst.weight, 0), loss: pct(worst.es_contribution, 0), n: details.tail_periods, conf });
    } else {
      text += ' ' + t('Tail losses are spread roughly in line with the weights ({n} periods in the {conf} tail).', { n: details.tail_periods, conf });
    }
    setTakeaway('#takeaway-portfolio', text);
  }

  function renderPortfolio(result) {
    const details = result.portfolio;
    $('#portfolio-section').hidden = !details;
    if (!details) return;
    const conf = confidenceLabel(result.settings.confidence);
    portfolioTakeaway(details, conf);

    const table = $('#table-assets');
    table.replaceChildren();
    const heads = [t('Asset'), t('Weight'), t('Volatility'), t('{conf} VaR alone', { conf }), t('Share of volatility'), t('Share of expected shortfall')];
    table.appendChild(element('thead', {}, [element('tr', {}, heads.map((h) => element('th', { text: h, attributes: { scope: 'col' } })))]));
    const body = element('tbody');
    for (const asset of details.assets) {
      body.appendChild(
        element('tr', {}, [
          element('th', { text: asset.name, attributes: { scope: 'row' } }),
          element('td', { text: pct(asset.weight, 1) }),
          element('td', { text: pct(asset.volatility, 1) }),
          element('td', { text: pct(asset.var, 2) }),
          shareCell(asset.volatility_contribution),
          shareCell(asset.es_contribution),
        ]),
      );
    }
    body.appendChild(
      element('tr', {}, [
        element('th', { text: t('Portfolio'), attributes: { scope: 'row' } }),
        element('td', { text: pct(details.assets.reduce((sum, a) => sum + a.weight, 0), 1) }),
        element('td', { text: pct(details.portfolio_volatility, 1) }),
        element('td', { text: pct(headlineRisk(result).var, 2) }),
        element('td', { text: percentText(100, 1) }),
        element('td', { text: percentText(100, 1) }),
      ]),
    );
    table.appendChild(body);

    const { names, matrix } = details.correlation;
    const corr = $('#table-corr');
    corr.replaceChildren();
    corr.appendChild(element('thead', {}, [element('tr', {}, [element('td'), ...names.map((n) => element('th', { text: n, attributes: { scope: 'col' } }))])]));
    const corrBody = element('tbody');
    names.forEach((name, i) => {
      corrBody.appendChild(element('tr', {}, [element('th', { text: name, attributes: { scope: 'row' } }), ...matrix[i].map(correlationCell)]));
    });
    corr.appendChild(corrBody);
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Stress: the worst stretches that actually happened
  // ------------------------------------------------------------------------------------------------------------------

  function renderStress(result) {
    const windows = result.stress || [];
    $('#stress-section').hidden = !windows.length;
    if (!windows.length) return;
    const conf = confidenceLabel(result.settings.confidence);
    const worstDay = windows.find((w) => w.periods === 1);
    const risk = headlineRisk(result);
    const sentences = [];
    if (worstDay && isNumber(risk.var) && risk.var < 0) {
      sentences.push(t('The worst single period lost **{loss}** on {date}, {times} times the {conf} VaR.', { loss: pct(worstDay.return, 2), date: worstDay.start, times: num(worstDay.return / risk.var, 1), conf }));
    }
    const longest = windows[windows.length - 1];
    sentences.push(t('The worst {n} periods in a row lost **{loss}** ({from} to {to}).', { n: longest.periods, loss: pct(longest.return, 1), from: longest.start, to: longest.end }));
    setTakeaway('#takeaway-stress', sentences.join(' '));

    const names = windows[0].assets ? windows[0].assets.map((a) => a.name) : [];
    const table = $('#table-stress');
    table.replaceChildren();
    const heads = [t('Window'), t('Return'), t('From'), t('To'), ...names];
    table.appendChild(element('thead', {}, [element('tr', {}, heads.map((h) => element('th', { text: h, attributes: { scope: 'col' } })))]));
    const body = element('tbody');
    for (const w of windows) {
      body.appendChild(
        element('tr', {}, [
          element('th', { text: w.periods === 1 ? t('Worst period') : t('Worst {n} periods', { n: w.periods }), attributes: { scope: 'row' } }),
          element('td', { text: pct(w.return, 2) }),
          element('td', { text: w.start }),
          element('td', { text: w.end }),
          ...(w.assets || []).map((a) => element('td', { text: pct(a.return, 2) })),
        ]),
      );
    }
    table.appendChild(body);
  }

  // ------------------------------------------------------------------------------------------------------------------
  // What if: shocks of the user's own, answered by the server
  // ------------------------------------------------------------------------------------------------------------------

  const SERIES_KEY = 'series'; // what the server calls a single series in a scenario
  const assetLabel = (name) => (name === SERIES_KEY ? t('Series') : name);
  const shockText = (fraction) => String(Number((fraction * 100).toFixed(2)));

  function whatIfCell(scenario, result) {
    return [
      element('td', { className: 'effect', text: pct(scenario.loss, 2) }),
      element('td', { className: 'multiple', text: isNumber(scenario.var_multiple) ? `${num(scenario.var_multiple, 1)}×` : DASH }),
      element('td', { className: 'multiple', text: isNumber(scenario.es_multiple) ? `${num(scenario.es_multiple, 1)}×` : DASH }),
    ];
  }

  function renderWhatIf(result) {
    const editable = !api.staticMode;
    const section = $('#whatif-section');
    const results = result.scenarios || [];
    section.hidden = editable ? false : !results.length;
    $('#whatif-add').hidden = !editable;
    if (section.hidden) return;
    const table = $('#table-whatif');
    const asked = (state.dataset && state.dataset.scenarios) || [];
    table.hidden = editable ? !asked.length : false;
    if (table.hidden) return;

    const names = result.portfolio ? result.portfolio.assets.map((a) => a.name) : [SERIES_KEY];
    const signature = JSON.stringify([names, editable ? asked.length : results.length, window.I18n.lang]);
    if (table.dataset.signature !== signature) {
      table.dataset.signature = signature;
      table.replaceChildren();
      const heads = [t('Scenario'), ...names.map((name) => t('{asset} (%)', { asset: assetLabel(name) })), t('Effect'), t('× VaR'), t('× ES')];
      if (editable) heads.push('');
      table.appendChild(element('thead', {}, [element('tr', {}, heads.map((h) => element('th', { text: h, attributes: { scope: 'col' } })))]));
      const body = element('tbody');
      (editable ? asked : results).forEach((scenario, i) => {
        const cells = [];
        if (editable) {
          cells.push(element('th', { attributes: { scope: 'row' } }, [element('input', { attributes: { type: 'text', maxlength: '60', value: scenario.name, 'aria-label': t('Scenario name'), 'data-field': 'name' } })]));
          for (const name of names) {
            const shock = scenario.shocks[name] || 0;
            cells.push(element('td', {}, [element('input', { attributes: { type: 'number', step: 'any', inputmode: 'decimal', value: shockText(shock), 'aria-label': t('Shock of {asset} (%)', { asset: assetLabel(name) }), 'data-asset': name } })]));
          }
        } else {
          cells.push(element('th', { text: scenario.name, attributes: { scope: 'row' } }));
          for (const asset of scenario.assets) cells.push(element('td', { text: pct(asset.shock, 1) }));
        }
        cells.push(...whatIfCell(scenario, result));
        if (editable) cells.push(element('td', {}, [element('button', { className: 'button danger', text: t('Remove'), attributes: { type: 'button', 'data-remove': String(i), 'aria-label': t('Remove {name}', { name: scenario.name }) } })]));
        body.appendChild(element('tr', {}, cells));
      });
      table.appendChild(body);
    }
    // the inputs keep what was typed; only the answers are rewritten
    table.querySelectorAll('tbody tr').forEach((row, i) => {
      const scenario = results[i];
      if (!scenario) return;
      const [effect, varMultiple, esMultiple] = whatIfCell(scenario, result);
      row.querySelector('.effect').replaceWith(effect);
      row.querySelectorAll('.multiple')[0].replaceWith(varMultiple);
      row.querySelectorAll('.multiple')[1].replaceWith(esMultiple);
    });
  }

  function readScenarios() {
    return [...document.querySelectorAll('#table-whatif tbody tr')].map((row, i) => {
      const shocks = {};
      for (const input of row.querySelectorAll('input[data-asset]')) {
        const value = Number(input.value);
        shocks[input.dataset.asset] = Number.isFinite(value) ? value / 100 : 0;
      }
      return { name: row.querySelector('input[data-field="name"]').value.trim() || t('Scenario {n}', { n: i + 1 }), shocks };
    });
  }

  function addScenario() {
    const dataset = state.dataset;
    if (!dataset || !state.result) return;
    const names = state.result.portfolio ? state.result.portfolio.assets.map((a) => a.name) : [SERIES_KEY];
    const scenarios = dataset.scenarios || [];
    if (scenarios.length >= 5) {
      setStatus(t('At most five scenarios.'), true);
      return;
    }
    dataset.scenarios = [...scenarios, { name: t('Scenario {n}', { n: scenarios.length + 1 }), shocks: Object.fromEntries(names.map((n) => [n, -0.1])) }];
    scheduleRun(0);
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Charts
  // ------------------------------------------------------------------------------------------------------------------

  function drawGrowth(container, result) {
    const { dates, growth: rawGrowth, drawdown } = result.series;
    const growth = rawGrowth.map((g) => (isNumber(g) ? g * 100 : g));
    const n = dates.length;
    const episode = result.worst_drawdown;
    const label = t('Growth of 100 invested, ending at {end}. Maximum drawdown {depth}, from {from} to {to}.', { end: num(growth[n - 1], 1), depth: pct(episode.depth, 1), from: dates[episode.peak], to: dates[episode.trough] });
    setTakeaway('#takeaway-growth', t('Ends at **{end}**. Deepest fall **{depth}** from the peak on {from} to the trough on {to}.', { end: num(growth[n - 1], 1), depth: pct(episode.depth, 1), from: dates[episode.peak], to: dates[episode.trough] }));

    registerChart(container, (width) => {
      const compact = width < 520;
      const left = compact ? 56 : 68;
      const right = width - 12;
      const growthTop = 12;
      const growthBottom = 200;
      const ddTop = 232;
      const ddBottom = 310;
      const svg = makeSvg(width, ddBottom + 40, label);
      const x = linearScale(0, Math.max(n - 1, 1), left, right);

      const [gMin, gMax] = extent([growth]);
      const gScale = niceTicks(Math.min(gMin, 100), gMax, 5);
      const yGrowth = linearScale(gScale.min, gScale.max, growthBottom, growthTop);
      gridAndYAxis(svg, { left, right, top: growthTop, bottom: growthBottom, y: yGrowth, ticks: gScale.ticks, format: (v) => v.toFixed(0) });
      // shade the deepest peak-to-trough episode so the drawdown panel below reads against the level above
      const x0 = x(episode.peak);
      const x1 = x(episode.trough);
      svg.appendChild(svgEl('rect', { x: x0.toFixed(1), y: growthTop, width: Math.max(x1 - x0, 1).toFixed(1), height: growthBottom - growthTop, class: 'span' }));
      svg.appendChild(svgEl('line', { x1: left, x2: right, y1: yGrowth(100).toFixed(1), y2: yGrowth(100).toFixed(1), class: 'line ref' }));
      svg.appendChild(svgEl('path', { d: linePath(growth, x, yGrowth), class: 'line' }));
      axisTitle(svg, t('Growth of 100'), { x: 14, y: (growthTop + growthBottom) / 2, rotate: true });

      const [dMin] = extent([drawdown]);
      const dScale = niceTicks(Math.min(dMin, -0.01), 0, 3);
      const yDd = linearScale(dScale.min, 0, ddBottom, ddTop);
      gridAndYAxis(svg, { left, right, top: ddTop, bottom: ddBottom, y: yDd, ticks: dScale.ticks, format: (v) => pct(v, 0) });
      svg.appendChild(svgEl('rect', { x: x0.toFixed(1), y: ddTop, width: Math.max(x1 - x0, 1).toFixed(1), height: ddBottom - ddTop, class: 'span' }));
      svg.appendChild(svgEl('path', { d: areaPath(drawdown, x, yDd, yDd(0).toFixed(1)), class: 'area' }));
      const labelX = Math.min(Math.max(x1, left + 60), right - 60);
      svg.appendChild(svgEl('text', { x: labelX.toFixed(1), y: (ddTop - 6).toFixed(1), 'text-anchor': 'middle', class: 'annotation' }, t('Max drawdown {depth}', { depth: pct(episode.depth, 1) })));
      dateAxis(svg, { labels: dates, x, left, right, y: ddBottom });
      axisTitle(svg, t('Drawdown'), { x: 14, y: (ddTop + ddBottom) / 2, rotate: true });

      container.appendChild(svg);
      attachCrosshair({
        container, svg, count: n, left, right, top: growthTop, bottom: ddBottom, x,
        describe: (i) => [[dates[i]], [t('Growth of 100'), num(growth[i], 1)], [t('Drawdown'), pct(drawdown[i], 1)]],
      });
    });
  }

  function drawVar(container, result) {
    const { dates, returns, var: varSeries, expected_shortfall: es, breach } = result.series;
    const n = dates.length;
    const conf = confidenceLabel(result.settings.confidence);
    const { test, expected } = breachFacts(result);
    const label = t('Daily returns against the {conf} value at risk forecast: {n} breaches in {periods} periods, {expected} expected.', { conf, n: test.exceedances, periods: test.observations, expected: num(expected, 1) });
    setTakeaway('#takeaway-var', t('The forecast was breached **{n} times** in {periods} periods ({expected} expected at {conf}). Each return is judged against the forecast made the period before.', { n: test.exceedances, periods: integer(test.observations), expected: num(expected, 1), conf }));

    registerChart(container, (width) => {
      const compact = width < 520;
      const left = compact ? 56 : 68;
      const right = width - 12;
      const legendItems = [
        { kind: 'bar', label: t('Return'), className: 'bar' },
        { kind: 'bar', label: t('Breach'), className: 'bar breach-key' },
        { label: t('{conf} VaR', { conf }) },
        { label: t('Expected shortfall'), className: 'second dashed' },
      ];
      const top = plotTop(legendLayout(legendItems, left, right).rows);
      const bottom = top + 240;
      const svg = makeSvg(width, bottom + 40, label);
      const x = linearScale(0, Math.max(n - 1, 1), left, right);
      const [lo, hi] = extent([returns, varSeries, es]);
      const scale = niceTicks(lo, hi, 6);
      const y = linearScale(scale.min, scale.max, bottom, top);
      gridAndYAxis(svg, { left, right, top, bottom, y, ticks: scale.ticks, format: (v) => pct(v, 1) });

      // returns as bars from zero: one path for ordinary periods and one for breaches, so a thousand bars stay cheap
      const barWidth = Math.max(((right - left) / n) * 0.85, 0.8).toFixed(2);
      const zero = y(0).toFixed(1);
      let ordinary = '';
      let breached = '';
      returns.forEach((v, i) => {
        if (!isNumber(v)) return;
        const segment = `M${x(i).toFixed(1)} ${zero}V${y(v).toFixed(1)}`;
        if (breach[i]) breached += segment;
        else ordinary += segment;
      });
      svg.appendChild(svgEl('path', { d: ordinary, class: 'bars', 'stroke-width': barWidth }));
      svg.appendChild(svgEl('line', { x1: left, x2: right, y1: zero, y2: zero, class: 'line ref' }));
      svg.appendChild(svgEl('path', { d: linePath(varSeries, x, y), class: 'line' }));
      svg.appendChild(svgEl('path', { d: linePath(es, x, y), class: 'line second dashed' }));
      svg.appendChild(svgEl('path', { d: breached, class: 'bars breach', 'stroke-width': Math.max(Number(barWidth), 2).toFixed(2) }));
      dateAxis(svg, { labels: dates, x, left, right, y: bottom });
      axisTitle(svg, t('Daily return'), { x: 14, y: (top + bottom) / 2, rotate: true });
      legend(svg, legendItems, left, 14, right);

      container.appendChild(svg);
      attachCrosshair({
        container, svg, count: n, left, right, top, bottom, x,
        describe: (i) => {
          const lines = [[dates[i]], [t('Return'), pct(returns[i], 2)], [t('VaR forecast'), pct(varSeries[i], 2)], [t('Expected shortfall'), pct(es[i], 2)]];
          if (breach[i]) lines.push([t('Breach')]);
          return lines;
        },
      });
    });
  }

  function drawDistribution(container, result) {
    const headline = headlineRisk(result);
    const { centres, counts, normal_counts: normal, width: binWidth, outliers_below: below, outliers_above: above } = result.histogram;
    const label = t('Histogram of returns with the normal curve, value at risk {var} and expected shortfall {es}.', { var: pct(headline.var, 2), es: pct(headline.es, 2) });
    const conf = confidenceLabel(result.settings.confidence);
    const outliers = below + above ? ' ' + t('({n} outliers not shown)', { n: below + above }) : '';
    setTakeaway('#takeaway-dist', t('Central 99% of returns.{outliers} VaR **{var}**, expected shortfall **{es}** at {conf}.', { outliers, var: pct(headline.var, 2), es: pct(headline.es, 2), conf }));

    registerChart(container, (width) => {
      const compact = width < 520;
      const left = compact ? 40 : 52;
      const right = width - 10;
      const top = 24;
      const bottom = 250;
      const svg = makeSvg(width, bottom + 46, label);
      const xMin = centres[0] - binWidth / 2;
      const xMax = centres[centres.length - 1] + binWidth / 2;
      const xScale = niceTicks(xMin, xMax, width < 420 ? 4 : 6);
      const x = linearScale(xScale.min, xScale.max, left, right);
      const [, peak] = extent([counts, normal]);
      const yScale = niceTicks(0, peak, 5);
      const y = linearScale(yScale.min, yScale.max, bottom, top);
      gridAndYAxis(svg, { left, right, top, bottom, y, ticks: yScale.ticks, format: (v) => String(Math.round(v)) });

      centres.forEach((c, i) => {
        const x0 = x(c - binWidth / 2);
        const x1 = x(c + binWidth / 2);
        svg.appendChild(svgEl('rect', { x: x0.toFixed(1), y: y(counts[i]).toFixed(1), width: Math.max(x1 - x0 - 1, 1).toFixed(1), height: (bottom - y(counts[i])).toFixed(1), class: 'bar' }));
      });
      svg.appendChild(svgEl('path', { d: linePath(normal, (i) => x(centres[i]), y), class: 'normal' }));
      xAxisNumeric(svg, { ticks: xScale.ticks, x, left, right, y: bottom, format: (v) => pct(v, 0) });
      axisTitle(svg, t('Daily return'), { x: (left + right) / 2, y: bottom + 36 });
      axisTitle(svg, t('Days'), { x: 12, y: (top + bottom) / 2, rotate: true });

      // label the markers on the chart itself rather than in a legend
      const marks = [
        ['VaR', headline.var, 'var'],
        ['ES', headline.es, 'es'],
      ].filter(([, v]) => isNumber(v) && v >= xScale.min && v <= xScale.max);
      marks.sort((a, b) => a[1] - b[1]);
      marks.forEach(([name, value, kind], k) => {
        const px = x(value);
        svg.appendChild(svgEl('line', { x1: px.toFixed(1), x2: px.toFixed(1), y1: top, y2: bottom, class: `marker ${kind}` }));
        const anchor = k === 0 && marks.length > 1 ? 'end' : 'start';
        svg.appendChild(svgEl('text', { x: (px + (anchor === 'end' ? -4 : 4)).toFixed(1), y: top - 8, 'text-anchor': anchor, class: `marker-label ${kind}` }, `${name} ${pct(value, 2)}`));
      });
      svg.appendChild(svgEl('line', { x1: right - 88, x2: right - 70, y1: top + 6, y2: top + 6, class: 'normal' }));
      svg.appendChild(svgEl('text', { x: right - 64, y: top + 10, class: 'label' }, t('Normal fit')));
      container.appendChild(svg);
    });
  }

  function drawQq(container, result) {
    const { theoretical, sample } = result.qq;
    const alpha = 1 - result.settings.confidence;
    const conf = confidenceLabel(result.settings.confidence);
    const worst = sample[0];
    const normalWorst = theoretical[0];
    const label = t('QQ plot of standardised returns against normal quantiles. The worst return is {worst} standard deviations; a normal sample of this size would reach about {normal}.', { worst: num(worst, 1), normal: num(normalWorst, 1) });
    const fatter = worst < normalWorst - 0.5;
    setTakeaway(
      '#takeaway-qq',
      t('Worst return is **{worst}σ**; a normal sample this size would reach about {normal}σ.', { worst: num(worst, 1), normal: num(normalWorst, 1) }) +
        ' ' +
        (fatter ? t('The left tail is fatter than a normal distribution allows.') : t('The left tail is in line with a normal distribution.')),
    );
    // the normal quantile of the VaR level: points beyond it are the tail the VaR is meant to cover
    const tailCut = normalQuantile(alpha);

    registerChart(container, (width) => {
      const compact = width < 520;
      const left = compact ? 44 : 52;
      const right = width - 10;
      const top = 24;
      const bottom = 250;
      const svg = makeSvg(width, bottom + 46, label);
      const [lo, hi] = extent([theoretical, sample]);
      const scale = niceTicks(Math.min(lo, -3), Math.max(hi, 3), 8);
      const x = linearScale(scale.min, scale.max, left, right);
      const y = linearScale(scale.min, scale.max, bottom, top);
      gridAndYAxis(svg, { left, right, top, bottom, y, ticks: scale.ticks, format: (v) => v.toFixed(0) });
      xAxisNumeric(svg, { ticks: scale.ticks, x, left, right, y: bottom, format: (v) => v.toFixed(0) });
      axisTitle(svg, t('Normal quantile (standard deviations)'), { x: (left + right) / 2, y: bottom + 36 });
      axisTitle(svg, t('Sample quantile'), { x: 12, y: (top + bottom) / 2, rotate: true });
      svg.appendChild(svgEl('line', { x1: x(scale.min).toFixed(1), y1: y(scale.min).toFixed(1), x2: x(scale.max).toFixed(1), y2: y(scale.max).toFixed(1), class: 'line ref' }));
      sample.forEach((value, i) => {
        svg.appendChild(svgEl('circle', { cx: x(theoretical[i]).toFixed(1), cy: y(value).toFixed(1), r: 2.6, class: theoretical[i] <= tailCut ? 'dot tail' : 'dot' }));
      });
      svg.appendChild(svgEl('circle', { cx: right - 150, cy: bottom - 14, r: 3, class: 'dot tail' }));
      svg.appendChild(svgEl('text', { x: right - 142, y: bottom - 10, class: 'label' }, t('Beyond the {conf} VaR level', { conf })));
      container.appendChild(svg);
    });
  }

  // Inverse of the standard normal distribution function (Acklam's rational approximation, relative error ~1e-9)
  function normalQuantile(p) {
    const a = [-39.69683028665376, 220.9460984245205, -275.9285104469687, 138.357751867269, -30.66479806614716, 2.506628277459239];
    const b = [-54.47609879822406, 161.5858368580409, -155.6989798598866, 66.80131188771972, -13.28068155288572];
    const c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783];
    const d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996, 3.754408661907416];
    const low = 0.02425;
    if (p < low) {
      const q = Math.sqrt(-2 * Math.log(p));
      return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1);
    }
    if (p > 1 - low) return -normalQuantile(1 - p);
    const q = p - 0.5;
    const r = q * q;
    return ((((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q) / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1);
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Page
  // ------------------------------------------------------------------------------------------------------------------

  function render(result) {
    state.result = result;
    renderProvenance(result);
    renderHeadline(result);
    renderTables(result);
    renderTests(result);
    renderPortfolio(result);
    renderStress(result);
    renderWhatIf(result);
    renderNotes(result);
    drawGrowth($('#chart-growth'), result);
    drawVar($('#chart-var'), result);
    drawDistribution($('#chart-dist'), result);
    drawQq($('#chart-qq'), result);
  }

  // ------------------------------------------------------------------------------------------------------------------
  // CSV in and out
  // ------------------------------------------------------------------------------------------------------------------

  function parseNumber(text) {
    const trimmed = text.trim();
    if (trimmed === '') return NaN;
    if (trimmed.endsWith('%')) return Number(trimmed.slice(0, -1)) / 100;
    return Number(trimmed);
  }

  function parseCsv(text, kind) {
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!lines.length) throw new Error(t('The file is empty.'));
    const delimiter = [',', ';', '\t'].find((d) => lines[0].includes(d)) || ',';
    let rows = lines.map((line) => line.split(delimiter).map((cell) => cell.trim().replace(/^"|"$/g, '')));
    const last = rows[0].length - 1;
    if (Number.isNaN(parseNumber(rows[0][Math.min(1, last)]))) rows = rows.slice(1); // header
    if (!rows.length) throw new Error(t('The file has no data rows.'));
    if (rows.length > MAX_ROWS) throw new Error(t('The file has {n} rows, the maximum is {max}.', { n: rows.length, max: MAX_ROWS }));

    const dated = rows[0].length > 1;
    const values = [];
    const dates = [];
    rows.forEach((row, i) => {
      const value = parseNumber(dated ? row[1] : row[0]);
      if (!Number.isFinite(value)) throw new Error(t('Row {row} does not contain a number.', { row: i + 1 }));
      values.push(value);
      if (dated) {
        if (!/^\d{4}-\d{2}-\d{2}/.test(row[0])) throw new Error(t('Row {row}: the first column must be a date such as 2024-03-29.', { row: i + 1 }));
        dates.push(row[0].slice(0, 10));
      }
    });
    return { id: 'upload', simulated: false, kind, values, dates: dated ? dates : null };
  }

  const DATE_CELL = /^\d{4}-\d{2}-\d{2}/;

  // Several assets side by side: an optional date column, a header with the asset names, one column per asset
  function parsePortfolioCsv(text, kind, maxAssets) {
    const lines = text.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);
    if (!lines.length) throw new Error(t('The file is empty.'));
    const delimiter = [',', ';', '\t'].find((d) => lines[0].includes(d)) || ',';
    let rows = lines.map((line) => line.split(delimiter).map((cell) => cell.trim().replace(/^"|"$/g, '')));
    const hasHeader = rows[0].some((cell) => !DATE_CELL.test(cell) && Number.isNaN(parseNumber(cell)));
    const header = hasHeader ? rows[0] : null;
    if (hasHeader) rows = rows.slice(1);
    if (!rows.length) throw new Error(t('The file has no data rows.'));
    if (rows.length > MAX_ROWS) throw new Error(t('The file has {n} rows, the maximum is {max}.', { n: rows.length, max: MAX_ROWS }));

    const dated = DATE_CELL.test(rows[0][0]);
    const first = dated ? 1 : 0;
    const count = rows[0].length - first;
    if (count < 2) throw new Error(t('A portfolio needs at least two asset columns.'));
    if (count > maxAssets) throw new Error(t('The file has {n} assets, the maximum is {max}.', { n: count, max: maxAssets }));
    const names = [];
    for (let j = 0; j < count; j++) {
      const name = header && header[first + j] ? header[first + j] : t('Asset {n}', { n: j + 1 });
      if (names.includes(name)) throw new Error(t('The asset name "{name}" appears twice.', { name }));
      names.push(name);
    }
    const assets = Object.fromEntries(names.map((n) => [n, []]));
    const dates = [];
    rows.forEach((row, i) => {
      if (row.length !== count + first) throw new Error(t('Row {row} has {n} columns, expected {expected}.', { row: i + 1, n: row.length, expected: count + first }));
      if (dated) {
        if (!DATE_CELL.test(row[0])) throw new Error(t('Row {row}: the first column must be a date such as 2024-03-29.', { row: i + 1 }));
        dates.push(row[0].slice(0, 10));
      }
      names.forEach((name, j) => {
        const value = parseNumber(row[first + j]);
        if (!Number.isFinite(value)) throw new Error(t('Row {row}, {name}: not a number.', { row: i + 1, name }));
        assets[name].push(value);
      });
    });
    return { id: 'portfolio', portfolio: true, simulated: false, kind, assets, dates: dated ? dates : null, weights: equalWeights(names) };
  }

  const equalWeights = (names) => Object.fromEntries(names.map((n) => [n, 1 / names.length]));

  // A cell that starts with = + @ can be executed as a formula by a spreadsheet, so it is never emitted raw
  const csvCell = (value) => {
    if (value === null || value === undefined) return '';
    const text = String(value);
    return /^[=+@]/.test(text) ? `'${text}` : text;
  };

  function resultToCsv(result) {
    const { dates, returns, growth, drawdown, var: varSeries, expected_shortfall: es, breach } = result.series;
    const header = ['date', 'return', 'growth_of_1', 'drawdown', 'var_forecast', 'expected_shortfall', 'breach'];
    const rows = dates.map((date, i) => [date, returns[i], growth[i], drawdown[i], varSeries[i], es[i], breach[i] ? 1 : 0]);
    return `${[header, ...rows].map((row) => row.map(csvCell).join(',')).join('\n')}\n`;
  }

  function saveBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = element('a', { attributes: { href: url, download: filename } });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function download() {
    if (!state.result) return;
    saveBlob(new Blob([resultToCsv(state.result)], { type: 'text/csv;charset=utf-8' }), 'risk_series.csv');
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------------------------------------------------------

  const SAMPLE_PORTFOLIO = [
    ['calm', 'Calm market', 11],
    ['volatile', 'Volatile market', 12],
    ['regime_shift', 'Regime shift', 13], // the titles are keys of the translations: see loadSamplePortfolio
  ];

  const state = {
    dataset: null,
    datasets: { single: null, portfolio: null },
    mode: 'single',
    result: null,
    request: 0,
    timer: null,
    savedRun: null,
    runs: [],
    compare: new Set(),
    limits: { assets: 10 },
    scenarios: [],
    marketSource: null,
    started: false,
  };

  function setStatus(message, isError = false) {
    const status = $('#status');
    status.textContent = message;
    status.classList.toggle('error', isError);
  }

  // A 401 means the server wants a token: ask for one instead of showing an error
  function fail(error) {
    if (error.status === 401) {
      const rejected = Boolean(token);
      setToken('');
      $('#token-form').hidden = false;
      $('#token').focus();
      setStatus(rejected ? t('That access token was not accepted.') : t('Enter the access token to continue.'), rejected);
      return;
    }
    setStatus(window.I18n.server(error.message), true);
  }

  // The static export only has results for a grid of confidence levels; the slider then steps through that grid
  const confidenceValue = () => (api.confidences ? api.confidences[Number($('#confidence').value)] : Number($('#confidence').value));

  function settings() {
    return { confidence: confidenceValue(), method: $('#method').value, window: Number($('#window').value) };
  }

  // The rolling window must be shorter than the series: a short history gets a window that fits instead of an error
  function fitWindow(dataset) {
    const first = dataset.portfolio ? Object.values(dataset.assets || {})[0] : dataset.values;
    if (!first) return; // the static export has results only, not the series behind them
    const returns = dataset.kind === 'prices' ? first.length - 1 : first.length;
    const input = $('#window');
    if (returns <= Number(input.value) + 1 && !input.closest('.field').hidden) input.value = Math.max(30, Math.floor(returns / 2));
  }

  function setDataset(dataset) {
    fitWindow(dataset);
    state.dataset = dataset;
    state.datasets[dataset.portfolio ? 'portfolio' : 'single'] = dataset;
    state.savedRun = null;
    updateSaveControls();
  }

  function updateSaveControls() {
    const report = $('#report'); // not part of the static export
    if (report) report.hidden = !state.savedRun;
    renderHistory();
  }

  async function run() {
    if (!state.dataset) return;
    const ticket = ++state.request;
    const results = $('#results');
    results.classList.add('loading');
    setStatus(t('Calculating…'));
    try {
      const result = await api.analyze(state.dataset, settings());
      if (ticket !== state.request) return; // a newer request superseded this one
      results.hidden = false;
      render(result);
      setStatus('');
    } catch (error) {
      if (ticket !== state.request) return;
      fail(error);
    } finally {
      if (ticket === state.request) results.classList.remove('loading');
    }
  }

  function scheduleRun(delay = 200) {
    state.savedRun = null;
    updateSaveControls();
    clearTimeout(state.timer);
    state.timer = setTimeout(run, delay);
  }

  async function chooseScenario(scenario) {
    setStatus(t('Loading sample data…'));
    try {
      setDataset(await api.loadScenario(scenario.id, scenario.title));
      $('#file').value = '';
      await run();
    } catch (error) {
      fail(error);
    }
  }

  // ---- portfolio inputs

  function renderWeights() {
    const dataset = state.datasets.portfolio;
    $('#weights-field').hidden = !dataset;
    if (!dataset) return;
    const body = $('#weights');
    body.replaceChildren();
    Object.keys(dataset.assets).forEach((name, i) => {
      const input = element('input', { attributes: { id: `weight-${i}`, type: 'number', step: 'any', 'data-asset': name, inputmode: 'decimal' } });
      input.value = (dataset.weights[name] * 100).toFixed(2).replace(/\.?0+$/, '');
      input.dataset.exact = String(dataset.weights[name]); // the rounded text must not replace an exact weight such as 1/3
      body.appendChild(
        element('tr', {}, [
          element('th', { attributes: { scope: 'row' } }, [element('label', { text: `${name} (%)`, attributes: { for: `weight-${i}` } })]),
          element('td', {}, [input]),
        ]),
      );
    });
    updateWeightsHint();
  }

  function readWeights() {
    const weights = {};
    for (const input of document.querySelectorAll('#weights input')) {
      const shown = Number(input.value) / 100;
      const exact = Number(input.dataset.exact);
      weights[input.dataset.asset] = Math.abs(shown - exact) < 5e-5 ? exact : shown; // untouched inputs keep their exact value
    }
    return weights;
  }

  function updateWeightsHint() {
    const values = Object.values(readWeights());
    const total = values.reduce((sum, v) => sum + v, 0);
    const hint = $('#weights-hint');
    if (values.some((v) => !Number.isFinite(v))) hint.textContent = t('Every weight must be a number.');
    else if (Math.abs(total - 1) < 1e-4) hint.textContent = t('The weights sum to 100%.');
    else hint.textContent = total > 0 ? t('The weights sum to {total} and are scaled to 100%.', { total: pct(total, 1) }) : t('The weights sum to {total}.', { total: pct(total, 1) });
  }

  async function loadSamplePortfolio() {
    setStatus(t('Loading sample portfolio…'));
    try {
      const sets = await Promise.all(SAMPLE_PORTFOLIO.map(([id, title, seed]) => api.loadScenario(id, title, seed)));
      const assets = Object.fromEntries(SAMPLE_PORTFOLIO.map(([, title], i) => [t(title), sets[i].values]));
      setDataset({
        id: 'portfolio', portfolio: true, simulated: true, title: t('Sample portfolio'), kind: 'returns',
        assets, dates: sets[0].dates, weights: equalWeights(Object.keys(assets)),
      });
      renderWeights();
      await run();
    } catch (error) {
      fail(error);
    }
  }

  function setMode(mode) {
    state.mode = mode;
    document.querySelector(`input[name="mode"][value="${mode}"]`).checked = true;
    const portfolio = mode === 'portfolio';
    $('#portfolio-fields').hidden = !portfolio;
    $('#scenario-field').hidden = portfolio;
    $('#file-field').hidden = portfolio;
    updateMarketField();
    $('#mode-hint').textContent = portfolio
      ? t('Assets held at constant weights, rebalanced every period. Shows what each asset adds to the risk.')
      : t('One series of returns or prices.');
  }

  async function switchMode(mode) {
    setMode(mode);
    const dataset = state.datasets[mode];
    if (dataset) {
      state.dataset = dataset;
      state.savedRun = null;
      updateSaveControls();
      await run();
    } else {
      state.dataset = null;
      $('#results').hidden = true;
      setStatus(mode === 'portfolio' ? t('Upload a CSV of several assets or load the sample portfolio.') : '');
      if (mode === 'single') await chooseScenario(state.scenarios.find((s) => s.id === $('#scenario').value));
    }
  }

  // ---- market data

  function updateMarketField() {
    const field = $('#market-field');
    field.hidden = !state.marketSource;
    if (!state.marketSource) return;
    const portfolio = state.mode === 'portfolio';
    $('#symbols-label').textContent = portfolio ? t('Load several symbols') : t('Load by symbol');
    $('#symbols').placeholder = portfolio ? 'THYAO.IS, GARAN.IS, ASELS.IS' : 'THYAO.IS';
    const adjusted = state.marketSource === 'Yahoo Finance';
    const hint = portfolio
      ? adjusted
        ? t('Daily closing prices from {source}, adjusted for splits and dividends, two to {max} symbols separated by commas. They can be delayed, and are not investment advice.')
        : t('Daily closing prices from {source}, two to {max} symbols separated by commas. They can be delayed, and are not investment advice.')
      : adjusted
        ? t('Daily closing prices from {source}, adjusted for splits and dividends. They can be delayed, and are not investment advice.')
        : t('Daily closing prices from {source}. They can be delayed, and are not investment advice.');
    $('#market-hint').textContent = hint.replace('{source}', state.marketSource).replace('{max}', state.limits.assets);
  }

  async function loadMarket() {
    const symbols = $('#symbols').value.split(',').map((s) => s.trim()).filter(Boolean);
    const portfolio = state.mode === 'portfolio';
    if (portfolio ? symbols.length < 2 : symbols.length !== 1) {
      setStatus(portfolio ? t('Give at least two symbols, separated by commas.') : t('Give one symbol, or switch to a portfolio for several.'), true);
      return;
    }
    const years = $('#market-history').value;
    let start = null;
    if (years !== 'all') {
      const from = new Date();
      from.setFullYear(from.getFullYear() - Number(years));
      start = from.toISOString().slice(0, 10);
    }
    setStatus(t('Loading prices from {source}…', { source: state.marketSource }));
    try {
      const data = await api.marketPrices(symbols, start, $('#market-base').value);
      const inBase = data.base && Object.keys(data.converted).length ? ' ' + t('in {currency}', { currency: data.base }) : '';
      if (portfolio) {
        setDataset({
          id: 'portfolio', portfolio: true, simulated: false, market: data.source, title: `${data.symbols.join(', ')}${inBase}`, notes: data.notes, kind: 'prices',
          assets: data.prices, dates: data.dates, weights: equalWeights(data.symbols),
        });
        renderWeights();
      } else {
        const symbol = data.symbols[0];
        setDataset({ id: 'upload', simulated: false, market: data.source, title: `${symbol}${inBase}`, notes: data.notes, kind: 'prices', values: data.prices[symbol], dates: data.dates });
        $('#file').value = '';
      }
      await run();
    } catch (error) {
      fail(error);
    }
  }

  // ---- saved runs

  const kindLabel = (kind) => ({ single: t('Series'), portfolio: t('Portfolio') })[kind] || kind;

  function renderHistory() {
    const list = $('#history');
    list.replaceChildren();
    $('#history-empty').hidden = state.runs.length > 0;
    for (const id of [...state.compare]) if (!state.runs.some((r) => r.id === id)) state.compare.delete(id);
    $('#compare-bar').hidden = state.runs.length < 2;
    for (const item of state.runs) {
      const current = state.savedRun && state.savedRun.id === item.id;
      const h = item.headline || {};
      const meta = [
        kindLabel(item.kind),
        item.created_at.slice(0, 16).replace('T', ' '),
        t('{conf} VaR {var}', { conf: confidenceLabel(h.confidence), var: pct(h.var, 2) }),
        t('Basel {zone}', { zone: zoneName(h.zone) }),
      ].join(' · ');
      const buttons = element('div', { className: 'buttons' }, [
        element('button', { className: 'button', text: t('Open'), attributes: { type: 'button', 'data-action': 'open', 'aria-label': t('Open {name}', { name: item.name }) } }),
        element('button', { className: 'button', text: t('Report'), attributes: { type: 'button', 'data-action': 'report', 'aria-label': t('Download the report of {name}', { name: item.name }) } }),
        element('button', { className: 'button danger', text: t('Delete'), attributes: { type: 'button', 'data-action': 'delete', 'aria-label': t('Delete {name}', { name: item.name }) } }),
      ]);
      const row = element('li', { className: current ? 'current' : '', attributes: { 'data-id': item.id } }, [
          element('label', { className: 'name' }, [
            element('input', { attributes: { type: 'checkbox', 'data-compare': item.id, 'aria-label': t('Compare {name}', { name: item.name }) } }),
            element('span', { text: item.name }),
          ]),
          element('span', { className: 'meta', text: meta }),
          buttons,
      ]);
      row.querySelector('input[data-compare]').checked = state.compare.has(item.id);
      list.appendChild(row);
    }
    updateCompareControls();
  }

  // ---- comparing saved analyses

  const COMPARE_ROWS = [
    ['Type', (r) => kindLabel(r.kind)],
    ['Saved', (r) => r.created_at.slice(0, 10)],
    ['Confidence', (r) => confidenceLabel(r.metrics.confidence)],
    ['Method', (r) => methodName(r.metrics.method)],
    ['Observations', (r) => integer(r.metrics.observations)],
    ['Annualized return', (r) => pct(r.metrics.annualized_return)],
    ['Annualized volatility', (r) => pct(r.metrics.volatility)],
    ['Value at risk', (r) => pct(r.metrics.var)],
    ['Expected shortfall', (r) => pct(r.metrics.expected_shortfall)],
    [t('Maximum drawdown'), (r) => pct(r.metrics.max_drawdown)],
    [t('Worst period'), (r) => pct(r.metrics.worst_period)],
    [t('Sortino ratio'), (r) => num(r.metrics.sortino_ratio)],
    [t('Calmar ratio'), (r) => num(r.metrics.calmar_ratio)],
    ['Diversification ratio', (r) => num(r.metrics.diversification_ratio)],
    ['Breaches (expected)', (r) => `${r.metrics.exceedances} (${num(r.metrics.expected_exceedances, 1)})`],
    ['Kupiec p-value', (r) => (isNumber(r.metrics.kupiec_p_value) ? pValue(r.metrics.kupiec_p_value) : DASH)],
    ['Basel traffic light', (r) => zoneName(r.metrics.zone)],
  ];

  function updateCompareControls() {
    const count = state.compare.size;
    $('#compare').disabled = count < 2 || count > 4;
    $('#compare-hint').textContent =
      count < 2 ? t('Tick two to four analyses to compare them side by side.') : count > 4 ? t('Compare at most four at a time.') : t('{n} selected.', { n: count });
  }

  async function compareSelected() {
    const ids = state.runs.filter((r) => state.compare.has(r.id)).map((r) => r.id);
    setStatus(t('Comparing…'));
    try {
      const { runs } = await api.compareRuns(ids);
      const table = $('#table-compare');
      table.replaceChildren();
      const heads = [element('td'), ...runs.map((r) => element('th', { text: r.name, attributes: { scope: 'col' } }))];
      table.appendChild(element('thead', {}, [element('tr', {}, heads)]));
      const body = element('tbody');
      for (const [label, format] of COMPARE_ROWS) {
        body.appendChild(element('tr', {}, [element('th', { text: t(label), attributes: { scope: 'row' } }), ...runs.map((r) => element('td', { text: format(r) }))]));
      }
      table.appendChild(body);
      const panel = $('#compare-panel');
      panel.hidden = false;
      setStatus('');
      panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
      panel.focus();
    } catch (error) {
      fail(error);
    }
  }

  async function loadHistory() {
    try {
      state.runs = await api.listRuns();
      renderHistory();
    } catch (error) {
      fail(error);
    }
  }

  function datasetFromRun(run, request) {
    if (run.kind === 'portfolio') {
      const names = Object.keys(request.assets);
      return {
        id: 'portfolio', portfolio: true, simulated: false, title: run.name, kind: request.kind, assets: request.assets,
        dates: request.dates || null, weights: request.weights || equalWeights(names), scenarios: request.scenarios || [],
      };
    }
    const kind = request.prices ? 'prices' : 'returns';
    return { id: 'upload', simulated: false, title: run.name, kind, values: request[kind], dates: request.dates || null, scenarios: request.scenarios || [] };
  }

  async function openRun(id) {
    setStatus(t('Opening…'));
    try {
      const { run: meta, request: saved, result } = await api.openRun(id);
      setMode(meta.kind === 'portfolio' ? 'portfolio' : 'single');
      setDataset(datasetFromRun(meta, saved));
      const confidence = $('#confidence');
      confidence.value = saved.confidence;
      $('#confidence-out').textContent = confidenceLabel(saved.confidence);
      $('#method').value = saved.method;
      $('#method-hint').textContent = methodHint(saved.method);
      $('#window').value = saved.window;
      renderWeights();
      state.request += 1; // a calculation still in flight must not replace this result
      $('#results').hidden = false;
      render(result);
      state.savedRun = meta;
      $('#run-name').value = meta.name;
      updateSaveControls();
      setStatus('');
      $('#results').scrollIntoView({ behavior: 'smooth', block: 'start' });
    } catch (error) {
      fail(error);
    }
  }

  async function saveRun(event) {
    event.preventDefault();
    if (!state.dataset) return;
    const name = $('#run-name').value.trim();
    if (!name) return;
    setStatus(t('Saving…'));
    try {
      const meta = await api.saveRun(name, state.dataset, settings());
      state.runs = [meta, ...state.runs];
      state.savedRun = meta;
      updateSaveControls();
      setStatus(t('Saved as “{name}”.', { name }));
    } catch (error) {
      fail(error);
    }
  }

  async function downloadReport(id) {
    try {
      saveBlob(await api.reportBlob(id), `risk_report_${id.slice(0, 8)}.html`);
    } catch (error) {
      fail(error);
    }
  }

  async function removeRun(id) {
    const item = state.runs.find((r) => r.id === id);
    if (!item || !window.confirm(t('Delete “{name}”?', { name: item.name }))) return;
    try {
      await api.deleteRun(id);
      state.runs = state.runs.filter((r) => r.id !== id);
      if (state.savedRun && state.savedRun.id === id) state.savedRun = null;
      updateSaveControls();
    } catch (error) {
      fail(error);
    }
  }

  // ---- language

  // Everything that was written into the page from code is written again in the other language
  function applyLanguage() {
    window.I18n.applyDocument();
    document.documentElement.lang = window.I18n.lang;
    $('#lang').textContent = isTurkish() ? 'English' : 'Türkçe';
    $('#lang').setAttribute('lang', isTurkish() ? 'en' : 'tr');
    const selected = $('#scenario').value;
    for (const option of $('#scenario').options) {
      const scenario = state.scenarios.find((item) => item.id === option.value);
      if (scenario) option.textContent = t(scenario.title);
    }
    $('#scenario').value = selected;
    describeScenario();
    $('#method-hint').textContent = methodHint($('#method').value);
    $('#confidence-out').textContent = confidenceLabel(confidenceValue());
    setMode(state.mode);
    if (state.datasets.portfolio) updateWeightsHint();
    updateCompareControls();
    $('#compare-panel').hidden = true;
    renderHistory();
    setStatus('');
    if (state.result) render(state.result);
  }

  function chooseLanguage(lang) {
    window.I18n.setLang(lang);
    applyLanguage();
  }

  // ---- start up

  // Loads what the server has. Runs again after a token was entered.
  async function start() {
    let config = { limits: { assets: 10 } };
    try {
      if (api.config) config = await api.config();
      state.scenarios = await api.scenarios();
    } catch (error) {
      fail(error);
      return;
    }
    $('#token-form').hidden = true;
    setStatus('');
    state.limits = config.limits;
    state.marketSource = config.market_data || null;
    updateMarketField();
    $('#max-assets').textContent = config.limits.assets;

    const scenarioSelect = $('#scenario');
    scenarioSelect.replaceChildren();
    for (const scenario of state.scenarios) scenarioSelect.appendChild(element('option', { text: t(scenario.title), attributes: { value: scenario.id } }));
    describeScenario();

    if (!api.staticMode) {
      $('#history-panel').hidden = false;
      await loadHistory();
    }
    if (!state.dataset) await chooseScenario(chosenScenario());
    else await run();
  }

  const chosenScenario = () => state.scenarios.find((s) => s.id === $('#scenario').value);
  const describeScenario = () => {
    $('#scenario-hint').textContent = chosenScenario() ? t(chosenScenario().description) : '';
  };

  function init() {
    window.I18n.applyDocument();
    document.documentElement.lang = window.I18n.lang;
    $('#lang').textContent = isTurkish() ? 'English' : 'Türkçe';
    $('#lang').setAttribute('lang', isTurkish() ? 'en' : 'tr');
    $('#lang').addEventListener('click', () => chooseLanguage(isTurkish() ? 'en' : 'tr'));
    const fixed = Boolean(api.staticMode && api.fixed);
    if (fixed) document.body.classList.add('report');
    if (api.staticMode) {
      $('#file').closest('.field').hidden = true;
      $('#mode-field').hidden = true;
      $('#report').remove();
      $('#save-form').remove();
    }
    if (api.confidences) {
      const slider = $('#confidence');
      slider.min = 0;
      slider.max = api.confidences.length - 1;
      slider.step = 1;
      slider.value = api.confidences.reduce((best, c, i, all) => (Math.abs(c - 0.95) < Math.abs(all[best] - 0.95) ? i : best), 0);
    }
    if (api.window) {
      $('#window').value = api.window;
      $('#window').closest('.field').hidden = true;
    }
    if (!fixed) $('#confidence-out').textContent = confidenceLabel(confidenceValue());
    setMode('single');

    const showMethodHint = () => {
      $('#method-hint').textContent = methodHint($('#method').value);
    };
    showMethodHint();

    $('#scenario').addEventListener('change', () => {
      describeScenario();
      chooseScenario(chosenScenario());
    });
    $('#controls').addEventListener('submit', (event) => event.preventDefault());
    $('#confidence').addEventListener('input', () => {
      $('#confidence-out').textContent = confidenceLabel(confidenceValue());
      scheduleRun();
    });
    $('#method').addEventListener('change', () => {
      showMethodHint();
      scheduleRun(0);
    });
    $('#window').addEventListener('change', () => scheduleRun(0));
    $('#download').addEventListener('click', download);
    document.querySelectorAll('input[name="kind"]').forEach((radio) =>
      radio.addEventListener('change', () => {
        if (state.dataset && state.dataset.id === 'upload' && $('#file').files.length) $('#file').dispatchEvent(new Event('change'));
      }),
    );
    $('#file').addEventListener('change', async () => {
      const file = $('#file').files[0];
      if (!file) return;
      try {
        const kind = document.querySelector('input[name="kind"]:checked').value;
        setDataset(parseCsv(await file.text(), kind));
        await run();
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    if (fixed) return;

    $('#market-load').addEventListener('click', loadMarket);
    $('#symbols').addEventListener('keydown', (event) => {
      if (event.key === 'Enter') {
        event.preventDefault();
        loadMarket();
      }
    });

    // portfolio
    document.querySelectorAll('input[name="mode"]').forEach((radio) => radio.addEventListener('change', () => switchMode(radio.value)));
    $('#portfolio-sample').addEventListener('click', loadSamplePortfolio);
    $('#portfolio-file').addEventListener('change', async () => {
      const file = $('#portfolio-file').files[0];
      if (!file) return;
      try {
        const kind = document.querySelector('input[name="portfolio-kind"]:checked').value;
        setDataset(parsePortfolioCsv(await file.text(), kind, state.limits.assets));
        renderWeights();
        await run();
      } catch (error) {
        setStatus(error.message, true);
      }
    });
    document.querySelectorAll('input[name="portfolio-kind"]').forEach((radio) =>
      radio.addEventListener('change', () => {
        if ($('#portfolio-file').files.length) $('#portfolio-file').dispatchEvent(new Event('change'));
      }),
    );
    $('#weights').addEventListener('change', () => {
      updateWeightsHint();
      const weights = readWeights();
      if (Object.values(weights).some((v) => !Number.isFinite(v))) return;
      state.datasets.portfolio.weights = weights;
      scheduleRun(0);
    });
    $('#weights-equal').addEventListener('click', () => {
      const dataset = state.datasets.portfolio;
      dataset.weights = equalWeights(Object.keys(dataset.assets));
      renderWeights();
      scheduleRun(0);
    });

    // saved runs
    $('#save-form').addEventListener('submit', saveRun);
    $('#report').addEventListener('click', () => state.savedRun && downloadReport(state.savedRun.id));
    $('#whatif-add').addEventListener('click', addScenario);
    $('#table-whatif').addEventListener('change', () => {
      if (!state.dataset) return;
      state.dataset.scenarios = readScenarios();
      scheduleRun(250);
    });
    $('#table-whatif').addEventListener('click', (event) => {
      const button = event.target.closest('button[data-remove]');
      if (!button || !state.dataset) return;
      state.dataset.scenarios = readScenarios().filter((scenario, i) => i !== Number(button.dataset.remove));
      scheduleRun(0);
    });
    $('#compare').addEventListener('click', compareSelected);
    $('#compare-close').addEventListener('click', () => {
      $('#compare-panel').hidden = true;
    });
    $('#history').addEventListener('change', (event) => {
      const box = event.target.closest('input[data-compare]');
      if (!box) return;
      if (box.checked) state.compare.add(box.dataset.compare);
      else state.compare.delete(box.dataset.compare);
      updateCompareControls();
    });
    $('#history').addEventListener('click', (event) => {
      const button = event.target.closest('button[data-action]');
      if (!button) return;
      const id = button.closest('li').dataset.id;
      if (button.dataset.action === 'open') openRun(id);
      else if (button.dataset.action === 'report') downloadReport(id);
      else removeRun(id);
    });

    // access token
    $('#token-form').addEventListener('submit', (event) => {
      event.preventDefault();
      setToken($('#token').value.trim());
      $('#token').value = '';
      start();
    });
  }

  init();
  start();
})();
