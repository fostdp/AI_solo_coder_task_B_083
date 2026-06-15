class TrendChart {
    constructor(containerId) {
        this.containerId = containerId;
        this.container = document.getElementById(containerId);
        this.width = 0;
        this.height = 0;
        this.margin = { top: 20, right: 30, bottom: 40, left: 50 };
    }

    _getSize() {
        const rect = this.container.getBoundingClientRect();
        this.width = rect.width || 400;
        this.height = rect.height || 200;
    }

    drawEnvChart(data) {
        this._getSize();
        this.container.innerHTML = '';

        if (!data || data.length === 0) {
            this._drawEmptyState('暂无数据');
            return;
        }

        const svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', this.width)
            .attr('height', this.height);

        const innerWidth = this.width - this.margin.left - this.margin.right;
        const innerHeight = this.height - this.margin.top - this.margin.bottom;

        const g = svg.append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const parseTime = d3.timeParse('%Y-%m-%d %H:%M:%S');

        const processedData = data.map(d => ({
            date: parseTime(d.timestamp) || new Date(d.timestamp),
            temperature: d.avg_temperature,
            humidity: d.avg_humidity,
            mold_spore: d.avg_mold_spore
        })).filter(d => d.date);

        const x = d3.scaleTime()
            .domain(d3.extent(processedData, d => d.date))
            .range([0, innerWidth]);

        const yTemp = d3.scaleLinear()
            .domain([d3.min(processedData, d => d.temperature) - 2,
                     d3.max(processedData, d => d.temperature) + 2])
            .range([innerHeight, 0]);

        const yHumid = d3.scaleLinear()
            .domain([30, 90])
            .range([innerHeight, 0]);

        const xAxis = d3.axisBottom(x)
            .ticks(6)
            .tickFormat(d3.timeFormat('%m-%d'));

        const yAxisLeft = d3.axisLeft(yTemp)
            .ticks(5);

        const yAxisRight = d3.axisRight(yHumid)
            .ticks(5);

        g.append('g')
            .attr('class', 'x-axis')
            .attr('transform', `translate(0,${innerHeight})`)
            .style('font-size', '10px')
            .call(xAxis);

        g.append('g')
            .attr('class', 'y-axis-left')
            .style('font-size', '10px')
            .call(yAxisLeft);

        g.append('g')
            .attr('class', 'y-axis-right')
            .attr('transform', `translate(${innerWidth},0)`)
            .style('font-size', '10px')
            .call(yAxisRight);

        const tempLine = d3.line()
            .x(d => x(d.date))
            .y(d => yTemp(d.temperature))
            .curve(d3.curveMonotoneX);

        const humidLine = d3.line()
            .x(d => x(d.date))
            .y(d => yHumid(d.humidity))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(processedData)
            .attr('fill', 'none')
            .attr('stroke', '#ff4d4f')
            .attr('stroke-width', 2)
            .attr('d', tempLine);

        g.append('path')
            .datum(processedData)
            .attr('fill', 'none')
            .attr('stroke', '#1890ff')
            .attr('stroke-width', 2)
            .attr('d', humidLine);

        const gradient = svg.append('defs')
            .append('linearGradient')
            .attr('id', 'tempGradient')
            .attr('x1', '0%')
            .attr('y1', '0%')
            .attr('x2', '0%')
            .attr('y2', '100%');

        gradient.append('stop')
            .attr('offset', '0%')
            .attr('stop-color', '#ff4d4f')
            .attr('stop-opacity', 0.3);

        gradient.append('stop')
            .attr('offset', '100%')
            .attr('stop-color', '#ff4d4f')
            .attr('stop-opacity', 0);

        const tempArea = d3.area()
            .x(d => x(d.date))
            .y0(innerHeight)
            .y1(d => yTemp(d.temperature))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(processedData)
            .attr('fill', 'url(#tempGradient)')
            .attr('d', tempArea);

        const legend = g.append('g')
            .attr('class', 'legend')
            .attr('transform', `translate(${innerWidth - 120}, 0)`);

        legend.append('line')
            .attr('x1', 0)
            .attr('y1', 8)
            .attr('x2', 20)
            .attr('y2', 8)
            .attr('stroke', '#ff4d4f')
            .attr('stroke-width', 2);

        legend.append('text')
            .attr('x', 25)
            .attr('y', 12)
            .style('font-size', '10px')
            .text('温度(°C)');

        legend.append('line')
            .attr('x1', 0)
            .attr('y1', 28)
            .attr('x2', 20)
            .attr('y2', 28)
            .attr('stroke', '#1890ff')
            .attr('stroke-width', 2);

        legend.append('text')
            .attr('x', 25)
            .attr('y', 32)
            .style('font-size', '10px')
            .text('湿度(%)');
    }

    drawPhChart(data) {
        this._getSize();
        this.container.innerHTML = '';

        if (!data || data.length === 0) {
            this._drawEmptyState('暂无数据');
            return;
        }

        const svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', this.width)
            .attr('height', this.height);

        const innerWidth = this.width - this.margin.left - this.margin.right;
        const innerHeight = this.height - this.margin.top - this.margin.bottom;

        const g = svg.append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const parseTime = d3.timeParse('%Y-%m-%d');

        const processedData = data.map(d => ({
            date: parseTime(d.date) || new Date(d.date),
            ph: d.avg_ph,
            max_ph: d.max_ph,
            min_ph: d.min_ph
        })).filter(d => d.date);

        const x = d3.scaleTime()
            .domain(d3.extent(processedData, d => d.date))
            .range([0, innerWidth]);

        const y = d3.scaleLinear()
            .domain([5.0, 7.5])
            .range([innerHeight, 0]);

        const xAxis = d3.axisBottom(x)
            .ticks(6)
            .tickFormat(d3.timeFormat('%m-%d'));

        const yAxis = d3.axisLeft(y)
            .ticks(5);

        g.append('g')
            .attr('class', 'x-axis')
            .attr('transform', `translate(0,${innerHeight})`)
            .style('font-size', '10px')
            .call(xAxis);

        g.append('g')
            .attr('class', 'y-axis')
            .style('font-size', '10px')
            .call(yAxis);

        const thresholds = [6.5, 6.0, 5.5];
        const thresholdColors = ['#faad14', '#ff9c6e', '#ff4d4f'];

        thresholds.forEach((th, i) => {
            g.append('line')
                .attr('x1', 0)
                .attr('x2', innerWidth)
                .attr('y1', y(th))
                .attr('y2', y(th))
                .attr('stroke', thresholdColors[i])
                .attr('stroke-width', 1)
                .attr('stroke-dasharray', '5,5')
                .attr('opacity', 0.7);

            g.append('text')
                .attr('x', innerWidth - 5)
                .attr('y', y(th) - 3)
                .attr('text-anchor', 'end')
                .style('font-size', '9px')
                .attr('fill', thresholdColors[i])
                .text(`pH ${th}`);
        });

        const area = d3.area()
            .x(d => x(d.date))
            .y0(d => y(d.min_ph))
            .y1(d => y(d.max_ph))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(processedData)
            .attr('fill', 'rgba(24, 144, 255, 0.2)')
            .attr('d', area);

        const line = d3.line()
            .x(d => x(d.date))
            .y(d => y(d.ph))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(processedData)
            .attr('fill', 'none')
            .attr('stroke', '#1890ff')
            .attr('stroke-width', 2)
            .attr('d', line);

        g.append('circle')
            .attr('cx', x(processedData[processedData.length - 1].date))
            .attr('cy', y(processedData[processedData.length - 1].ph))
            .attr('r', 4)
            .attr('fill', '#1890ff');
    }

    drawPredictionChart(currentPh, predictions, history) {
        this._getSize();
        this.container.innerHTML = '';

        const svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', this.width)
            .attr('height', this.height);

        const innerWidth = this.width - this.margin.left - this.margin.right;
        const innerHeight = this.height - this.margin.top - this.margin.bottom;

        const g = svg.append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const allData = [];

        if (history && history.length > 0) {
            history.forEach(d => {
                allData.push({
                    day: -history.length + history.indexOf(d),
                    ph: d.ph_value,
                    type: 'history'
                });
            });
        }

        allData.push({ day: 0, ph: currentPh, type: 'current' });

        if (predictions) {
            Object.keys(predictions).sort((a, b) => a - b).forEach(day => {
                allData.push({
                    day: parseInt(day),
                    ph: predictions[day],
                    type: 'prediction'
                });
            });
        }

        const x = d3.scaleLinear()
            .domain(d3.extent(allData, d => d.day))
            .range([0, innerWidth]);

        const y = d3.scaleLinear()
            .domain([5.0, 7.5])
            .range([innerHeight, 0]);

        const xAxis = d3.axisBottom(x)
            .ticks(6)
            .tickFormat(d => d === 0 ? '今天' : (d > 0 ? `${d}天` : `${-d}天前`));

        const yAxis = d3.axisLeft(y)
            .ticks(5);

        g.append('g')
            .attr('class', 'x-axis')
            .attr('transform', `translate(0,${innerHeight})`)
            .style('font-size', '10px')
            .call(xAxis);

        g.append('g')
            .attr('class', 'y-axis')
            .style('font-size', '10px')
            .call(yAxis);

        const thresholds = [6.5, 6.0, 5.5];
        const thresholdColors = ['#faad14', '#ff9c6e', '#ff4d4f'];

        thresholds.forEach((th, i) => {
            g.append('line')
                .attr('x1', 0)
                .attr('x2', innerWidth)
                .attr('y1', y(th))
                .attr('y2', y(th))
                .attr('stroke', thresholdColors[i])
                .attr('stroke-width', 1)
                .attr('stroke-dasharray', '5,5')
                .attr('opacity', 0.6);
        });

        const historyData = allData.filter(d => d.type !== 'prediction');
        const predictionData = allData.filter(d => d.type !== 'history');

        const historyLine = d3.line()
            .x(d => x(d.day))
            .y(d => y(d.ph))
            .curve(d3.curveMonotoneX);

        g.append('path')
            .datum(historyData)
            .attr('fill', 'none')
            .attr('stroke', '#1890ff')
            .attr('stroke-width', 2)
            .attr('d', historyLine);

        if (predictionData.length > 1) {
            const predLine = d3.line()
                .x(d => x(d.day))
                .y(d => y(d.ph))
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(predictionData)
                .attr('fill', 'none')
                .attr('stroke', '#ff4d4f')
                .attr('stroke-width', 2)
                .attr('stroke-dasharray', '5,5')
                .attr('d', predLine);
        }

        const legend = g.append('g')
            .attr('class', 'legend')
            .attr('transform', `translate(${innerWidth - 100}, 0)`);

        legend.append('line')
            .attr('x1', 0)
            .attr('y1', 8)
            .attr('x2', 20)
            .attr('y2', 8)
            .attr('stroke', '#1890ff')
            .attr('stroke-width', 2);

        legend.append('text')
            .attr('x', 25)
            .attr('y', 12)
            .style('font-size', '10px')
            .text('历史数据');

        legend.append('line')
            .attr('x1', 0)
            .attr('y1', 28)
            .attr('x2', 20)
            .attr('y2', 28)
            .attr('stroke', '#ff4d4f')
            .attr('stroke-width', 2)
            .attr('stroke-dasharray', '5,5');

        legend.append('text')
            .attr('x', 25)
            .attr('y', 32)
            .style('font-size', '10px')
            .text('预测数据');
    }

    drawMoldRiskChart(data) {
        this._getSize();
        this.container.innerHTML = '';

        if (!data || data.length === 0) {
            this._drawEmptyState('暂无数据');
            return;
        }

        const svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', this.width)
            .attr('height', this.height);

        const innerWidth = this.width - this.margin.left - this.margin.right;
        const innerHeight = this.height - this.margin.top - this.margin.bottom;

        const g = svg.append('g')
            .attr('transform', `translate(${this.margin.left},${this.margin.top})`);

        const x = d3.scaleBand()
            .domain(data.map(d => d.day || d.label))
            .range([0, innerWidth])
            .padding(0.2);

        const y = d3.scaleLinear()
            .domain([0, d3.max(data, d => d.spore_concentration || d.value) * 1.1])
            .range([innerHeight, 0]);

        const xAxis = d3.axisBottom(x)
            .ticks(5);

        const yAxis = d3.axisLeft(y)
            .ticks(5);

        g.append('g')
            .attr('class', 'x-axis')
            .attr('transform', `translate(0,${innerHeight})`)
            .style('font-size', '10px')
            .call(xAxis);

        g.append('g')
            .attr('class', 'y-axis')
            .style('font-size', '10px')
            .call(yAxis);

        g.selectAll('.bar')
            .data(data)
            .enter()
            .append('rect')
            .attr('class', 'bar')
            .attr('x', d => x(d.day || d.label))
            .attr('y', d => y(d.spore_concentration || d.value))
            .attr('width', x.bandwidth())
            .attr('height', d => innerHeight - y(d.spore_concentration || d.value))
            .attr('fill', d => {
                const val = d.spore_concentration || d.value;
                if (val < 100) return '#52c41a';
                if (val < 500) return '#faad14';
                return '#ff4d4f';
            })
            .attr('opacity', 0.8);
    }

    _drawEmptyState(message) {
        const svg = d3.select(`#${this.containerId}`)
            .append('svg')
            .attr('width', this.width || 400)
            .attr('height', this.height || 200);

        svg.append('text')
            .attr('x', (this.width || 400) / 2)
            .attr('y', (this.height || 200) / 2)
            .attr('text-anchor', 'middle')
            .attr('dominant-baseline', 'middle')
            .attr('fill', '#999')
            .style('font-size', '14px')
            .text(message);
    }
}
