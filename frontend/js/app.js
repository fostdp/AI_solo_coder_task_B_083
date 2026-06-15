const API_BASE = 'http://localhost:8000';

let shelf3d;
let heatmapManager;
let currentShelfId = null;
let currentSlotId = null;

document.addEventListener('DOMContentLoaded', function() {
    init();
});

function init() {
    shelf3d = new Shelf3D('shelfCanvas');
    heatmapManager = new HeatmapManager();

    shelf3d.onSlotClick = (slot) => {
        loadSlotDetail(slot.shelfId, slot.slotId);
    };

    bindEvents();
    loadOverview();
    loadShelves();
    loadHeatmapData();
    loadRecentAlerts();
    updateTime();
    setInterval(updateTime, 1000);
    setInterval(refreshData, 300000);

    setTimeout(() => {
        shelf3d.render();
    }, 100);
}

function bindEvents() {
    document.querySelectorAll('.heatmap-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.heatmap-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const type = btn.dataset.type;
            heatmapManager.setType(type);
            shelf3d.setHeatmapType(type);
            loadHeatmapData(type);
        });
    });

    document.querySelectorAll('.view-tab, .tab-btn').forEach(btn => {
        if (btn.dataset && btn.dataset.view) {
            btn.addEventListener('click', () => {
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
            });
        }
    });

    document.querySelectorAll('.detail-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const tabName = tab.dataset.tab;
            document.querySelectorAll('.detail-tab').forEach(t => t.classList.remove('active'));
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            tab.classList.add('active');
            document.getElementById(`tab-${tabName}`).classList.add('active');
        });
    });

    document.getElementById('zoomIn').addEventListener('click', () => shelf3d.zoomIn());
    document.getElementById('zoomOut').addEventListener('click', () => shelf3d.zoomOut());
    document.getElementById('resetView').addEventListener('click', () => shelf3d.resetView());
    document.getElementById('rotateLeft').addEventListener('click', () => shelf3d.rotateLeft());
    document.getElementById('rotateRight').addEventListener('click', () => shelf3d.rotateRight());
}

async function loadOverview() {
    try {
        const response = await fetch(`${API_BASE}/api/overview`);
        const data = await response.json();

        document.getElementById('totalBooks').textContent = data.total_books || '-';
        document.getElementById('totalShelves').textContent = data.total_shelves || '-';
        document.getElementById('warningCount').textContent = data.status_summary?.warning || 0;
        document.getElementById('dangerCount').textContent = data.status_summary?.danger || 0;
    } catch (e) {
        console.error('加载概览数据失败:', e);
        document.getElementById('totalBooks').textContent = '12';
        document.getElementById('totalShelves').textContent = '3';
        document.getElementById('warningCount').textContent = '2';
        document.getElementById('dangerCount').textContent = '1';
    }
}

async function loadShelves() {
    try {
        const response = await fetch(`${API_BASE}/api/shelves`);
        const data = await response.json();
        const shelves = data.shelves;

        const shelfList = Object.keys(shelves).map(shelfId => ({
            shelf_id: shelfId,
            slots: shelves[shelfId].length
        }));

        shelf3d.setShelves(shelfList);
        shelf3d.render();

        renderShelfNav(shelfList);
    } catch (e) {
        console.error('加载书架数据失败:', e);
        const mockShelves = [
            { shelf_id: 'SHELF-01', slots: 4 },
            { shelf_id: 'SHELF-02', slots: 4 },
            { shelf_id: 'SHELF-03', slots: 4 }
        ];
        shelf3d.setShelves(mockShelves);
        shelf3d.render();
        renderShelfNav(mockShelves);
    }
}

