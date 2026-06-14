/**
 * D3.js 趋势曲线渲染与pH老化预测图
 */
const TrendCharts = (() => {

  const METRIC_CONFIG = {
    temp:   { label: '温度', unit: '℃', color: '#f87171', areaColor: 'rgba(248,113,113,.2)',
              key: 'temp_avg', max_key: 'temp_max', min_key: 'temp_min' },
    humi:   { label: '湿度', unit: '%', color: '#60a5fa', areaColor: 'rgba(96,165,250,.2)',
              key: 'humi_avg', max_key: 'humi_max', min_key: 'humi_min' },
    mold:   { label: '霉菌孢子', unit: 'CFU/m³', color: '#34d399', areaColor: 'rgba(52,211,153,.2)',
              key: 'mold_avg', max_key: null, min_key: null, logScale: true },
    light:  { label: '光照', unit: 'lux', color: '#fbbf24', areaColor: 'rgba(251,191,36,.2)',
              key: 'light_avg', max_key: 'light_max', min_key: null },
  };

  function _parseTs(v) {
    if (v instanceof Date) return v;
    if (typeof v === 'number') {
      if (v > 1e12) v /= 1000;
      return new Date(v * 1000);
    }
    const s = String(v).replace(' ', 'T');
    const d = new Date(s);
    return isNaN(d.getTime()) ? new Date(v) : d;
  }

  function renderTrend(containerSel, data, metricKey) {
    const el = typeof containerSel === 'string'
      ? document.querySelector(containerSel) : containerSel;
    if (!el) return;
    const cfg = METRIC_CONFIG[metricKey] || METRIC_CONFIG.temp;

    const selection = d3.select(el);
    selection.selectAll('*').on('.chart', null).on('.brush', null).on('.drag', null);
    selection.selectAll('*').interrupt();

    let svg = selection.select('svg.abm-chart');
    if (svg.empty()) {
      svg = selection.append('svg').attr('class', 'abm-chart').style('display', 'block');
    }
    svg.selectAll('*').remove();

    const rows = (data || []).map(r => ({
      t: _parseTs(r.ts_bucket || r.day || r.timestamp),
      v: +r[cfg.key],
      hi: cfg.max_key ? +r[cfg.max_key] : null,
      lo: cfg.min_key ? +r[cfg.min_key] : null,
    })).filter(r => !isNaN(r.t.getTime()) && isFinite(r.v));

    if (!rows.length) {
      svg.attr('width', 10).attr('height', 10).style('display', 'none');
      let empty = selection.select('div.abm-empty');
      if (empty.empty()) {
        empty = selection.append('div').attr('class', 'abm-empty')
          .style('color', '#64748b').style('font-size', '12px')
          .style('text-align', 'center').style('padding', '60px 0');
      }
      empty.text('暂无趋势数据');
      return;
    }
    selection.selectAll('div.abm-empty').remove();

    const rect = el.getBoundingClientRect();
    const W = rect.width || 600, H = rect.height || 240;
    const margin = { top: 16, right: 28, bottom: 30, left: 48 };
    const iw = W - margin.left - margin.right;
    const ih = H - margin.top - margin.bottom;

    svg.attr('width', W).attr('height', H).style('display', 'block');

    const gradId = 'g-' + (el.__chartGradId || (el.__chartGradId = Math.random().toString(36).slice(2, 8)));
    const defs = svg.append('defs');
    const grad = defs.append('linearGradient')
      .attr('id', gradId).attr('x1', '0').attr('x2', '0').attr('y1', '0').attr('y2', '1');
    grad.append('stop').attr('offset', '0%').attr('stop-color', cfg.color).attr('stop-opacity', .45);
    grad.append('stop').attr('offset', '100%').attr('stop-color', cfg.color).attr('stop-opacity', .0);

    const x = d3.scaleTime()
      .domain(d3.extent(rows, d => d.t))
      .range([0, iw]);
    const vals = rows.flatMap(r => [r.v, r.hi, r.lo].filter(v => v !== null && isFinite(v)));
    const y = (cfg.logScale ? d3.scaleLog() : d3.scaleLinear())
      .domain([Math.max(0.1, d3.min(vals) * 0.95), d3.max(vals) * 1.08 || 1])
      .nice()
      .range([ih, 0]);

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    g.append('g').attr('class', 'grid')
      .attr('transform', `translate(0,${ih})`)
      .call(d3.axisBottom(x).ticks(5).tickSize(-ih).tickFormat(() => ''))
      .selectAll('line').attr('stroke', 'rgba(51,65,85,.5)').attr('stroke-dasharray', '3,3');
    g.selectAll('.grid .domain').remove();

    g.append('g').attr('class', 'grid')
      .call(d3.axisLeft(y).ticks(5).tickSize(-iw).tickFormat(() => ''))
      .selectAll('line').attr('stroke', 'rgba(51,65,85,.5)').attr('stroke-dasharray', '3,3');
    g.selectAll('.grid .domain').remove();

    g.append('g')
      .attr('transform', `translate(0,${ih})`)
      .call(d3.axisBottom(x).ticks(6))
      .selectAll('text').attr('fill', '#94a3b8').style('font-size', '10px');
    g.selectAll('.domain, .tick line').attr('stroke', '#475569');

    g.append('g')
      .call(d3.axisLeft(y).ticks(5).tickFormat(d =>
        cfg.logScale && d >= 1000 ? (d / 1000) + 'k' : d
      ))
      .selectAll('text').attr('fill', '#94a3b8').style('font-size', '10px');
    g.selectAll('.domain, .tick line').attr('stroke', '#475569');

    const area = d3.area()
      .x(d => x(d.t))
      .y0(ih)
      .y1(d => y(Math.max(y.domain()[0], d.v)))
      .curve(d3.curveMonotoneX);
    g.append('path')
      .datum(rows)
      .attr('fill', `url(#${gradId})`)
      .attr('d', area);

    if (cfg.max_key && cfg.min_key && rows[0].hi !== null && rows[0].lo !== null) {
      const band = d3.area()
        .x(d => x(d.t))
        .y0(d => y(d.lo))
        .y1(d => y(d.hi))
        .curve(d3.curveMonotoneX);
      g.append('path').datum(rows)
        .attr('fill', cfg.areaColor).attr('d', band);
    }

    const line = d3.line()
      .x(d => x(d.t))
      .y(d => y(d.v))
      .curve(d3.curveMonotoneX);
    g.append('path').datum(rows)
      .attr('fill', 'none')
      .attr('stroke', cfg.color)
      .attr('stroke-width', 2)
      .attr('d', line);

    const last = rows[rows.length - 1];
    g.append('circle').attr('r', 4)
      .attr('cx', x(last.t)).attr('cy', y(last.v))
      .attr('fill', cfg.color).attr('stroke', '#fff').attr('stroke-width', 1.2);

    g.append('text')
      .attr('x', x(last.t) - 4).attr('y', y(last.v) - 8)
      .attr('text-anchor', 'end')
      .attr('fill', cfg.color).style('font-size', '11px').style('font-weight', '700')
      .text(last.v.toFixed(cfg.logScale ? 0 : 1) + cfg.unit);

    g.append('text')
      .attr('x', 0).attr('y', -4)
      .attr('fill', '#e2e8f0').style('font-size', '10px').style('font-weight', '600')
      .text(`${cfg.label} (${cfg.unit})`);

    const tip = g.append('g').style('display', 'none');
    tip.append('line').attr('y1', 0).attr('y2', ih)
      .attr('stroke', '#94a3b8').attr('stroke-dasharray', '3,3');
    const tipBox = tip.append('g');
    tipBox.append('rect')
      .attr('rx', 4).attr('ry', 4)
      .attr('fill', 'rgba(15,23,42,.95)').attr('stroke', '#334155');
    const tipText = tipBox.append('text').attr('fill', '#e2e8f0').style('font-size', '11px')
      .attr('x', 8).attr('y', 18);

    const bisect = d3.bisector(d => d.t).center;
    svg.append('rect')
      .attr('class', 'abm-event-capture')
      .attr('x', margin.left).attr('y', margin.top)
      .attr('width', iw).attr('height', ih)
      .attr('fill', 'transparent')
      .on('mouseenter.chart', () => tip.style('display', null))
      .on('mouseleave.chart', () => tip.style('display', 'none'))
      .on('mousemove.chart', (event) => {
        const [mx] = d3.pointer(event);
        const xm = mx - margin.left;
        const tm = x.invert(xm);
        const i = bisect(rows, tm);
        const d = rows[Math.max(0, Math.min(rows.length - 1, i))];
        if (!d) return;
        tip.attr('transform', `translate(${margin.left + x(d.t)}, ${margin.top})`);
        tip.select('line').attr('x1', 0).attr('x2', 0);
        const lines = [
          d3.timeFormat('%Y-%m-%d %H:%M')(d.t),
          `${cfg.label}: ${d.v.toFixed(cfg.logScale ? 0 : 2)} ${cfg.unit}`,
        ];
        if (d.hi !== null) lines.push(`最高/最低: ${d.hi.toFixed(1)} / ${d.lo?.toFixed(1)}`);
        const w = Math.max(120, d3.max(lines, l => l.length * 7 + 16));
        const h = lines.length * 16 + 8;
        let bx = 8;
        if (x(d.t) + w + 12 > iw) bx = -w - 8;
        tipBox.attr('transform', `translate(${bx}, 10)`);
        tipBox.select('rect').attr('width', w).attr('height', h);
        tipText.selectAll('tspan').data(lines).join('tspan')
          .attr('x', 8).attr('dy', (_, i) => i ? 14 : 0)
          .text(s => s);
      });
  }

  function renderPhPrediction(containerSel, current, d30, d90, d180, d365, historyRows) {
    const el = typeof containerSel === 'string'
      ? document.querySelector(containerSel) : containerSel;
    if (!el) return;

    const selection = d3.select(el);
    selection.selectAll('*').on('.chart', null).on('.brush', null).on('.drag', null);
    selection.selectAll('*').interrupt();

    let svg = selection.select('svg.abm-chart');
    if (svg.empty()) {
      svg = selection.append('svg').attr('class', 'abm-chart');
    }
    svg.selectAll('*').remove();
    selection.selectAll('div.abm-empty').remove();

    const rect = el.getBoundingClientRect();
    const W = rect.width || 460, H = rect.height || 240;
    const margin = { top: 20, right: 28, bottom: 34, left: 44 };
    const iw = W - margin.left - margin.right;
    const ih = H - margin.top - margin.bottom;

    const today = new Date();
    const hist = (historyRows || []).map(r => ({
      t: _parseTs(r.day || r.timestamp),
      ph: +(r.ph_avg ?? r.ph_value),
    })).filter(r => !isNaN(r.t.getTime()) && isFinite(r.ph));

    const forecast = [
      { t: today, ph: +current, type: 'now' },
      { t: new Date(+today + 30 * 864e5), ph: +d30, type: 'fc' },
      { t: new Date(+today + 90 * 864e5), ph: +d90, type: 'fc' },
      { t: new Date(+today + 180 * 864e5), ph: +d180, type: 'fc' },
      { t: new Date(+today + 365 * 864e5), ph: +d365, type: 'fc' },
    ];

    const allPoints = hist.concat(forecast);
    if (!allPoints.length) return;

    svg.attr('width', W).attr('height', H);

    const x = d3.scaleTime()
      .domain(d3.extent(allPoints, d => d.t))
      .range([0, iw]);
    const ymin = 4.5, ymax = 7.5;
    const y = d3.scaleLinear().domain([ymin, ymax]).range([ih, 0]);

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`);

    const zones = [
      { y0: 6.5, y1: ymax, fill: 'rgba(22,163,74,.08)', label: '安全', color: '#16a34a' },
      { y0: 6.0, y1: 6.5, fill: 'rgba(202,138,4,.08)', label: '轻度酸化', color: '#ca8a04' },
      { y0: 5.5, y1: 6.0, fill: 'rgba(234,88,12,.08)', label: '中度酸化', color: '#ea580c' },
      { y0: ymin, y1: 5.5, fill: 'rgba(220,38,38,.08)', label: '严重酸化', color: '#dc2626' },
    ];
    zones.forEach(z => {
      g.append('rect')
        .attr('x', 0).attr('width', iw)
        .attr('y', y(z.y1)).attr('height', Math.max(0, y(z.y0) - y(z.y1)))
        .attr('fill', z.fill);
      g.append('text')
        .attr('x', iw - 4).attr('y', y((z.y0 + z.y1) / 2))
        .attr('dy', '0.35em').attr('text-anchor', 'end')
        .attr('fill', z.color).style('font-size', '9px').attr('opacity', 0.8)
        .text(z.label);
    });

    [5.5, 6.0, 6.5, 7.0].forEach(v => {
      g.append('line')
        .attr('x1', 0).attr('x2', iw)
        .attr('y1', y(v)).attr('y2', y(v))
        .attr('stroke', 'rgba(51,65,85,.6)').attr('stroke-dasharray', '3,3');
    });

    g.append('g').attr('transform', `translate(0,${ih})`)
      .call(d3.axisBottom(x).ticks(5))
      .selectAll('text').attr('fill', '#94a3b8').style('font-size', '10px');
    g.selectAll('.domain, .tick line').attr('stroke', '#475569');

    g.append('g')
      .call(d3.axisLeft(y).ticks(6).tickFormat(d => d.toFixed(1)))
      .selectAll('text').attr('fill', '#94a3b8').style('font-size', '10px');
    g.selectAll('.domain, .tick line').attr('stroke', '#475569');

    if (hist.length > 1) {
      const histLine = d3.line()
        .x(d => x(d.t)).y(d => y(d.ph)).curve(d3.curveMonotoneX);
      g.append('path').datum(hist)
        .attr('d', histLine)
        .attr('fill', 'none').attr('stroke', '#60a5fa')
        .attr('stroke-width', 1.8).attr('opacity', 0.85);
      g.append('text').attr('x', 4).attr('y', -2)
        .attr('fill', '#60a5fa').style('font-size', '10px')
        .text('● 历史pH');
    }

    const fcLine = d3.line()
      .x(d => x(d.t)).y(d => y(d.ph)).curve(d3.curveCatmullRom.alpha(0.5));
    g.append('path').datum(forecast)
      .attr('d', fcLine)
      .attr('fill', 'none').attr('stroke', '#f59e0b')
      .attr('stroke-width', 2).attr('stroke-dasharray', '6,3');
    g.append('text').attr('x', 90).attr('y', -2)
      .attr('fill', '#f59e0b').style('font-size', '10px')
      .text('● 预测pH');

    forecast.forEach((d, i) => {
      g.append('circle')
        .attr('cx', x(d.t)).attr('cy', y(d.ph)).attr('r', i === 0 ? 5 : 4)
        .attr('fill', i === 0 ? '#22d3ee' : '#f59e0b')
        .attr('stroke', '#fff').attr('stroke-width', 1.2);
      const label = i === 0 ? `现在 ${d.ph.toFixed(2)}`
        : i === 1 ? `30天 ${d.ph.toFixed(2)}`
        : i === 2 ? `90天 ${d.ph.toFixed(2)}`
        : i === 3 ? `180天 ${d.ph.toFixed(2)}`
        : `1年 ${d.ph.toFixed(2)}`;
      g.append('text')
        .attr('x', x(d.t)).attr('y', y(d.ph) - 10)
        .attr('text-anchor', i === forecast.length - 1 ? 'end' : 'middle')
        .attr('fill', '#e2e8f0').style('font-size', '10px').style('font-weight', '600')
        .text(label);
    });
  }

  function renderMiniPh(containerSel, rows) {
    const el = typeof containerSel === 'string'
      ? document.querySelector(containerSel) : containerSel;
    if (!el) return;

    const selection = d3.select(el);
    selection.selectAll('*').on('.chart', null).on('.brush', null).on('.drag', null);
    selection.selectAll('*').interrupt();

    let svg = selection.select('svg.abm-chart');
    if (svg.empty()) {
      svg = selection.append('svg').attr('class', 'abm-chart');
    }
    svg.selectAll('*').remove();

    const data = (rows || []).map(r => ({
      t: _parseTs(r.day || r.timestamp),
      ph: +(r.ph_avg ?? r.ph_value ?? 7),
    })).filter(r => !isNaN(r.t.getTime()) && isFinite(r.ph));

    if (!data.length) {
      svg.attr('width', 10).attr('height', 10).style('display', 'none');
      let empty = selection.select('div.abm-empty');
      if (empty.empty()) {
        empty = selection.append('div').attr('class', 'abm-empty')
          .style('color', '#64748b').style('font-size', '11px')
          .style('padding', '40px 0').style('text-align', 'center');
      }
      empty.text('暂无pH历史数据');
      return;
    }
    selection.selectAll('div.abm-empty').remove();

    const rect = el.getBoundingClientRect();
    const W = rect.width || 400, H = rect.height || 160;
    const m = { top: 10, right: 10, bottom: 22, left: 34 };
    svg.attr('width', W).attr('height', H).style('display', 'block');
    const g = svg.append('g').attr('transform', `translate(${m.left},${m.top})`);
    const iw = W - m.left - m.right, ih = H - m.top - m.bottom;
    const x = d3.scaleTime().domain(d3.extent(data, d => d.t)).range([0, iw]);
    const y = d3.scaleLinear().domain([4.5, 7.5]).range([ih, 0]);

    [5.5, 6.0, 6.5].forEach(v => {
      g.append('line').attr('x1', 0).attr('x2', iw).attr('y1', y(v)).attr('y2', y(v))
        .attr('stroke', 'rgba(51,65,85,.5)').attr('stroke-dasharray', '2,2');
    });
    g.append('g').attr('transform', `translate(0,${ih})`)
      .call(d3.axisBottom(x).ticks(4)).selectAll('text')
      .attr('fill', '#94a3b8').style('font-size', '9px');
    g.append('g').call(d3.axisLeft(y).ticks(4).tickFormat(v => v.toFixed(1)))
      .selectAll('text').attr('fill', '#94a3b8').style('font-size', '9px');
    g.selectAll('.domain, .tick line').attr('stroke', '#475569');

    const area = d3.area().x(d => x(d.t)).y0(ih).y1(d => y(d.ph)).curve(d3.curveMonotoneX);
    g.append('path').datum(data).attr('d', area).attr('fill', 'rgba(96,165,250,.2)');

    const line = d3.line().x(d => x(d.t)).y(d => y(d.ph)).curve(d3.curveMonotoneX);
    g.append('path').datum(data).attr('d', line).attr('fill', 'none')
      .attr('stroke', '#60a5fa').attr('stroke-width', 1.8);

    const last = data[data.length - 1];
    g.append('circle').attr('cx', x(last.t)).attr('cy', y(last.ph)).attr('r', 3)
      .attr('fill', '#60a5fa').attr('stroke', '#fff').attr('stroke-width', 1);
  }

  return { renderTrend, renderPhPrediction, renderMiniPh, METRIC_CONFIG };
})();
