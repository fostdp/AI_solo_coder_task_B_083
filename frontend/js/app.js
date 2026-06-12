/**
 * 前端主应用控制器
 * 数据加载 + UI 与状态管理 + 交互 + 格口详情弹窗
 */
const API_BASE = location.protocol === 'file:' ? 'http://localhost:8000/api/v1' : '/api/v1';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));

async function api(path, opts = {}) {
  try {
    const res = await fetch(API_BASE + path, { credentials: 'omit', ...opts, headers: { 'Accept': 'application/json', ...(opts.headers || {}} });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    return await res.json();
  } catch (e) {
    return null;
  }
}

const ShelvesView = {
  currentFloor: 1,
  currentShelf: null,
  heatmapData: null,
  trendMetric: 'temp',
  trendData: [],
  renderer: null,
};

const DEFAULT_SHELVES = [
  { shelf_id: 'SH-A-01', shelf_name: 'A区一号书架·明版本草区', floor_num: 1, room_id: 'RM-101', rows_count: 6, cols_count: 8, total_slots: 48 },
  { shelf_id: 'SH-A-02', shelf_name: 'A区二号书架·明版医案区', floor_num: 1, room_id: 'RM-101', rows_count: 6, cols_count: 8, total_slots: 48 },
  { shelf_id: 'SH-A-03', shelf_name: 'A区三号书架·明版综合区', floor_num: 1, room_id: 'RM-101', rows_count: 6, cols_count: 8, total_slots: 48 },
  { shelf_id: 'SH-B-01', shelf_name: 'B区一号书架·清版本草区', floor_num: 1, room_id: 'RM-102', rows_count: 6, cols_count: 8, total_slots: 48 },
  { shelf_id: 'SH-B-02', shelf_name: 'B区二号书架·清版宫廷医案', floor_num: 1, room_id: 'RM-102', rows_count: 6, cols_count: 8, total_slots: 48 },
  { shelf_id: 'SH-C-01', shelf_name: 'C区一号书架·珍本手稿区', floor_num: 2, room_id: 'RM-201', rows_count: 6, cols_count: 6, total_slots: 36 },
  { shelf_id: 'SH-C-02', shelf_name: 'C区二号书架·孤本特藏区', floor_num: 2, room_id: 'RM-201', rows_count: 6, cols_count: 6, total_slots: 36 },
];

const LEVEL_NAMES = { SAFE: '安全', LOW: '低危', MEDIUM: '中危', HIGH: '高危', CRITICAL: '危急' };
const LEVEL_CN = { SAFE: '', LOW: 'medium', MEDIUM: 'medium', HIGH: 'high', CRITICAL: 'critical' };

async function loadOverview() {
  const d = await api('/overview/stats');
  if (!d) return;
  $('#statBooks').textContent = d.total_books?.toLocaleString?.() ?? d.total_books;
  $('#statShelves').textContent = d.total_shelves;
  $('#statEnv').textContent = d.total_env_sensors;
  $('#statPh').textContent = d.total_ph_sensors;
  const a = d.alerts_24h || {};
  $('#alertRed').textContent = a.red ?? 0;
  $('#alertOrange').textContent = a.orange ?? 0;
  $('#alertYellow').textContent = a.yellow ?? 0;
  const r = d.realtime_avg || {};
  $('#statTemp').textContent = r.temperature_c?.toFixed?.(1) ?? r.temperature_c;
  $('#statHumi').textContent = r.humidity_percent?.toFixed?.(0) ?? r.humidity_percent;
  $('#statPhv').textContent = r.ph?.toFixed?.(2) ?? r.ph;
}

function renderShelfList(list) {
  const shelves = (list && list.length ? list : DEFAULT_SHELVES;
  const filtered = shelves.filter(s => s.floor_num == ShelvesView.currentFloor);
  const el = $('#shelfList');
  el.innerHTML = '';
  filtered.forEach(s => {
    const div = document.createElement('div');
    div.className = 'shelf-item' + (s.shelf_id === ShelvesView.currentShelf ? ' active' : '');
    div.dataset.shelf = s.shelf_id;
    const riskClass = LEVEL_CN[s._risk] || (s.shelf_id === 'SH-A-01' ? 'medium' : '';
    div.innerHTML = `
      <div>
        <div class="shelf-name">${s.shelf_name || s.shelf_id}</div>
        <div class="shelf-meta">${s.room_id || ''} · ${s.rows_count || 6}×${s.cols_count || 8}=${s.total_slots || 48}格</div>
      </div>
      <div class="shelf-risk ${riskClass}">${s.floor_num ? `${s.total_slots ? '' : ''}${riskClass ? LEVEL_NAMES[(s._risk ? s._risk : (s.shelf_id === 'SH-A-01' ? 'MEDIUM' : SAFE']}</div>
    `;
    div.onclick = () => selectShelf(s);
    el.appendChild(div);
  });
}

function selectShelf(shelf) {
  ShelvesView.currentShelf = shelf.shelf_id;
  $('#viewerTitle').textContent = `📚 ${shelf.shelf_name || shelf.shelf_id`;
  $$('.shelf-item').forEach(el =>
    el.classList.toggle('active', el.dataset.shelf === shelf.shelf_id));
  loadHeatmap(shelf);
  loadTrend(shelf);
  renderShelfList();
}

async function loadHeatmap(shelf) {
  const data = await api(`/heatmap?shelf_id=${encodeURIComponent(shelf.shelf_id)}`);
  if (!data || !data.data) return;
  ShelvesView.heatmapData = data;
  const rows = data.rows || shelf.rows_count || 6;
  const cols = data.cols || shelf.cols_count || 8;
  const slotsSorted = Array.from({ length: rows * cols);
  data.data.forEach(s => {
    const idx = (s.row_num - 1) * cols + (s.col_num - 1);
    slotsSorted[idx] = s;
  });
  ShelvesView.renderer.setShelf(shelf.shelf_id, rows, cols, slotsSorted);
  const avg = slotsSorted.reduce((a, b) => a + (b?.scores?.overall || 0), 0) / (slotsSorted.filter(Boolean).length || 1;
  const s = DEFAULT_SHELVES.find(x => x.shelf_id === shelf.shelf_id);
  if (s) s._risk = avg > 0.7 ? 'CRITICAL' : avg > 0.5 ? 'HIGH' : avg > 0.3 ? 'MEDIUM' : avg > 0.1 ? 'LOW' : 'SAFE';
  renderShelfList();
  const current = slotsSorted.find(x => x);
  if (current) {
    const p = current.prediction || {};
    const m = current.metrics || {};
    $('#phPredInfo').textContent = `当前pH ${m.ph?.toFixed?.(2) || '-'} → 30天 ${p.ph_30d?.toFixed?.(2) || '-'} → 90天 ${p.ph_90d?.toFixed?.(2) || '-'}`;
    loadPhTrend(current);
    loadHerbsRecommend(current);
  }
}

async function loadTrend(shelf) {
  const d = await api(`/env/trend?shelf_id=${encodeURIComponent(shelf.shelf_id)}&hours=${24 * 90}`);
  ShelvesView.trendData = d?.data || [];
  drawTrendChart();
}

function drawTrendChart() {
  TrendCharts.renderTrend('#trendChart', ShelvesView.trendData, ShelvesView.trendMetric);
}

async function loadPhTrend(slot) {
  const d = await api(`/ph/trend?slot_id=${encodeURIComponent(slot?.slot_id || ShelvesView.currentShelf)}&days=90}`);
  const rows = d?.data || [];
  const p = slot?.prediction || {};
  const m = slot?.metrics || {};
  const cur = +(m.ph || p.ph_current || 6.6);
  TrendCharts.renderPhPrediction(
    '#phChart',
    cur,
    +(p.ph_30d || (cur - 0.03)),
    +(p.ph_90d || (cur - 0.09)),
    +(p.ph_180d || (cur - 0.18)),
    +(p.ph_365d || (cur - 0.36)),
    rows
  );
}

async function loadHerbsRecommend(slot) {
  const s = slot?.scores || {};
  const diseases = [];
  if (s.acidosis > 0.3) diseases.push('ACIDOSIS');
  if (s.mold > 0.3) diseases.push('MOLD');
  if (s.insect > 0.4) diseases.push('INSECT');
  if (!diseases.length && (s.overall || 0) < 0.2) return;
  const resp = await api('/herbs/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      disease_types: diseases,
      mold_risk: s.mold || 0,
      insect_risk: s.insect || 0,
      ph_value: slot?.metrics?.ph || null,
      book_dynasty: slot?.book_dynasty || '',
      top_k: 4,
    }),
  });
  ShelvesView._lastHerbs = resp;
}

async function loadAlerts() {
  const d = await api('/alerts?hours=48&limit=30');
  const rows = d?.data || [];
  const el = $('#alertList');
  el.innerHTML = '';
  if (!rows.length) {
    el.innerHTML = '<div class="alert-empty">近48小时无告警 🎉</div>';
    return;
  }
  rows.forEach(a => {
    const lv = (a.alert_level || 'YELLOW').toLowerCase();
    const typeMap = { ACIDOSIS: '酸化', MOLD: '霉菌', LIGHT: '光照', INSECT: '虫蛀', ACTIVE_MOLD: '活性霉菌' };
    const t = a.timestamp;
    const timeStr = typeof t === 'number' ? new Date(t > 1e12 ? t / 1000 : t).toLocaleString('zh-CN', { hour12: false }) : String(t).slice(0, 16);
    const div = document.createElement('div');
    div.className = 'alert-item ' + lv;
    div.innerHTML = `
      <div class="alert-level ${lv}">${lv === 'red' ? '🚨' : lv === 'orange' ? '⚠️' : '⚡'} ${a.alert_level || ''}</div>
      <div class="alert-msg">${typeMap[a.alert_type] || a.alert_type} · ${a.shelf_id || ''}${a.slot_id ? ' / ' + a.slot_id : ''}</div>
      <div class="alert-meta">${a.description || ''}</div>
      <div class="alert-meta">${timeStr}</div>
    `;
    el.appendChild(div);
  });
}

function openSlotModal(slotWrap) {
  const slot = slotWrap.slot || slotWrap.data || slotWrap;
  if (!slot?.slot_id) return;
  $('#modalTitle').textContent = `格口详情 · ${slot.slot_id}`;
  const m = slot.metrics || {};
  const s = slot.scores || {};
  const p = slot.prediction || {};
  const body = $('#modalBody');
  const vCls = (v, t1 = 6.5, t2 = 6.0, good = 'good', warn = 'warn', bad = 'bad') =>
    v >= t1 ? good : v >= t2 ? warn : bad;
  const pc = vCls(m.ph || 7, 6.5, 5.8);
  const tc = (m.temperature || 22) > 28 ? 'bad' : (m.temperature || 22) < 16 ? 'warn' : 'good';
  const hc = (m.humidity || 50) > 65 ? 'bad' : (m.humidity || 50) < 38 ? 'warn' : 'good';
  const mc = (m.mold_spores || 200) > 1000 ? 'bad' : (m.mold_spores || 200) > 500 ? 'warn' : 'good';
  const body.innerHTML = `
    <div class="modal-section">
      <h4>📖 藏书信息</h4>
      <div class="info-grid">
        <div class="info-cell"><div class="info-label">藏书名称</div><div class="info-value">${slot.book_title || '-'}</div></div>
        <div class="info-cell"><div class="info-label">朝代 / 类型</div><div class="info-value">${slot.book_dynasty || '-'} · ${slot.book_type || '-'}</div></div>
        <div class="info-cell"><div class="info-label">位置</div><div class="info-value">R${slot.row_num}行 · C${slot.col_num}列</div></div>
        <div class="info-cell"><div class="info-label">关联传感器</div><div class="info-value" style="font-size:13px">${slot.sensor_env_id || '-'} / ${slot.sensor_ph_id || '-'}</div></div>
      </div>
    </div>
    <div class="modal-section">
      <h4>🌡️ 微环境指标（近24h平均）</h4>
      <div class="info-grid">
        <div class="info-cell"><div class="info-label">温度</div><div class="info-value ${tc}">${m.temperature?.toFixed?.(1) || '-'} ℃</div></div>
        <div class="info-cell"><div class="info-label">相对湿度</div><div class="info-value ${hc}">${m.humidity?.toFixed?.(1) || '-'} %</div></div>
        <div class="info-cell"><div class="info-label">纸张pH</div><div class="info-value ${pc}">${m.ph?.toFixed?.(2) || '-'}</div></div>
        <div class="info-cell"><div class="info-label">霉菌孢子</div><div class="info-value ${mc}">${Math.round(m.mold_spores || 0)} CFU/m³</div></div>
        <div class="info-cell"><div class="info-label">光照强度</div><div class="info-value">${m.light_lux?.toFixed?.(0) || 0} lux</div></div>
        <div class="info-cell"><div class="info-label">活性霉菌</div><div class="info-value ${m.active_mold ? 'bad' : 'good'}">${m.active_mold ? '✅ 检出' : '未检出'}</div></div>
      </div>
    </div>
    <div class="modal-section">
      <h4>⚠️ 病害风险评估</h4>
      ${_riskBar('纸张酸化风险', s.acidosis || 0, '#6366f1')}
      ${_riskBar('霉菌生长风险', s.mold || 0, '#0d9488')}
      ${_riskBar('虫蛀风险', s.insect || 0, '#b45309')}
      <div style="margin-top:8px;padding:8px 12px;background:rgba(212,165,116,.1);border:1px solid rgba(212,165,116,.3);border-radius:6px;">
        <div style="font-size:12px;color:#94a3b8;">综合风险等级</div>
        <div style="font-size:18px;font-weight:700;color:${s.level === 'CRITICAL' ? '#dc2626' : s.level === 'HIGH' ? '#ea580c' : s.level === 'MEDIUM' ? '#f59e0b' : s.level === 'LOW' ? '#65a30d' : '#16a34a'}" >
          ${LEVEL_NAMES[s.level || 'SAFE'] || '安全'}
        </div>
      </div>
    </div>
    <div class="modal-section">
      <h4>🧪 纸张老化动力学预测（Arrhenius模型）</h4>
      <div id="modalMiniPh" class="mini-chart" style="height:170px;"></div>
      <div class="info-grid" style="margin-top:10px;">
        <div class="info-cell"><div class="info-label">当前pH</div><div class="info-value ${pc}">${m.ph?.toFixed?.(2) || '-'}</div></div>
        <div class="info-cell"><div class="info-label">30天后pH</div><div class="info-value">${p.ph_30d?.toFixed?.(2) || '-'}</div></div>
        <div class="info-cell"><div class="info-label">90天后pH</div><div class="info-value">${p.ph_90d?.toFixed?.(2) || '-'}</div></div>
        <div class="info-cell"><div class="info-label">老化速率</div><div class="info-value warn">${p.aging_rate ? (p.aging_rate * 100).toFixed(3) + ' %' : '-'}/年</div></div>
        <div class="info-cell"><div class="info-label">预测寿命</div><div class="info-value ${(p.life_expectancy || 100) < 50 ? 'bad' : (p.life_expectancy || 100) < 100 ? 'warn' : 'good'}">${p.life_expectancy || '-'} 年</div></div>
        <div class="info-cell"><div class="info-label">风险等级</div><div class="info-value">${LEVEL_NAMES[p.risk_level] || '-'}</div></div>
      </div>
    </div>
    <div class="modal-section">
      <h4>🌿 古籍防蠹药方推荐（知识图谱关联）</h4>
      <div id="herbsList"></div>
    </div>
  `;
  $('#slotModal').classList.remove('hidden');

  api(`/ph/trend?slot_id=${encodeURIComponent(slot.slot_id)}&days=90`).then(d => {
    TrendCharts.renderMiniPh('#modalMiniPh', d?.data || []);
  });
  _renderHerbsList();
}

function _riskBar(label, value, color) {
  const v = Math.max(0, Math.min(1, value || 0));
  const pct = Math.round(v * 100);
  return `
    <div class="risk-bar-wrap">
      <div class="risk-bar-label"><span>${label}</span><span>${pct}%</span></div>
      <div class="risk-bar"><div class="risk-bar-fill" style="width:${pct}%;background:${color};"></div></div>
    </div>
  `;
}

function _renderHerbsList() {
  const el = $('#herbsList');
  const resp = ShelvesView._lastHerbs;
  if (!resp || !resp.recommended_recipes?.length) {
    el.innerHTML = '<div class="alert-empty" style="padding:20px;">当前藏书保存状况良好，无需特别防护建议定期检查 😊</div>';
    return;
  }
  let html = '';
  resp.recommended_recipes.forEach(r => {
    const score = Math.round((r.match_score || 0) * 100);
    html += `
      <div class="herb-card">
        <div class="herb-head">
          <div>
            <div class="herb-name">🌿 ${r.herb_cn_name || r.herb_id}</div>
            <div class="herb-source">出处：${r.source || '-'}</div>
          </div>
          <div class="herb-score">匹配度 ${score}%</div>
        </div>
        <div class="herb-usage">📜 ${r.usage_method || ''}</div>
        <div style="font-size:11px;color:#94a3b8;margin-top:4px;">💡 ${r.efficacy || ''}</div>
        <div class="herb-tags">
          ${(r.target_pests || []).map(t => `<span class="herb-tag">杀${t}</span>`).join('')}
          ${r.toxicity === 'HIGH' ? `<span class="herb-tag" style="background:rgba(220,38,38,.2);border-color:rgba(220,38,38,.5);color:#fca5a5;">含毒/慎用</span>`
            : r.toxicity === 'MEDIUM' ? `<span class="herb-tag" style="background:rgba(234,88,12,.2);border-color:rgba(234,88,12,.4);color:#fdba74;">中注意用量</span>` : ''}
        </div>
        ${r.reasons?.length ? `<div class="herb-reasons">✔ ${r.reasons.join('；')}</div>` : ''}
      </div>
    `;
  });
  if (resp.compatibility_suggestion?.tip) {
    html += `<div class="compat-tip">💡 配伍建议：${resp.compatibility_suggestion.tip}</div>`;
  }
  el.innerHTML = html;
}

function bindEvents() {
  $('#floorTabs').addEventListener('click', e => {
    const btn = e.target.closest('.floor-tab');
    if (!btn) return;
    ShelvesView.currentFloor = +btn.dataset.floor;
    $$('.floor-tab').forEach(b => b.classList.toggle('active', b === btn));
    renderShelfList();
  });
  $$('.layer').forEach(lab => {
    lab.addEventListener('click', e => {
      const cb = lab.querySelector('input');
      if (e.target !== cb) cb.checked = !cb.checked;
      lab.classList.toggle('active', cb.checked);
      const layers = {};
      $$('.layer input').forEach(c => layers[c.value] = c.checked);
      ShelvesView.renderer.setLayers(layers);
    });
  });
  $('#btnRotateL').onclick = () => ShelvesView.renderer.rotate(-0.2, 0);
  $('#btnRotateR').onclick = () => ShelvesView.renderer.rotate(0.2, 0);
  $('#btnReset').onclick = () => { ShelvesView.renderer.resetView(); $('#zoomLabel').textContent = '100%'; };
  $('#btnZoomIn').onclick = () => { const z = ShelvesView.renderer.zoomBy(1.15); $('#zoomLabel').textContent = Math.round(z*100) + '%'; };
  $('#btnZoomOut').onclick = () => { const z = ShelvesView.renderer.zoomBy(1/1.15); $('#zoomLabel').textContent = Math.round(z*100) + '%'; };
  $('#btnRefresh').onclick = () => {
    loadOverview(); loadAlerts();
    const s = DEFAULT_SHELVES.find(x => x.shelf_id === ShelvesView.currentShelf);
    if (s) loadHeatmap(s);
  };
  $('#trendMetric').addEventListener('change', e => {
    ShelvesView.trendMetric = e.target.value; drawTrendChart();
  });
  $('#modalClose').onclick = () => $('#slotModal').classList.add('hidden');
  $('#slotModal').addEventListener('click', e => {
    if (e.target.id === 'slotModal') $('#slotModal').classList.add('hidden');
  });
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') $('#slotModal').classList.add('hidden');
  });
  const cv = $('#shelfCanvas');
  cv.addEventListener('slotClick', e => {
    const wrap = e.detail;
    if (wrap?.slot || wrap?.data?.slot_id) {
      openSlotModal(wrap);
    }
  });
  ShelvesView.renderer.on('slotClick', slot => {
    cv.dispatchEvent(new CustomEvent('slotClick', { detail: slot }));
  });
  window.addEventListener('resize', () => {
    ShelvesView.renderer.resize();
    ShelvesView.renderer.requestRender();
    drawTrendChart();
  });
}

async function init() {
  ShelvesView.renderer = new Shelf3DRenderer($('#shelfCanvas'));
  bindEvents();
  await loadOverview();
  const shelves = (await api('/shelves'))?.data;
  renderShelfList(shelves);
  loadAlerts();
  setTimeout(() => {
    const first = DEFAULT_SHELVES.find(s => s.floor_num === 1);
    if (first) selectShelf(first);
  }, 200);
  setInterval(() => { loadOverview(); loadAlerts(); }, 60_000);
}

document.addEventListener('DOMContentLoaded', init);