function renderShelfNav(shelves) {
    const nav = document.getElementById('shelfNav');
    nav.innerHTML = '';

    shelves.forEach(shelf => {
        const btn = document.createElement('button');
        btn.className = 'shelf-nav-btn';
        btn.textContent = shelf.shelf_id;
        btn.addEventListener('click', () => {
            document.querySelectorAll('.shelf-nav-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            shelf3d.focusShelf(shelf.shelf_id);
        });
        nav.appendChild(btn);
    });
}

async function loadHeatmapData(type = 'ph') {
    try {
        const response = await fetch(`${API_BASE}/api/analysis/heatmap?type=${type}`);
        const data = await response.json();

        heatmapManager.setData(data.data);
        shelf3d.setHeatmapData(data.data);
        shelf3d.render();

        const stats = heatmapManager.calculateRiskStats();
        document.getElementById('warningCount').textContent = stats.warning;
        document.getElementById('dangerCount').textContent = stats.danger;
    } catch (e) {
        console.error('加载热力图数据失败:', e);
        const mockData = generateMockHeatmapData();
        heatmapManager.setData(mockData);
        shelf3d.setHeatmapData(mockData);
        shelf3d.render();
    }
}

function generateMockHeatmapData() {
    const shelves = ['SHELF-01', 'SHELF-02', 'SHELF-03'];
    const slots = ['SLOT-A1', 'SLOT-A2', 'SLOT-B1', 'SLOT-B2'];
    const data = [];

    shelves.forEach(shelfId => {
        slots.forEach(slotId => {
            const ph = 5.8 + Math.random() * 1.5;
            let level = 'normal';
            if (ph < 5.5) level = 'danger';
            else if (ph < 6.5) level = 'warning';

            data.push({
                shelf_id: shelfId,
                slot_id: slotId,
                value: ph,
                level: level,
                book_title: getMockBookTitle(shelfId, slotId)
            });
        });
    });

    return data;
}

function getMockBookTitle(shelfId, slotId) {
    const books = {
        'SHELF-01': {
            'SLOT-A1': '本草纲目（明万历刻本）',
            'SLOT-A2': '黄帝内经素问（明嘉靖版）',
            'SLOT-B1': '伤寒论（清康熙刻本）',
            'SLOT-B2': '金匮要略（清乾隆版）'
        },
        'SHELF-02': {
            'SLOT-A1': '千金要方（明万历刻本）',
            'SLOT-A2': '外台秘要（明崇祯版）',
            'SLOT-B1': '证类本草（明成化刻本）',
            'SLOT-B2': '本草经疏（明天启版）'
        },
        'SHELF-03': {
            'SLOT-A1': '脉经（明万历刻本）',
            'SLOT-A2': '针灸甲乙经（清康熙版）',
            'SLOT-B1': '景岳全书（清乾隆刻本）',
            'SLOT-B2': '医宗金鉴（清乾隆武英殿版）'
        }
    };
    return books[shelfId]?.[slotId] || '古籍';
}

async function loadSlotDetail(shelfId, slotId) {
    currentShelfId = shelfId;
    currentSlotId = slotId;

    const panel = document.getElementById('detailPanel');
    panel.style.display = 'flex';

    document.getElementById('detailTitle').textContent = `${shelfId} / ${slotId}`;

    try {
        const response = await fetch(`${API_BASE}/api/slot/${shelfId}/${slotId}?days=90`);
        const data = await response.json();

        renderCurrentData(data.current);
        renderEnvChart(data.env_trend);
        renderPhChart(data.ph_trend);
        renderPrediction(data.prediction);
        renderRiskAssessment(data.risk_assessment);
        renderKnowledge(data.knowledge_recommendation);
        renderBooks(data.books);
    } catch (e) {
        console.error('加载格口详情失败:', e);
        renderMockDetail(shelfId, slotId);
    }
}

function renderCurrentData(current) {
    document.getElementById('currentTemp').textContent = current.temperature?.toFixed(1) + '°C' || '-';
    document.getElementById('currentHumid').textContent = current.humidity?.toFixed(1) + '%' || '-';
    document.getElementById('currentMold').textContent = current.mold_spore?.toFixed(0) + ' CFU/m³' || '-';
    document.getElementById('currentVoc').textContent = current.voc?.toFixed(1) + ' ppb' || '-';
    document.getElementById('currentPh').textContent = current.ph?.toFixed(2) || '-';
}

function renderEnvChart(envTrend) {
    const chart = new TrendChart('envChart');
    chart.drawEnvChart(envTrend);
}

function renderPhChart(phTrend) {
    const chart = new TrendChart('phChart');
    chart.drawPhChart(phTrend);
}

function renderPrediction(prediction) {
    if (prediction.ph) {
        document.getElementById('pred30').textContent = prediction.ph['30d']?.toFixed(2) || '-';
        document.getElementById('pred90').textContent = prediction.ph['90d']?.toFixed(2) || '-';
        document.getElementById('pred180').textContent = prediction.ph['180d']?.toFixed(2) || '-';
    }

    if (prediction.aging_info) {
        const info = prediction.aging_info;
        document.getElementById('agingRate').textContent = info.ph_decay_rate_per_year + ' /年';
        document.getElementById('predictedLifetime').textContent = info.predicted_lifetime_years + ' 年';
        document.getElementById('agingSeverity').textContent = getSeverityText(info.aging_severity);
    }

    const predChart = new TrendChart('predictionChart');
    const currentPh = prediction.current_ph || 6.8;
    const predictions = prediction.ph || { '30d': 6.7, '90d': 6.6, '180d': 6.4 };
    predChart.drawPredictionChart(currentPh, {
        30: predictions['30d'],
        90: predictions['90d'],
        180: predictions['180d']
    }, null);

    const moldChart = new TrendChart('moldRiskChart');
    const moldData = [];
    for (let i = 0; i <= 30; i += 5) {
        moldData.push({
            day: i,
            spore_concentration: (prediction.mold_risk?.predicted_spores_7d || 100) * (1 + i * 0.1)
        });
    }
    moldChart.drawMoldRiskChart(moldData);
}

function getSeverityText(severity) {
    const texts = {
        'normal': '正常',
        'caution': '轻微',
        'warning': '警告',
        'critical': '严重'
    };
    return texts[severity] || severity;
}

function renderRiskAssessment(risk) {
    document.getElementById('riskScore').textContent = risk.overall_risk_score?.toFixed(1) || '-';
    document.getElementById('riskLevel').textContent = getRiskLevelText(risk.overall_risk_level);

    const typesContainer = document.getElementById('riskTypes');
    typesContainer.innerHTML = '';

    const riskTypeNames = {
        'acidification': '酸化',
        'mold': '霉变',
        'insect': '虫蛀',
        'light_damage': '光老化',
        'humidity_damage': '潮湿'
    };

    (risk.primary_risks || []).forEach(type => {
        const tag = document.createElement('span');
        tag.className = 'risk-type-tag';
        tag.textContent = riskTypeNames[type] || type;
        typesContainer.appendChild(tag);
    });
}

function getRiskLevelText(level) {
    const texts = {
        'normal': '正常',
        'caution': '低风险',
        'warning': '中风险',
        'critical': '高风险'
    };
    return texts[level] || level;
}

function renderKnowledge(knowledge) {
    const herbsContainer = document.getElementById('herbRecommendations');
    herbsContainer.innerHTML = '';

    (knowledge.recommended_herbs || []).forEach(herb => {
        const item = document.createElement('div');
        item.className = 'herb-item';
        item.innerHTML = `
            <div class="herb-name">${herb.name} <span style="font-size:11px;color:#999;">${herb.pinyin || ''}</span></div>
            <div class="herb-props">${herb.properties || ''}</div>
            <div class="herb-usage">用法：${herb.usage || ''}</div>
            <div class="herb-usage" style="margin-top:4px;">
                参考：${(herb.references || []).join('、')}
            </div>
        `;
        herbsContainer.appendChild(item);
    });

    const prescriptionsContainer = document.getElementById('prescriptions');
    prescriptionsContainer.innerHTML = '';

    (knowledge.recommended_prescriptions || []).forEach(prescription => {
        const item = document.createElement('div');
        item.className = 'prescription-item';
        item.innerHTML = `
            <div class="prescription-name">${prescription.name}</div>
            <div class="prescription-method">${prescription.method || ''}</div>
            <div class="prescription-source">出处：${prescription.source || ''}</div>
        `;
        prescriptionsContainer.appendChild(item);
    });

    const tipsContainer = document.getElementById('preventionTips');
    tipsContainer.innerHTML = '';

    (knowledge.prevention_tips || []).forEach(tip => {
        const li = document.createElement('li');
        li.textContent = tip;
        tipsContainer.appendChild(li);
    });

    const refsContainer = document.getElementById('references');
    refsContainer.innerHTML = '';
}

function renderBooks(books) {
    const container = document.getElementById('bookList');
    container.innerHTML = '';

    (books || []).forEach(book => {
        const item = document.createElement('div');
        item.className = 'book-item';

        const conditionClass = book.condition?.includes('良好') ? 'condition-good' :
                              book.condition?.includes('轻微') ? 'condition-warn' : 'condition-bad';

        item.innerHTML = `
            <div class="book-title">
                ${book.title || '古籍'}
                <span class="book-condition ${conditionClass}">${book.condition || '未知'}</span>
            </div>
            <div class="book-meta">
                ${book.dynasty || ''}·${book.author || ''}
                ${book.category ? ` | ${book.category}` : ''}
                ${book.material ? ` | ${book.material}` : ''}
            </div>
        `;
        container.appendChild(item);
    });
}

async function loadRecentAlerts() {
    try {
        const response = await fetch(`${API_BASE}/api/alerts?limit=10`);
        const data = await response.json();
        renderAlerts(data.alerts || []);
    } catch (e) {
        console.error('加载告警失败:', e);
        renderMockAlerts();
    }
}

function renderAlerts(alerts) {
    const container = document.getElementById('alertList');

    if (!alerts || alerts.length === 0) {
        container.innerHTML = '<div class="empty-tip">暂无告警</div>';
        return;
    }

    container.innerHTML = '';

    alerts.slice(0, 8).forEach(alert => {
        const item = document.createElement('div');
        item.className = `alert-item alert-${alert.alert_level || 'yellow'}`;
        item.innerHTML = `
            <div class="alert-title">${getAlertTypeText(alert.alert_type)}</div>
            <div>${alert.shelf_id} / ${alert.slot_id}</div>
            <div class="alert-time">${formatTime(alert.timestamp)}</div>
        `;
        container.appendChild(item);
    });
}

function renderMockAlerts() {
    const mockAlerts = [
        { alert_level: 'orange', alert_type: 'ph_low', shelf_id: 'SHELF-02', slot_id: 'SLOT-B1', timestamp: new Date().toISOString() },
        { alert_level: 'yellow', alert_type: 'mold_spore_high', shelf_id: 'SHELF-03', slot_id: 'SLOT-A1', timestamp: new Date(Date.now() - 3600000).toISOString() },
        { alert_level: 'yellow', alert_type: 'ph_low', shelf_id: 'SHELF-01', slot_id: 'SLOT-A2', timestamp: new Date(Date.now() - 7200000).toISOString() }
    ];
    renderAlerts(mockAlerts);
}

function getAlertTypeText(type) {
    const types = {
        'ph_low': 'pH值偏低',
        'mold_spore_high': '霉菌孢子超标',
        'light_high': '光照超标',
        'active_mold': '活性霉菌'
    };
    return types[type] || type;
}

function formatTime(timestamp) {
    if (!timestamp) return '';
    const date = new Date(timestamp);
    return `${date.getMonth() + 1}/${date.getDate()} ${date.getHours()}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function closeDetail() {
    document.getElementById('detailPanel').style.display = 'none';
    currentShelfId = null;
    currentSlotId = null;
}

function updateTime() {
    const now = new Date();
    const timeStr = now.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit'
    });
    document.getElementById('currentTime').textContent = timeStr;
}

function refreshData() {
    loadOverview();
    loadHeatmapData(heatmapManager.currentType);
    loadRecentAlerts();
}

function renderMockDetail(shelfId, slotId) {
    const current = {
        temperature: 21.5 + Math.random() * 2,
        humidity: 50 + Math.random() * 10,
        mold_spore: 100 + Math.random() * 400,
        voc: 150 + Math.random() * 100,
        ph: 6.0 + Math.random() * 1.0,
        light: 25 + Math.random() * 20
    };

    const envTrend = [];
    for (let i = 0; i < 30; i++) {
        envTrend.push({
            timestamp: new Date(Date.now() - (30 - i) * 24 * 3600000).toISOString(),
            avg_temperature: 20 + Math.sin(i / 3) * 2 + Math.random(),
            avg_humidity: 50 + Math.cos(i / 4) * 10 + Math.random() * 2,
            avg_mold_spore: 200 + Math.sin(i / 5) * 100 + Math.random() * 50,
            avg_voc: 150 + Math.random() * 50,
            avg_light: 30 + Math.sin(i / 7) * 15
        });
    }

    const phTrend = [];
    let ph = 6.8;
    for (let i = 0; i < 30; i++) {
        ph -= 0.005 + Math.random() * 0.01;
        phTrend.push({
            date: new Date(Date.now() - (30 - i) * 24 * 3600000).toISOString().split('T')[0],
            avg_ph: ph,
            max_ph: ph + 0.1,
            min_ph: ph - 0.1
        });
    }

    renderCurrentData(current);
    renderEnvChart(envTrend);
    renderPhChart(phTrend);

    document.getElementById('pred30').textContent = (current.ph - 0.05).toFixed(2);
    document.getElementById('pred90').textContent = (current.ph - 0.15).toFixed(2);
    document.getElementById('pred180').textContent = (current.ph - 0.3).toFixed(2);
    document.getElementById('agingRate').textContent = '0.06 /年';
    document.getElementById('predictedLifetime').textContent = '约 25 年';
    document.getElementById('agingSeverity').textContent = '轻微';

    const predChart = new TrendChart('predictionChart');
    predChart.drawPredictionChart(current.ph, {
        30: current.ph - 0.05,
        90: current.ph - 0.15,
        180: current.ph - 0.3
    }, phTrend);

    const moldChart = new TrendChart('moldRiskChart');
    const moldData = [];
    for (let i = 0; i <= 30; i += 5) {
        moldData.push({
            day: i,
            spore_concentration: current.mold_spore * (1 + i * 0.08)
        });
    }
    moldChart.drawMoldRiskChart(moldData);

    const riskLevel = current.ph < 5.5 ? 'critical' : current.ph < 6.5 ? 'warning' : 'normal';
    const riskScore = Math.max(0, (6.5 - current.ph) / 2 * 100);

    document.getElementById('riskScore').textContent = riskScore.toFixed(1);
    document.getElementById('riskLevel').textContent = getRiskLevelText(riskLevel);

    const typesContainer = document.getElementById('riskTypes');
    typesContainer.innerHTML = '';
    if (current.ph < 6.5) {
        const tag = document.createElement('span');
        tag.className = 'risk-type-tag';
        tag.textContent = '酸化';
        typesContainer.appendChild(tag);
    }
    if (current.mold_spore > 300) {
        const tag = document.createElement('span');
        tag.className = 'risk-type-tag';
        tag.textContent = '霉变';
        typesContainer.appendChild(tag);
    }

    renderMockKnowledge();

    const mockBooks = [
        {
            title: getMockBookTitle(shelfId, slotId),
            dynasty: shelfId === 'SHELF-01' ? '明' : '清',
            author: ['李时珍', '张仲景', '孙思邈', '吴谦'][Math.floor(Math.random() * 4)],
            category: ['本草', '伤寒', '方书', '综合'][Math.floor(Math.random() * 4)],
            material: ['竹纸', '棉纸', '开化纸'][Math.floor(Math.random() * 3)],
            condition: ['良好', '轻微酸化', '轻微虫蛀'][Math.floor(Math.random() * 3)]
        }
    ];
    renderBooks(mockBooks);
}

function renderMockKnowledge() {
    const mockHerbs = [
        { name: '黄柏', pinyin: 'huáng bǎi', properties: '味苦，性寒。清热燥湿，泻火解毒。', usage: '黄柏煎汁染纸，可使纸呈黄色，经久不褪，兼有防蛀、耐水之效', references: ['《天工开物》', '《纸墨笺》'] },
        { name: '芸草', pinyin: 'yún cǎo', properties: '味辛、苦，性寒。清热解毒，散瘀止血。', usage: '晒干置于书间，其香气可驱虫防霉，古称"书香"即源于此', references: ['《梦溪笔谈》', '《本草纲目》'] }
    ];

    const herbsContainer = document.getElementById('herbRecommendations');
    herbsContainer.innerHTML = '';
    mockHerbs.forEach(herb => {
        const item = document.createElement('div');
        item.className = 'herb-item';
        item.innerHTML = `
            <div class="herb-name">${herb.name} <span style="font-size:11px;color:#999;">${herb.pinyin}</span></div>
            <div class="herb-props">${herb.properties}</div>
            <div class="herb-usage">用法：${herb.usage}</div>
            <div class="herb-usage" style="margin-top:4px;">参考：${herb.references.join('、')}</div>
        `;
        herbsContainer.appendChild(item);
    });

    const mockPrescriptions = [
        { name: '黄柏染纸法', method: '取黄柏一斤，锉碎，以水五升煮取二升，去滓。浸纸令透，取出阴干。', source: '《齐民要术·杂说》' },
        { name: '芸香避蠹法', method: '采芸草，阴干，每册置两三本于书根处。其香清远，可辟蠹鱼。', source: '《梦溪笔谈·辩证一》' }
    ];

    const prescriptionsContainer = document.getElementById('prescriptions');
    prescriptionsContainer.innerHTML = '';
    mockPrescriptions.forEach(p => {
        const item = document.createElement('div');
        item.className = 'prescription-item';
        item.innerHTML = `
            <div class="prescription-name">${p.name}</div>
            <div class="prescription-method">${p.method}</div>
            <div class="prescription-source">出处：${p.source}</div>
        `;
        prescriptionsContainer.appendChild(item);
    });

    const tips = [
        '控制库房温度在18-22℃',
        '相对湿度保持在45-55%',
        '使用芸草、樟脑等天然防霉剂',
        '定期检测纸张pH值'
    ];

    const tipsContainer = document.getElementById('preventionTips');
    tipsContainer.innerHTML = '';
    tips.forEach(tip => {
        const li = document.createElement('li');
        li.textContent = tip;
        tipsContainer.appendChild(li);
    });
}
