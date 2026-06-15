class RankWidget {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.data = [];
        this.metricLabels = {
            temperature: '温度',
            humidity: '湿度',
            ph: 'pH值',
            mold_spore: '霉菌孢子'
        };
        this.metricUnits = {
            temperature: '°C',
            humidity: '%',
            ph: '',
            mold_spore: ' CFU/m³'
        };
    }

    setData(data) {
        this.data = data || [];
        this.render();
    }

    render() {
        if (!this.container) return;

        let html = '<h4>跨馆藏环境比对</h4>';

        if (!this.data || this.data.length === 0) {
            html += '<div class="empty-tip">暂无比对数据</div>';
            this.container.innerHTML = html;
            return;
        }

        html += '<div class="rank-widget-container">';

        this.data.forEach((item, index) => {
            const isAnomaly = item.is_anomaly || item.percentile > 95;
            const statusClass = isAnomaly ? 'anomaly' : this._getStatusClass(item.percentile);

            html += `
                <div class="rank-card ${statusClass}" data-library="${item.library_name}" data-index="${index}">
                    <div class="rank-header">
                        <span class="rank-library">${item.library_name}</span>
                        ${isAnomaly ? '<span class="anomaly-badge">异常</span>' : ''}
                    </div>
                    <div class="rank-metrics">
                        ${this._renderMetric(item, 'temperature')}
                        ${this._renderMetric(item, 'humidity')}
                        ${this._renderMetric(item, 'ph')}
                        ${this._renderMetric(item, 'mold_spore')}
                    </div>
                    <div class="rank-overall">
                        <div class="rank-overall-label">综合百分位</div>
                        <div class="rank-percentile-bar">
                            <div class="rank-percentile-fill ${this._getPercentileClass(item.percentile)}" 
                                 style="width: ${Math.min(item.percentile, 100)}%"></div>
                        </div>
                        <div class="rank-percentile-value">${item.percentile?.toFixed(1) || 0}%</div>
                    </div>
                </div>
            `;
        });

        html += '</div>';
        this.container.innerHTML = html;

        this._bindCardEvents();
    }

    _renderMetric(item, metric) {
        const value = item.metrics?.[metric] ?? item[metric];
        const percentile = item.metric_percentiles?.[metric] ?? item.percentile;

        if (value === undefined || value === null) {
            return '';
        }

        const statusClass = this._getMetricStatusClass(metric, percentile);
        const unit = this.metricUnits[metric] || '';
        const label = this.metricLabels[metric] || metric;

        return `
            <div class="rank-metric-item" data-metric="${metric}">
                <span class="metric-label">${label}</span>
                <span class="metric-value ${statusClass}">${this._formatValue(metric, value)}${unit}</span>
                <span class="metric-percentile">${percentile?.toFixed(0) || 0}%</span>
            </div>
        `;
    }

    _formatValue(metric, value) {
        if (metric === 'ph') {
            return value.toFixed(2);
        } else if (metric === 'mold_spore') {
            return value.toFixed(0);
        } else {
            return value.toFixed(1);
        }
    }

    _getStatusClass(percentile) {
        if (percentile >= 95) return 'danger';
        if (percentile >= 85) return 'warning';
        return 'normal';
    }

    _getPercentileClass(percentile) {
        if (percentile >= 95) return 'fill-danger';
        if (percentile >= 85) return 'fill-warning';
        return 'fill-normal';
    }

    _getMetricStatusClass(metric, percentile) {
        const thresholds = {
            temperature: { warning: 80, danger: 90 },
            humidity: { warning: 80, danger: 90 },
            ph: { warning: 85, danger: 95 },
            mold_spore: { warning: 80, danger: 90 }
        };

        const threshold = thresholds[metric] || { warning: 80, danger: 90 };

        if (percentile >= threshold.danger) return 'value-danger';
        if (percentile >= threshold.warning) return 'value-warning';
        return 'value-normal';
    }

    highlightAnomaly() {
        if (!this.container) return;

        const anomalyCards = this.container.querySelectorAll('.rank-card.anomaly');
        anomalyCards.forEach(card => {
            card.classList.add('pulse-highlight');
            setTimeout(() => {
                card.classList.remove('pulse-highlight');
            }, 3000);
        });
    }

    updateMetric(libraryName, metric, value, percentile) {
        if (!this.container) return;

        const card = this.container.querySelector(`.rank-card[data-library="${libraryName}"]`);
        if (!card) return;

        const metricItem = card.querySelector(`.rank-metric-item[data-metric="${metric}"]`);
        if (!metricItem) return;

        const unit = this.metricUnits[metric] || '';
        const statusClass = this._getMetricStatusClass(metric, percentile);

        const valueSpan = metricItem.querySelector('.metric-value');
        const percentileSpan = metricItem.querySelector('.metric-percentile');

        if (valueSpan) {
            valueSpan.textContent = `${this._formatValue(metric, value)}${unit}`;
            valueSpan.className = `metric-value ${statusClass}`;
        }

        if (percentileSpan) {
            percentileSpan.textContent = `${percentile?.toFixed(0) || 0}%`;
        }

        const dataIndex = card.dataset.index;
        if (this.data[dataIndex]) {
            if (!this.data[dataIndex].metrics) {
                this.data[dataIndex].metrics = {};
            }
            if (!this.data[dataIndex].metric_percentiles) {
                this.data[dataIndex].metric_percentiles = {};
            }
            this.data[dataIndex].metrics[metric] = value;
            this.data[dataIndex].metric_percentiles[metric] = percentile;
        }

        metricItem.classList.add('metric-updated');
        setTimeout(() => {
            metricItem.classList.remove('metric-updated');
        }, 1000);
    }

    _bindCardEvents() {
        if (!this.container) return;

        const cards = this.container.querySelectorAll('.rank-card');
        cards.forEach(card => {
            card.addEventListener('click', () => {
                cards.forEach(c => c.classList.remove('active'));
                card.classList.add('active');
            });
        });
    }
}

window.RankWidget = RankWidget;
