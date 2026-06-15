class HeatmapLayer {
    constructor(ctx, width, height) {
        this.ctx = ctx;
        this.width = width;
        this.height = height;
        this.data = [];
        this.type = 'ph';
    }

    setData(data) {
        this.data = data;
    }

    setType(type) {
        this.type = type;
    }

    draw() {
    }

    getColorForValue(value, level = null) {
        if (level) {
            return this._getColorByLevel(level);
        }
        return this._getColorByType(value);
    }

    _getColorByLevel(level) {
        const colors = {
            normal: { bg: 'rgba(82, 196, 26, 0.7)', text: '#52c41a' },
            warning: { bg: 'rgba(250, 173, 20, 0.7)', text: '#faad14' },
            danger: { bg: 'rgba(255, 77, 79, 0.8)', text: '#ff4d4f' }
        };
        return colors[level] || colors.normal;
    }

    _getColorByType(value) {
        switch (this.type) {
            case 'ph':
                return this._getPhColor(value);
            case 'mold':
                return this._getMoldColor(value);
            case 'acidification':
                return this._getAcidificationColor(value);
            case 'insect':
                return this._getInsectColor(value);
            default:
                return { bg: 'rgba(82, 196, 26, 0.7)', text: '#52c41a' };
        }
    }

    _getPhColor(value) {
        if (value >= 6.5) {
            return { bg: 'rgba(82, 196, 26, 0.8)', text: '#52c41a' };
        } else if (value >= 6.0) {
            const ratio = (6.5 - value) / 0.5;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.8)`,
                text: '#faad14'
            };
        } else if (value >= 5.5) {
            const ratio = (6.0 - value) / 0.5;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    _getMoldColor(value) {
        if (value < 100) {
            return { bg: 'rgba(82, 196, 26, 0.7)', text: '#52c41a' };
        } else if (value < 500) {
            const ratio = (value - 100) / 400;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.7)`,
                text: '#faad14'
            };
        } else if (value < 2000) {
            const ratio = (value - 500) / 1500;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    _getAcidificationColor(value) {
        if (value < 20) {
            return { bg: 'rgba(82, 196, 26, 0.6)', text: '#52c41a' };
        } else if (value < 50) {
            const ratio = (value - 20) / 30;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.6)`,
                text: '#faad14'
            };
        } else if (value < 80) {
            const ratio = (value - 50) / 30;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    _getInsectColor(value) {
        if (value < 50) {
            return { bg: 'rgba(82, 196, 26, 0.6)', text: '#52c41a' };
        } else if (value < 200) {
            const ratio = (value - 50) / 150;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.6)`,
                text: '#faad14'
            };
        } else if (value < 500) {
            const ratio = (value - 200) / 300;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    getLegendItems() {
        const legends = {
            ph: [
                { label: 'pH ≥ 6.5 (正常)', color: '#52c41a' },
                { label: 'pH 6.0-6.5 (轻度酸化)', color: '#faad14' },
                { label: 'pH 5.5-6.0 (中度酸化)', color: '#ff4d4f' },
                { label: 'pH < 5.5 (严重酸化)', color: '#cf1322' }
            ],
            mold: [
                { label: '< 100 CFU/m³ (正常)', color: '#52c41a' },
                { label: '100-500 CFU/m³ (轻度)', color: '#faad14' },
                { label: '500-2000 CFU/m³ (较高)', color: '#ff4d4f' },
                { label: '> 2000 CFU/m³ (严重)', color: '#cf1322' }
            ],
            acidification: [
                { label: '低风险', color: '#52c41a' },
                { label: '中低风险', color: '#95de64' },
                { label: '中高风险', color: '#faad14' },
                { label: '高风险', color: '#ff4d4f' }
            ],
            insect: [
                { label: '低风险', color: '#52c41a' },
                { label: '中低风险', color: '#95de64' },
                { label: '中高风险', color: '#faad14' },
                { label: '高风险', color: '#ff4d4f' }
            ]
        };
        return legends[this.type] || [];
    }

    getTypeLabel() {
        const labels = {
            ph: 'pH值分布',
            mold: '霉菌孢子分布',
            acidification: '酸化风险热力图',
            insect: '虫蛀风险热力图'
        };
        return labels[this.type] || '';
    }

    calculateRiskStats() {
        let normal = 0, warning = 0, danger = 0;

        this.data.forEach(item => {
            if (item.level === 'danger') {
                danger++;
            } else if (item.level === 'warning') {
                warning++;
            } else {
                normal++;
            }
        });

        return { normal, warning, danger, total: this.data.length };
    }
}

class HeatmapManager {
    constructor() {
        this.currentType = 'ph';
        this.data = [];
    }

    setType(type) {
        this.currentType = type;
    }

    setData(data) {
        this.data = data;
    }

