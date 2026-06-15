class Shelf3D {
    constructor(canvasId) {
        this.canvas = document.getElementById(canvasId);
        this.ctx = this.canvas.getContext('2d');

        this.shelves = [];
        this.heatmapData = [];
        this.heatmapType = 'ph';

        this.viewAngleX = 0.6;
        this.viewAngleY = 0.3;
        this.zoom = 1;
        this.offsetX = 0;
        this.offsetY = 0;

        this.isDragging = false;
        this.lastMouseX = 0;
        this.lastMouseY = 0;

        this.hoveredSlot = null;
        this.selectedSlot = null;
        this.onSlotClick = null;

        this._init();
    }

    _init() {
        this._resize();
        window.addEventListener('resize', () => this._resize());
        this._bindEvents();
    }

    _resize() {
        const rect = this.canvas.parentElement.getBoundingClientRect();
        this.canvas.width = rect.width;
        this.canvas.height = rect.height;
        this.width = this.canvas.width;
        this.height = this.canvas.height;
    }

    _bindEvents() {
        this.canvas.addEventListener('mousedown', (e) => this._onMouseDown(e));
        this.canvas.addEventListener('mousemove', (e) => this._onMouseMove(e));
        this.canvas.addEventListener('mouseup', () => this._onMouseUp());
        this.canvas.addEventListener('mouseleave', () => this._onMouseUp());
        this.canvas.addEventListener('click', (e) => this._onClick(e));
        this.canvas.addEventListener('wheel', (e) => this._onWheel(e));
    }

    _onMouseDown(e) {
        this.isDragging = true;
        this.lastMouseX = e.clientX;
        this.lastMouseY = e.clientY;
    }

    _onMouseMove(e) {
        const rect = this.canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        if (this.isDragging) {
            const dx = e.clientX - this.lastMouseX;
            const dy = e.clientY - this.lastMouseY;
            this.viewAngleY += dx * 0.005;
            this.viewAngleX += dy * 0.005;
            this.viewAngleX = Math.max(-1.5, Math.min(1.5, this.viewAngleX));
            this.lastMouseX = e.clientX;
            this.lastMouseY = e.clientY;
            this.render();
        } else {
            this._checkHover(x, y);
        }
    }

    _onMouseUp() {
        this.isDragging = false;
    }

    _onClick(e) {
        if (this.hoveredSlot && this.onSlotClick) {
            this.selectedSlot = this.hoveredSlot;
            this.onSlotClick(this.hoveredSlot);
            this.render();
        }
    }

    _onWheel(e) {
        e.preventDefault();
        const delta = e.deltaY > 0 ? 0.9 : 1.1;
        this.zoom = Math.max(0.3, Math.min(3, this.zoom * delta));
        this.render();
    }

    setShelves(shelves) {
        this.shelves = shelves;
    }

    setHeatmapData(data) {
        this.heatmapData = data;
    }

    setHeatmapType(type) {
        this.heatmapType = type;
    }

    _checkHover(x, y) {
        let found = null;
        const slots = this._getAllSlots();

        for (let i = slots.length - 1; i >= 0; i--) {
            const slot = slots[i];
            if (this._pointInRect(x, y, slot.screenRect)) {
                found = {
                    shelfId: slot.shelfId,
                    slotId: slot.slotId,
                    data: slot.data
                };
                break;
            }
        }

        if (found !== this.hoveredSlot) {
            this.hoveredSlot = found;
            this.canvas.style.cursor = found ? 'pointer' : 'grab';
            this.render();
        }
    }

    _pointInRect(x, y, rect) {
        return x >= rect.x && x <= rect.x + rect.width &&
               y >= rect.y && y <= rect.y + rect.height;
    }

    _getAllSlots() {
        const slots = [];
        const shelfWidth = 100;
        const shelfHeight = 180;
        const shelfDepth = 30;
        const slotWidth = 30;
        const slotHeight = 80;
        const gap = 5;

        this.shelves.forEach((shelf, shelfIdx) => {
            const row = Math.floor(shelfIdx / 2);
            const col = shelfIdx % 2;
            const baseX = (col - 0.5) * (shelfWidth + 80);
            const baseY = 0;
            const baseZ = (row - 1.5) * (shelfDepth + 60);

            const slotsPerRow = 3;
            const rows = 2;
            let slotIdx = 0;

            for (let r = 0; r < rows; r++) {
                for (let c = 0; c < slotsPerRow; c++) {
                    if (slotIdx >= (shelf.slots || 6)) break;

                    const slotId = `SLOT-${String.fromCharCode(65 + r)}${c + 1}`;
                    const sx = baseX + (c - slotsPerRow / 2 + 0.5) * (slotWidth + gap);
                    const sy = baseY + (r - rows / 2 + 0.5) * (slotHeight + gap) + shelfHeight / 4;
                    const sz = baseZ;

                    const heatmapItem = this.heatmapData.find(
                        h => h.shelf_id === shelf.shelf_id && h.slot_id === slotId
                    );

                    const screenRect = this._projectSlot(sx, sy, sz, slotWidth, slotHeight);

                    slots.push({
                        shelfId: shelf.shelf_id,
                        slotId: slotId,
                        data: heatmapItem,
                        screenRect: screenRect,
                        z: sz
                    });

                    slotIdx++;
                }
            }
        });

        return slots.sort((a, b) => a.z - b.z);
    }

    _project(x, y, z) {
        const cosY = Math.cos(this.viewAngleY);
        const sinY = Math.sin(this.viewAngleY);
        const cosX = Math.cos(this.viewAngleX);
        const sinX = Math.sin(this.viewAngleX);

        const x1 = x * cosY - z * sinY;
        const z1 = x * sinY + z * cosY;
        const y1 = y * cosX - z1 * sinX;
        const z2 = y * sinX + z1 * cosX;

        const scale = 400 / (400 + z2) * this.zoom;
        const screenX = this.width / 2 + x1 * scale + this.offsetX;
        const screenY = this.height / 2 + y1 * scale + this.offsetY;

        return { x: screenX, y: screenY, scale: scale, z: z2 };
    }

    _projectSlot(x, y, z, w, h) {
        const topLeft = this._project(x - w / 2, y - h / 2, z);
        const topRight = this._project(x + w / 2, y - h / 2, z);
        const bottomLeft = this._project(x - w / 2, y + h / 2, z);
        const bottomRight = this._project(x + w / 2, y + h / 2, z);

        const minX = Math.min(topLeft.x, topRight.x, bottomLeft.x, bottomRight.x);
        const maxX = Math.max(topLeft.x, topRight.x, bottomLeft.x, bottomRight.x);
        const minY = Math.min(topLeft.y, topRight.y, bottomLeft.y, bottomRight.y);
        const maxY = Math.max(topLeft.y, topRight.y, bottomLeft.y, bottomRight.y);

        return {
            x: minX,
            y: minY,
            width: maxX - minX,
            height: maxY - minY
        };
    }

    _getHeatColor(value, level) {
        if (this.heatmapType === 'ph') {
            if (value >= 6.5) return 'rgba(82, 196, 26, 0.8)';
            if (value >= 6.0) return 'rgba(250, 173, 20, 0.8)';
            if (value >= 5.5) return 'rgba(255, 77, 79, 0.8)';
            return 'rgba(207, 19, 34, 0.9)';
        } else if (this.heatmapType === 'mold') {
            if (value < 100) return 'rgba(82, 196, 26, 0.7)';
            if (value < 500) return 'rgba(250, 173, 20, 0.7)';
            if (value < 2000) return 'rgba(255, 77, 79, 0.7)';
            return 'rgba(207, 19, 34, 0.9)';
        } else {
            if (level === 'normal') return 'rgba(82, 196, 26, 0.7)';
            if (level === 'warning') return 'rgba(250, 173, 20, 0.7)';
            return 'rgba(255, 77, 79, 0.8)';
        }
    }

    render() {
        const ctx = this.ctx;
        ctx.clearRect(0, 0, this.width, this.height);

        this._drawGrid();
        this._drawShelves();
        this._drawHeatmapSlots();

        if (this.hoveredSlot) {
            this._drawHoverTooltip();
        }

        if (this.selectedSlot) {
            this._drawSelectedHighlight();
        }
    }

    _drawGrid() {
        const ctx = this.ctx;
        ctx.strokeStyle = 'rgba(0, 0, 0, 0.05)';
        ctx.lineWidth = 1;

        const gridSize = 50;
        for (let i = -5; i <= 5; i++) {
            const p1 = this._project(i * gridSize, 0, -200);
            const p2 = this._project(i * gridSize, 0, 200);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        }

        for (let i = -4; i <= 4; i++) {
            const p1 = this._project(-250, 0, i * gridSize);
            const p2 = this._project(250, 0, i * gridSize);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            ctx.stroke();
        }
    }

    _drawShelves() {
        const ctx = this.ctx;
        const shelfWidth = 100;
        const shelfHeight = 180;
        const shelfDepth = 30;

        const shelfDrawList = [];

        this.shelves.forEach((shelf, idx) => {
            const row = Math.floor(idx / 2);
            const col = idx % 2;
            const x = (col - 0.5) * (shelfWidth + 80);
            const y = 0;
            const z = (row - 1.5) * (shelfDepth + 60);

            const center = this._project(x, y, z);
            shelfDrawList.push({ shelf, x, y, z, centerZ: center.z, idx });
        });

        shelfDrawList.sort((a, b) => a.centerZ - b.centerZ);

        shelfDrawList.forEach(item => {
            this._drawSingleShelf(item.x, item.y, item.z, shelfWidth, shelfHeight, shelfDepth, item.shelf);
        });
    }

    _drawSingleShelf(x, y, z, w, h, d, shelfData) {
        const ctx = this.ctx;

        const faces = [];

        const frontTopLeft = this._project(x - w / 2, y - h / 2, z + d / 2);
        const frontTopRight = this._project(x + w / 2, y - h / 2, z + d / 2);
        const frontBottomLeft = this._project(x - w / 2, y + h / 2, z + d / 2);
        const frontBottomRight = this._project(x + w / 2, y + h / 2, z + d / 2);

        const backTopLeft = this._project(x - w / 2, y - h / 2, z - d / 2);
        const backTopRight = this._project(x + w / 2, y - h / 2, z - d / 2);
        const backBottomLeft = this._project(x - w / 2, y + h / 2, z - d / 2);
        const backBottomRight = this._project(x + w / 2, y + h / 2, z - d / 2);

        faces.push({
            type: 'top',
            z: (backTopLeft.z + backTopRight.z) / 2,
            points: [frontTopLeft, frontTopRight, backTopRight, backTopLeft],
            color: '#c89b6c'
        });

        faces.push({
            type: 'left',
            z: (backTopLeft.z + backBottomLeft.z) / 2,
            points: [frontTopLeft, backTopLeft, backBottomLeft, frontBottomLeft],
            color: '#a67c52'
        });

        faces.push({
            type: 'right',
            z: (frontTopRight.z + frontBottomRight.z) / 2,
            points: [frontTopRight, frontBottomRight, backBottomRight, backTopRight],
            color: '#8B6914'
        });

        faces.push({
            type: 'back',
            z: (backTopLeft.z + backBottomRight.z) / 2,
            points: [backTopLeft, backTopRight, backBottomRight, backBottomLeft],
            color: '#8B7355'
        });

        faces.push({
            type: 'bottom',
            z: (frontBottomLeft.z + frontBottomRight.z) / 2,
            points: [frontBottomLeft, backBottomLeft, backBottomRight, frontBottomRight],
            color: '#9c7a4f'
        });

        faces.sort((a, b) => a.z - b.z);

        faces.forEach(face => {
            ctx.beginPath();
            ctx.moveTo(face.points[0].x, face.points[0].y);
            for (let i = 1; i < face.points.length; i++) {
                ctx.lineTo(face.points[i].x, face.points[i].y);
            }
            ctx.closePath();
            ctx.fillStyle = face.color;
            ctx.fill();
            ctx.strokeStyle = 'rgba(80, 50, 20, 0.5)';
            ctx.lineWidth = 1;
            ctx.stroke();
        });

        const shelfY1 = y - h / 2 + h / 3;
        const shelfY2 = y + h / 2 - h / 3;

        const y1Front = this._project(0, shelfY1, z + d / 2);
        const y1Back = this._project(0, shelfY1, z - d / 2);
        const y2Front = this._project(0, shelfY2, z + d / 2);
        const y2Back = this._project(0, shelfY2, z - d / 2);

        ctx.strokeStyle = '#6b4423';
        ctx.lineWidth = 2;

        ctx.beginPath();
        ctx.moveTo(y1Front.x - w / 2 * frontTopLeft.scale, y1Front.y);
        ctx.lineTo(y1Front.x + w / 2 * frontTopRight.scale, y1Front.y);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(y2Front.x - w / 2 * frontBottomLeft.scale, y2Front.y);
        ctx.lineTo(y2Front.x + w / 2 * frontBottomRight.scale, y2Front.y);
        ctx.stroke();

        const labelPos = this._project(x, y - h / 2 - 15, z);
        ctx.font = '12px Microsoft YaHei';
        ctx.fillStyle = '#333';
        ctx.textAlign = 'center';
        ctx.fillText(shelfData.shelf_id || `书架`, labelPos.x, labelPos.y);
    }

    _drawHeatmapSlots() {
        const ctx = this.ctx;
        const slotWidth = 28;
        const slotHeight = 75;
        const gap = 5;

        const slotDrawList = [];

        this.shelves.forEach((shelf, shelfIdx) => {
            const row = Math.floor(shelfIdx / 2);
            const col = shelfIdx % 2;
            const baseX = (col - 0.5) * (100 + 80);
            const baseY = 0;
            const baseZ = (row - 1.5) * (30 + 60);

            const slotsPerRow = 3;
            const rows = 2;
            let slotIdx = 0;

            for (let r = 0; r < rows; r++) {
                for (let c = 0; c < slotsPerRow; c++) {
                    if (slotIdx >= (shelf.slots || 6)) break;

                    const slotId = `SLOT-${String.fromCharCode(65 + r)}${c + 1}`;
                    const sx = baseX + (c - slotsPerRow / 2 + 0.5) * (slotWidth + gap);
                    const sy = baseY + (r - rows / 2 + 0.5) * (slotHeight + gap) + 180 / 4;
                    const sz = baseZ + 8;

                    const heatmapItem = this.heatmapData.find(
                        h => h.shelf_id === shelf.shelf_id && h.slot_id === slotId
                    );

                    const center = this._project(sx, sy, sz);

                    slotDrawList.push({
                        shelfId: shelf.shelf_id,
                        slotId,
                        x: sx,
                        y: sy,
                        z: sz,
                        width: slotWidth,
                        height: slotHeight,
                        data: heatmapItem,
                        centerZ: center.z
                    });

                    slotIdx++;
                }
            }
        });

        slotDrawList.sort((a, b) => a.centerZ - b.z);

        slotDrawList.forEach(slot => {
            this._drawSingleSlot(slot);
        });
    }

    _drawSingleSlot(slot) {
        const ctx = this.ctx;
        const w = slot.width;
        const h = slot.height;

        const topLeft = this._project(slot.x - w / 2, slot.y - h / 2, slot.z);
        const topRight = this._project(slot.x + w / 2, slot.y - h / 2, slot.z);
        const bottomLeft = this._project(slot.x - w / 2, slot.y + h / 2, slot.z);
        const bottomRight = this._project(slot.x + w / 2, slot.y + h / 2, slot.z);

        const value = slot.data ? slot.data.value : 0;
        const level = slot.data ? slot.data.level : 'normal';
        const color = this._getHeatColor(value, level);

        ctx.beginPath();
        ctx.moveTo(topLeft.x, topLeft.y);
        ctx.lineTo(topRight.x, topRight.y);
        ctx.lineTo(bottomRight.x, bottomRight.y);
        ctx.lineTo(bottomLeft.x, bottomLeft.y);
        ctx.closePath();

        ctx.fillStyle = color;
        ctx.fill();
        ctx.strokeStyle = 'rgba(80, 50, 20, 0.6)';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.strokeStyle = 'rgba(255, 255, 255, 0.3)';
        ctx.lineWidth = 0.5;
        for (let i = 1; i < 5; i++) {
            const yRatio = i / 5;
            const leftX = topLeft.x + (bottomLeft.x - topLeft.x) * yRatio;
            const leftY = topLeft.y + (bottomLeft.y - topLeft.y) * yRatio;
            const rightX = topRight.x + (bottomRight.x - topRight.y) * yRatio;
            const rightY = topRight.y + (bottomRight.y - topRight.y) * yRatio;

            ctx.beginPath();
            ctx.moveTo(leftX, leftY);
            ctx.lineTo(rightX, rightY);
            ctx.stroke();
        }

        const isHovered = this.hoveredSlot &&
            this.hoveredSlot.shelfId === slot.shelfId &&
            this.hoveredSlot.slotId === slot.slotId;

        const isSelected = this.selectedSlot &&
            this.selectedSlot.shelfId === slot.shelfId &&
            this.selectedSlot.slotId === slot.slotId;

        if (isHovered || isSelected) {
            ctx.strokeStyle = isSelected ? '#1890ff' : '#fff';
            ctx.lineWidth = isSelected ? 3 : 2;
            ctx.beginPath();
            ctx.moveTo(topLeft.x, topLeft.y);
            ctx.lineTo(topRight.x, topRight.y);
            ctx.lineTo(bottomRight.x, bottomRight.y);
            ctx.lineTo(bottomLeft.x, bottomLeft.y);
            ctx.closePath();
            ctx.stroke();
        }
    }

    _drawHoverTooltip() {
        if (!this.hoveredSlot) return;

        const ctx = this.ctx;
        const slot = this.hoveredSlot;

        const heatmapItem = this.heatmapData.find(
            h => h.shelf_id === slot.shelfId && h.slot_id === slot.slotId
        );

        let text = `${slot.shelfId} / ${slot.slotId}`;
        if (heatmapItem) {
            if (this.heatmapType === 'ph') {
                text += `\npH: ${heatmapItem.value.toFixed(2)}`;
            } else if (this.heatmapType === 'mold') {
                text += `\n霉菌: ${heatmapItem.value.toFixed(0)} CFU/m³`;
            } else {
                text += `\n风险值: ${heatmapItem.value.toFixed(1)}`;
            }
            if (heatmapItem.book_title) {
                text += `\n${heatmapItem.book_title}`;
            }
        }

        const lines = text.split('\n');
        const padding = 8;
        const lineHeight = 18;
        const width = 150;
        const height = lines.length * lineHeight + padding * 2;

        const mouseX = this.lastMouseX - this.canvas.getBoundingClientRect().left;
        const mouseY = this.lastMouseY - this.canvas.getBoundingClientRect().top;

        let x = mouseX + 15;
        let y = mouseY + 15;

        if (x + width > this.width) x = mouseX - width - 15;
        if (y + height > this.height) y = mouseY - height - 15;

        ctx.fillStyle = 'rgba(0, 0, 0, 0.8)';
        ctx.beginPath();
        ctx.roundRect(x, y, width, height, 6);
        ctx.fill();

        ctx.fillStyle = '#fff';
        ctx.font = '12px Microsoft YaHei';
        ctx.textAlign = 'left';

        lines.forEach((line, i) => {
            ctx.fillText(line, x + padding, y + padding + (i + 1) * lineHeight - 4);
        });
    }

    _drawSelectedHighlight() {
    }

    zoomIn() {
        this.zoom = Math.min(3, this.zoom * 1.2);
        this.render();
    }

    zoomOut() {
        this.zoom = Math.max(0.3, this.zoom / 1.2);
        this.render();
    }

    resetView() {
        this.viewAngleX = 0.6;
        this.viewAngleY = 0.3;
        this.zoom = 1;
        this.offsetX = 0;
        this.offsetY = 0;
        this.selectedSlot = null;
        this.render();
    }

    rotateLeft() {
        this.viewAngleY -= 0.2;
        this.render();
    }

    rotateRight() {
        this.viewAngleY += 0.2;
        this.render();
    }

    focusShelf(shelfId) {
        const idx = this.shelves.findIndex(s => s.shelf_id === shelfId);
        if (idx >= 0) {
            const row = Math.floor(idx / 2);
            const col = idx % 2;
            this.offsetX = -col * 50;
            this.offsetY = (row - 1) * 30;
            this.zoom = 1.5;
            this.render();
        }
    }
}
