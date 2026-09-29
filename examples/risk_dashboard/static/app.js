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

  const SVG_NS = 'http://www.w3.org/2000/svg';
  const MAX_ROWS = 5000;
  const MINUS = '−';
  const DASH = '—';
  const METHOD_HINTS = {
    historical: 'The empirical quantile of the window. No distribution assumed; noisy in the far tail.',
    parametric: 'A normal distribution fitted to the window. Smooth, but understates fat tails.',
    cornish_fisher: 'A normal quantile corrected for skewness and kurtosis. Suits moderately fat tails.',
  };
  const METHOD_NAMES = { historical: 'historical', parametric: 'parametric', cornish_fisher: 'Cornish-Fisher' };

  const $ = (selector) => document.querySelector(selector);

  // ------------------------------------------------------------------------------------------------------------------
  // API. The static export replaces this with precomputed results by defining window.RiskApi.
  // ------------------------------------------------------------------------------------------------------------------

  async function requestJson(url, options) {
    let response;
    try {
      response = await fetch(url, options);
    } catch (error) {
      throw new Error('Could not reach the server. Is it still running?');
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch (error) {
      /* not JSON */
    }
    if (!response.ok) {
      throw new Error((payload && payload.error) || `The server answered with status ${response.status}`);
    }
    return payload;
  }

  const liveApi = {
    staticMode: false,
    scenarios: () => requestJson('/api/scenarios'),
    async loadScenario(id, title) {
      const sample = await requestJson(`/api/sample?scenario=${encodeURIComponent(id)}`);
      return { id, title, simulated: true, kind: 'returns', dates: sample.dates, values: sample.returns };
    },
    analyze(dataset, settings) {
      const body = { confidence: settings.confidence, method: settings.method, window: settings.window };
      body[dataset.kind] = dataset.values;
      if (dataset.dates) body.dates = dataset.dates;
      return requestJson('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    },
  };
  const api = window.RiskApi || liveApi;

  // ------------------------------------------------------------------------------------------------------------------
  // Formatting: one convention throughout. Percentages to two decimals, ratios to two, a true minus sign.
  // ------------------------------------------------------------------------------------------------------------------

  const isNumber = (v) => typeof v === 'number' && Number.isFinite(v);
  const signed = (text) => text.replace(/^-(0\.0+)$/, '$1').replace('-', MINUS);
  const pct = (v, digits = 2) => (isNumber(v) ? `${signed((v * 100).toFixed(digits))}%` : DASH);
  const num = (v, digits = 2) => (isNumber(v) ? signed(v.toFixed(digits)) : DASH);
  const pValue = (p) => (p < 0.001 ? '<0.001' : p.toFixed(3));
  const confidenceLabel = (c) => `${(c * 100).toFixed(1)}%`;
  const integer = (v) => Math.round(v).toLocaleString('en-US');

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

  function verdictSentence(result) {
    const { test, ind, expected, afterBreach, afterQuiet, tooMany } = breachFacts(result);
    const light = test.traffic_light;
    const count = `${test.exceedances} breaches in ${integer(test.observations)} periods against ${expected.toFixed(1)} expected`;
    const clauses = [];
    if (test.reject) {
      clauses.push(`${count}: the model ${tooMany ? 'understates' : 'overstates'} risk (Kupiec p ${pValue(test.p_value)}).`);
    } else {
      clauses.push(`${count}: consistent with the confidence level (Kupiec p ${pValue(test.p_value)}).`);
    }
    if (ind.independence_reject && isNumber(afterBreach) && isNumber(afterQuiet)) {
      clauses.push(`Breaches cluster: the chance of one the day after a breach is ${pct(afterBreach, 0)}, against ${pct(afterQuiet, 0)} otherwise.`);
    } else if (test.exceedances > 0) {
      clauses.push('No evidence that breaches cluster in time.');
    }
    if (light.zone !== 'green') clauses.push(`Basel traffic light: ${light.zone}.`);
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
      ['Annualized return', pct(summary.annualized_return), 'compound'],
      ['Annualized volatility', pct(summary.annualized_volatility), `${settings.periods_per_year} periods per year`],
      [`${conf} value at risk`, pct(risk.var), `one period, ${METHOD_NAMES[settings.method]}`],
      [`${conf} expected shortfall`, pct(risk.es), 'average return on breach periods'],
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
    fillTable($('#table-drawdown'), 'Drawdown and risk-adjusted return', [
      ['Maximum drawdown', pct(s.max_drawdown)],
      ['Worst period', pct(s.worst_period)],
      ['Sortino ratio', num(s.sortino_ratio)],
      ['Calmar ratio', num(s.calmar_ratio)],
      ['Ulcer index', pct(s.ulcer_index)],
    ]);
    fillTable($('#table-shape'), 'Shape of the distribution', [
      ['Skewness', num(s.skewness)],
      ['Excess kurtosis (0 = normal)', num(s.excess_kurtosis)],
      ['Best period', pct(s.best_period)],
      ['Downside deviation (annualized)', pct(s.downside_deviation)],
      ['Omega ratio', num(s.omega_ratio)],
    ]);
  }

  function resultCell(rejected) {
    return element('span', {
      className: `result ${rejected ? 'bad' : 'ok'}`,
      text: `${rejected ? '✕ Rejected' : '✓ Not rejected'}`,
    });
  }

  function renderTests(result) {
    const { test, ind, expected } = breachFacts(result);
    const light = test.traffic_light;
    const zoneClass = { green: 'ok', yellow: 'warn', red: 'bad' }[light.zone];
    const rows = [
      ['Kupiec', 'Number of breaches against the confidence level', `LR ${num(test.lr_statistic)}`, pValue(test.p_value), resultCell(test.reject)],
      [
        'Christoffersen independence',
        `Do breaches cluster? (${ind.n11} of ${ind.n10 + ind.n11} breaches were followed by another)`,
        `LR ${num(ind.independence_lr)}`,
        pValue(ind.independence_p_value),
        resultCell(ind.independence_reject),
      ],
      [
        'Conditional coverage',
        'Number and timing of breaches together',
        `LR ${num(ind.conditional_coverage_lr)}`,
        pValue(ind.conditional_coverage_p_value),
        resultCell(ind.conditional_coverage_reject),
      ],
      [
        'Basel traffic light',
        `${test.exceedances} breaches against ${expected.toFixed(1)} expected`,
        `F = ${pct(light.cumulative_probability, 3)}`,
        DASH,
        element('span', { className: `result ${zoneClass}`, text: light.zone[0].toUpperCase() + light.zone.slice(1) }),
      ],
    ];
    const table = $('#table-tests');
    table.replaceChildren();
    const head = element('tr', {}, ['Test', 'Statistic', 'p-value', 'Result'].map((h) => element('th', { text: h, attributes: { scope: 'col' } })));
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
    const tag = element('span', { className: `tag${simulated ? '' : ' real'}`, text: simulated ? 'Simulated data' : 'Your data' });
    const period = /^\d{4}-\d{2}-\d{2}$/.test(dates[0]) ? `${dates[0]} to ${dates[dates.length - 1]}` : `${dates.length} observations`;
    const label = simulated ? `${dataset.title} scenario` : 'Uploaded series';
    $('#provenance').replaceChildren(tag, `${label} · ${integer(result.summary.observations)} returns · ${period}`);
  }

  function renderNotes(result) {
    const notes = [
      `Rolling window of ${result.settings.window} periods, ${result.settings.periods_per_year} periods per year.`,
      'Every figure is a fraction of the portfolio, and losses are negative.',
      ...result.assumptions,
    ];
    const list = $('#notes');
    list.replaceChildren();
    for (const note of notes) list.appendChild(element('li', { text: note }));
  }

  function setTakeaway(id, parts) {
    const node = $(id);
    node.replaceChildren();
    for (const part of parts) {
      if (typeof part === 'string') node.append(part);
      else node.append(element('strong', { text: part.strong }));
    }
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Charts
  // ------------------------------------------------------------------------------------------------------------------

  function drawGrowth(container, result) {
    const { dates, growth: rawGrowth, drawdown } = result.series;
    const growth = rawGrowth.map((g) => (isNumber(g) ? g * 100 : g));
    const n = dates.length;
    const episode = result.worst_drawdown;
    const label = `Growth of 100 invested, ending at ${num(growth[n - 1], 1)}. Maximum drawdown ${pct(episode.depth, 1)}, from ${dates[episode.peak]} to ${dates[episode.trough]}.`;
    setTakeaway('#takeaway-growth', [
      'Ends at ',
      { strong: num(growth[n - 1], 1) },
      '. Deepest fall ',
      { strong: pct(episode.depth, 1) },
      ` from the peak on ${dates[episode.peak]} to the trough on ${dates[episode.trough]}.`,
    ]);

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
      axisTitle(svg, 'Growth of 100', { x: 14, y: (growthTop + growthBottom) / 2, rotate: true });

      const [dMin] = extent([drawdown]);
      const dScale = niceTicks(Math.min(dMin, -0.01), 0, 3);
      const yDd = linearScale(dScale.min, 0, ddBottom, ddTop);
      gridAndYAxis(svg, { left, right, top: ddTop, bottom: ddBottom, y: yDd, ticks: dScale.ticks, format: (v) => pct(v, 0) });
      svg.appendChild(svgEl('rect', { x: x0.toFixed(1), y: ddTop, width: Math.max(x1 - x0, 1).toFixed(1), height: ddBottom - ddTop, class: 'span' }));
      svg.appendChild(svgEl('path', { d: areaPath(drawdown, x, yDd, yDd(0).toFixed(1)), class: 'area' }));
      const labelX = Math.min(Math.max(x1, left + 60), right - 60);
      svg.appendChild(svgEl('text', { x: labelX.toFixed(1), y: (ddTop - 6).toFixed(1), 'text-anchor': 'middle', class: 'annotation' }, `Max drawdown ${pct(episode.depth, 1)}`));
      dateAxis(svg, { labels: dates, x, left, right, y: ddBottom });
      axisTitle(svg, 'Drawdown', { x: 14, y: (ddTop + ddBottom) / 2, rotate: true });

      container.appendChild(svg);
      attachCrosshair({
        container, svg, count: n, left, right, top: growthTop, bottom: ddBottom, x,
        describe: (i) => [[dates[i]], ['Growth of 100', num(growth[i], 1)], ['Drawdown', pct(drawdown[i], 1)]],
      });
    });
  }

  function drawVar(container, result) {
    const { dates, returns, var: varSeries, expected_shortfall: es, breach } = result.series;
    const n = dates.length;
    const conf = confidenceLabel(result.settings.confidence);
    const { test, expected } = breachFacts(result);
    const label = `Daily returns against the ${conf} value at risk forecast: ${test.exceedances} breaches in ${test.observations} periods, ${expected.toFixed(1)} expected.`;
    setTakeaway('#takeaway-var', [
      'The forecast was breached ',
      { strong: `${test.exceedances} times` },
      ` in ${integer(test.observations)} periods (${expected.toFixed(1)} expected at ${conf}). Each return is judged against the forecast made the period before.`,
    ]);

    registerChart(container, (width) => {
      const compact = width < 520;
      const left = compact ? 56 : 68;
      const right = width - 12;
      const legendItems = [
        { kind: 'bar', label: 'Return', className: 'bar' },
        { kind: 'bar', label: 'Breach', className: 'bar breach-key' },
        { label: `${conf} VaR` },
        { label: 'Expected shortfall', className: 'second dashed' },
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
      axisTitle(svg, 'Daily return', { x: 14, y: (top + bottom) / 2, rotate: true });
      legend(svg, legendItems, left, 14, right);

      container.appendChild(svg);
      attachCrosshair({
        container, svg, count: n, left, right, top, bottom, x,
        describe: (i) => {
          const lines = [[dates[i]], ['Return', pct(returns[i], 2)], ['VaR forecast', pct(varSeries[i], 2)], ['Expected shortfall', pct(es[i], 2)]];
          if (breach[i]) lines.push(['Breach']);
          return lines;
        },
      });
    });
  }

  function drawDistribution(container, result) {
    const headline = headlineRisk(result);
    const { centres, counts, normal_counts: normal, width: binWidth, outliers_below: below, outliers_above: above } = result.histogram;
    const label = `Histogram of returns with the normal curve, value at risk ${pct(headline.var, 2)} and expected shortfall ${pct(headline.es, 2)}.`;
    const conf = confidenceLabel(result.settings.confidence);
    setTakeaway('#takeaway-dist', [
      `Central 99% of returns${below + above ? ` (${below + above} outliers not shown)` : ''}. VaR `,
      { strong: pct(headline.var, 2) },
      ', expected shortfall ',
      { strong: pct(headline.es, 2) },
      ` at ${conf}.`,
    ]);

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
      axisTitle(svg, 'Daily return', { x: (left + right) / 2, y: bottom + 36 });
      axisTitle(svg, 'Days', { x: 12, y: (top + bottom) / 2, rotate: true });

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
      svg.appendChild(svgEl('text', { x: right - 64, y: top + 10, class: 'label' }, 'Normal fit'));
      container.appendChild(svg);
    });
  }

  function drawQq(container, result) {
    const { theoretical, sample } = result.qq;
    const alpha = 1 - result.settings.confidence;
    const conf = confidenceLabel(result.settings.confidence);
    const worst = sample[0];
    const normalWorst = theoretical[0];
    const label = `QQ plot of standardised returns against normal quantiles. The worst return is ${num(worst, 1)} standard deviations; a normal sample of this size would reach about ${num(normalWorst, 1)}.`;
    const fatter = worst < normalWorst - 0.5;
    setTakeaway('#takeaway-qq', [
      'Worst return is ',
      { strong: `${num(worst, 1)}σ` },
      `; a normal sample this size would reach about ${num(normalWorst, 1)}σ. `,
      fatter ? 'The left tail is fatter than a normal distribution allows.' : 'The left tail is in line with a normal distribution.',
    ]);
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
      axisTitle(svg, 'Normal quantile (standard deviations)', { x: (left + right) / 2, y: bottom + 36 });
      axisTitle(svg, 'Sample quantile', { x: 12, y: (top + bottom) / 2, rotate: true });
      svg.appendChild(svgEl('line', { x1: x(scale.min).toFixed(1), y1: y(scale.min).toFixed(1), x2: x(scale.max).toFixed(1), y2: y(scale.max).toFixed(1), class: 'line ref' }));
      sample.forEach((value, i) => {
        svg.appendChild(svgEl('circle', { cx: x(theoretical[i]).toFixed(1), cy: y(value).toFixed(1), r: 2.6, class: theoretical[i] <= tailCut ? 'dot tail' : 'dot' }));
      });
      svg.appendChild(svgEl('circle', { cx: right - 150, cy: bottom - 14, r: 3, class: 'dot tail' }));
      svg.appendChild(svgEl('text', { x: right - 142, y: bottom - 10, class: 'label' }, `Beyond the ${conf} VaR level`));
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
    if (!lines.length) throw new Error('The file is empty.');
    const delimiter = [',', ';', '\t'].find((d) => lines[0].includes(d)) || ',';
    let rows = lines.map((line) => line.split(delimiter).map((cell) => cell.trim().replace(/^"|"$/g, '')));
    const last = rows[0].length - 1;
    if (Number.isNaN(parseNumber(rows[0][Math.min(1, last)]))) rows = rows.slice(1); // header
    if (!rows.length) throw new Error('The file has no data rows.');
    if (rows.length > MAX_ROWS) throw new Error(`The file has ${rows.length} rows, the maximum is ${MAX_ROWS}.`);

    const dated = rows[0].length > 1;
    const values = [];
    const dates = [];
    rows.forEach((row, i) => {
      const value = parseNumber(dated ? row[1] : row[0]);
      if (!Number.isFinite(value)) throw new Error(`Row ${i + 1} does not contain a number.`);
      values.push(value);
      if (dated) {
        if (!/^\d{4}-\d{2}-\d{2}/.test(row[0])) throw new Error(`Row ${i + 1}: the first column must be a date such as 2024-03-29.`);
        dates.push(row[0].slice(0, 10));
      }
    });
    return { id: 'upload', simulated: false, kind, values, dates: dated ? dates : null };
  }

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

  function download() {
    if (!state.result) return;
    const blob = new Blob([resultToCsv(state.result)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = element('a', { attributes: { href: url, download: 'risk_series.csv' } });
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  // ------------------------------------------------------------------------------------------------------------------
  // Wiring
  // ------------------------------------------------------------------------------------------------------------------

  const state = { dataset: null, result: null, request: 0, timer: null };

  function setStatus(message, isError = false) {
    const status = $('#status');
    status.textContent = message;
    status.classList.toggle('error', isError);
  }

  // The static export only has results for a grid of confidence levels; the slider then steps through that grid
  const confidenceValue = () => (api.confidences ? api.confidences[Number($('#confidence').value)] : Number($('#confidence').value));

  function settings() {
    return { confidence: confidenceValue(), method: $('#method').value, window: Number($('#window').value) };
  }

  async function run() {
    if (!state.dataset) return;
    const ticket = ++state.request;
    const results = $('#results');
    results.classList.add('loading');
    setStatus('Calculating…');
    try {
      const result = await api.analyze(state.dataset, settings());
      if (ticket !== state.request) return; // a newer request superseded this one
      results.hidden = false;
      render(result);
      setStatus('');
    } catch (error) {
      if (ticket !== state.request) return;
      setStatus(error.message, true);
    } finally {
      if (ticket === state.request) results.classList.remove('loading');
    }
  }

  function scheduleRun(delay = 200) {
    clearTimeout(state.timer);
    state.timer = setTimeout(run, delay);
  }

  async function chooseScenario(scenario) {
    setStatus('Loading sample data…');
    try {
      state.dataset = await api.loadScenario(scenario.id, scenario.title);
      $('#file').value = '';
      await run();
    } catch (error) {
      setStatus(error.message, true);
    }
  }

  async function init() {
    const scenarioSelect = $('#scenario');
    const hint = $('#scenario-hint');
    let scenarios;
    try {
      scenarios = await api.scenarios();
    } catch (error) {
      setStatus(error.message, true);
      return;
    }
    for (const scenario of scenarios) scenarioSelect.appendChild(element('option', { text: scenario.title, attributes: { value: scenario.id } }));
    const chosen = () => scenarios.find((s) => s.id === scenarioSelect.value);
    const describe = () => {
      hint.textContent = chosen() ? chosen().description : '';
    };
    describe();

    if (api.staticMode) $('#file').closest('.field').hidden = true;
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
    $('#confidence-out').textContent = confidenceLabel(confidenceValue());

    const methodHint = () => {
      $('#method-hint').textContent = METHOD_HINTS[$('#method').value];
    };
    methodHint();

    scenarioSelect.addEventListener('change', () => {
      describe();
      chooseScenario(chosen());
    });
    $('#controls').addEventListener('submit', (event) => event.preventDefault());
    $('#confidence').addEventListener('input', () => {
      $('#confidence-out').textContent = confidenceLabel(confidenceValue());
      scheduleRun();
    });
    $('#method').addEventListener('change', () => {
      methodHint();
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
        state.dataset = parseCsv(await file.text(), kind);
        await run();
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    await chooseScenario(chosen());
  }

  init();
})();