    getColorForValue(value, level = null) {
        if (level) {
            return this._getColorByLevel(level);
        }
        return this._getColorByType(value);
    }

    _getColorByLevel(level) {
        const colors = {
            normal: { bg: 'rgba(82, 196, 26, 0.7)', text: '#52c41a' },
            warning: { bg: 'rgba(250, 173, 20, 0.7)', text: '#faad14' },
            danger: { bg: 'rgba(255, 77, 79, 0.8)', text: '#ff4d4f' }
        };
        return colors[level] || colors.normal;
    }

    _getColorByType(value) {
        switch (this.currentType) {
            case 'ph':
                return this._getPhColor(value);
            case 'mold':
                return this._getMoldColor(value);
            case 'acidification':
                return this._getAcidificationColor(value);
            case 'insect':
                return this._getInsectColor(value);
            default:
                return { bg: 'rgba(82, 196, 26, 0.7)', text: '#52c41a' };
        }
    }

    _getPhColor(value) {
        if (value >= 6.5) {
            return { bg: 'rgba(82, 196, 26, 0.8)', text: '#52c41a' };
        } else if (value >= 6.0) {
            const ratio = (6.5 - value) / 0.5;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.8)`,
                text: '#faad14'
            };
        } else if (value >= 5.5) {
            const ratio = (6.0 - value) / 0.5;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    _getMoldColor(value) {
        if (value < 100) {
            return { bg: 'rgba(82, 196, 26, 0.7)', text: '#52c41a' };
        } else if (value < 500) {
            const ratio = (value - 100) / 400;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.7)`,
                text: '#faad14'
            };
        } else if (value < 2000) {
            const ratio = (value - 500) / 1500;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    _getAcidificationColor(value) {
        if (value < 20) {
            return { bg: 'rgba(82, 196, 26, 0.6)', text: '#52c41a' };
        } else if (value < 50) {
            const ratio = (value - 20) / 30;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.6)`,
                text: '#faad14'
            };
        } else if (value < 80) {
            const ratio = (value - 50) / 30;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    _getInsectColor(value) {
        if (value < 50) {
            return { bg: 'rgba(82, 196, 26, 0.6)', text: '#52c41a' };
        } else if (value < 200) {
            const ratio = (value - 50) / 150;
            return {
                bg: `rgba(${Math.round(82 + ratio * 168)}, ${Math.round(196 - ratio * 23)}, ${Math.round(26 - ratio * 6)}, 0.6)`,
                text: '#faad14'
            };
        } else if (value < 500) {
            const ratio = (value - 200) / 300;
            return {
                bg: `rgba(${Math.round(250 + ratio * 5)}, ${Math.round(173 - ratio * 96)}, ${Math.round(20 + ratio * 59)}, 0.8)`,
                text: '#ff4d4f'
            };
        } else {
            return { bg: 'rgba(207, 19, 34, 0.9)', text: '#cf1322' };
        }
    }

    getLegendItems() {
        const legends = {
            ph: [
                { label: 'pH ≥ 6.5 (正常)', color: '#52c41a' },
                { label: 'pH 6.0-6.5 (轻度酸化)', color: '#faad14' },
                { label: 'pH 5.5-6.0 (中度酸化)', color: '#ff4d4f' },
                { label: 'pH < 5.5 (严重酸化)', color: '#cf1322' }
            ],
            mold: [
                { label: '< 100 CFU/m³ (正常)', color: '#52c41a' },
                { label: '100-500 CFU/m³ (轻度)', color: '#faad14' },
                { label: '500-2000 CFU/m³ (较高)', color: '#ff4d4f' },
                { label: '> 2000 CFU/m³ (严重)', color: '#cf1322' }
            ],
            acidification: [
                { label: '低风险', color: '#52c41a' },
                { label: '中低风险', color: '#95de64' },
                { label: '中高风险', color: '#faad14' },
                { label: '高风险', color: '#ff4d4f' }
            ],
            insect: [
                { label: '低风险', color: '#52c41a' },
                { label: '中低风险', color: '#95de64' },
                { label: '中高风险', color: '#faad14' },
                { label: '高风险', color: '#ff4d4f' }
            ]
        };
        return legends[this.currentType] || [];
    }

    getTypeLabel() {
        const labels = {
            ph: 'pH值分布',
            mold: '霉菌孢子分布',
            acidification: '酸化风险热力图',
            insect: '虫蛀风险热力图'
        };
        return labels[this.currentType] || '';
    }

    calculateRiskStats() {
        let normal = 0, warning = 0, danger = 0;

        this.data.forEach(item => {
            if (item.level === 'danger') {
                danger++;
            } else if (item.level === 'warning') {
                warning++;
            } else {
                normal++;
            }
        });

        return { normal, warning, danger, total: this.data.length };
    }
}

window.HeatmapLayer = HeatmapLayer;
window.HeatmapManager = HeatmapManager;
