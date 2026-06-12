/**
 * Canvas 三维书架模型 + 病害热力图渲染器
 * 支持：伪3D透视、拖拽旋转、滚轮缩放、热力图叠加、格口点击
 */
class Shelf3DRenderer {
  constructor(canvasEl) {
    this.canvas = canvasEl;
    this.ctx = canvasEl.getContext('2d');
    this.dpr = window.devicePixelRatio || 1;
    this.resize();

    this.view = {
      rotY: 0.35,
      rotX: 0.12,
      zoom: 1.0,
      panX: 0,
      panY: 0,
    };

    this.shelf = null;
    this.slots = [];
    this.hitMap = [];
    this.hoverSlot = null;

    this.layers = { acidosis: true, mold: true, insect: true };
    this._isDragging = false;
    this._dragStart = null;
    this._didDrag = false;
    this._bindEvents();

    this._animId = null;
    this._lastRender = 0;
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    this.w = Math.floor(rect.width || this.canvas.width);
    this.h = Math.floor(rect.height || this.canvas.height);
    this.canvas.width = this.w * this.dpr;
    this.canvas.height = this.h * this.dpr;
    this.canvas.style.width = this.w + 'px';
    this.canvas.style.height = this.h + 'px';
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.cx = this.w / 2;
    this.cy = this.h / 2 + 30;
  }

  setShelf(shelfId, rows, cols, slots) {
    this.shelf = { id: shelfId, rows, cols };
    this.slots = slots || [];
    this.requestRender();
  }

  setLayers(layers) {
    this.layers = { ...this.layers, ...layers };
    this.requestRender();
  }

  setView(v) {
    Object.assign(this.view, v);
    this.requestRender();
  }

  resetView() {
    this.view = { rotY: 0.35, rotX: 0.12, zoom: 1.0, panX: 0, panY: 0 };
    this.requestRender();
  }

  rotate(dY, dX) {
    this.view.rotY += dY;
    this.view.rotX += dX;
    this.view.rotX = Math.max(-0.5, Math.min(0.6, this.view.rotX));
    this.requestRender();
  }

  zoomBy(factor) {
    this.view.zoom = Math.max(0.5, Math.min(2.5, this.view.zoom * factor));
    this.requestRender();
    return this.view.zoom;
  }

  _bindEvents() {
    const cv = this.canvas;

    cv.addEventListener('mousedown', (e) => {
      this._isDragging = true;
      this._didDrag = false;
      const p = this._getMouse(e);
      this._dragStart = { x: p.x, y: p.y, ry: this.view.rotY, rx: this.view.rotX, t: Date.now() };
    });

    window.addEventListener('mousemove', (e) => {
      const p = this._getMouse(e);
      if (this._isDragging && this._dragStart) {
        const dx = p.x - this._dragStart.x;
        const dy = p.y - this._dragStart.y;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this._didDrag = true;
        this.view.rotY = this._dragStart.ry + dx * 0.008;
        this.view.rotX = Math.max(-0.5, Math.min(0.6, this._dragStart.rx - dy * 0.006));
        this.requestRender();
      } else {
        this._updateHover(p);
      }
    });

    window.addEventListener('mouseup', (e) => {
      if (this._isDragging && !this._didDrag && Date.now() - (this._dragStart?.t || 0) < 300) {
        const p = this._getMouse(e);
        const slot = this._hitTest(p.x, p.y);
        if (slot) this._emit('slotClick', slot);
      }
      this._isDragging = false;
      this._dragStart = null;
    });

    cv.addEventListener('wheel', (e) => {
      e.preventDefault();
      const f = e.deltaY < 0 ? 1.12 : 1 / 1.12;
      const z = this.zoomBy(f);
      this._emit('zoom', z);
    }, { passive: false });

    cv.addEventListener('touchstart', (e) => {
      if (e.touches.length === 1) {
        const t = e.touches[0];
        this._isDragging = true;
        this._didDrag = false;
        this._dragStart = { x: t.clientX, y: t.clientY, ry: this.view.rotY, rx: this.view.rotX, t: Date.now() };
      }
    });
    cv.addEventListener('touchmove', (e) => {
      if (this._isDragging && e.touches.length === 1) {
        const t = e.touches[0];
        const dx = t.clientX - this._dragStart.x;
        const dy = t.clientY - this._dragStart.y;
        if (Math.abs(dx) > 3 || Math.abs(dy) > 3) this._didDrag = true;
        this.view.rotY = this._dragStart.ry + dx * 0.008;
        this.view.rotX = Math.max(-0.5, Math.min(0.6, this._dragStart.rx - dy * 0.006));
        this.requestRender();
        e.preventDefault();
      }
    });
    cv.addEventListener('touchend', (e) => {
      if (this._isDragging && !this._didDrag) {
        const p = this._dragStart;
        const rect = this.canvas.getBoundingClientRect();
        const slot = this._hitTest(p.x - rect.left, p.y - rect.top);
        if (slot) this._emit('slotClick', slot);
      }
      this._isDragging = false;
      this._dragStart = null;
    });
  }

  _getMouse(e) {
    const rect = this.canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  _listeners = {};
  on(evt, cb) { this._listeners[evt] = cb; }
  _emit(evt, data) { if (this._listeners[evt]) this._listeners[evt](data); }

  _updateHover(p) {
    const slot = this._hitTest(p.x, p.y);
    if (slot !== this.hoverSlot) {
      this.hoverSlot = slot;
      this.canvas.style.cursor = slot ? 'pointer' : (this._isDragging ? 'grabbing' : 'grab');
      this.requestRender();
    }
  }

  _hitTest(x, y) {
    for (let i = this.hitMap.length - 1; i >= 0; i--) {
      const h = this.hitMap[i];
      if (h.ctx.isPointInPath(x * this.dpr, y * this.dpr)) {
        return h.slot;
      }
    }
    return null;
  }

  requestRender() {
    if (this._animId) return;
    this._animId = requestAnimationFrame(() => this._render());
  }

  _render() {
    this._animId = null;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.w, this.h);
    this.hitMap = [];

    if (!this.shelf) {
      this._drawEmptyState();
      return;
    }

    this._drawFloorShadow();

    const { rows, cols } = this.shelf;
    const unitW = 70, unitH = 82, unitD = 60;
    const shelfW = cols * unitW;
    const shelfH = rows * unitH;

    const books = [];

    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const slotIdx = r * cols + c;
        const slot = this.slots[slotIdx];
        const bx = c * unitW - shelfW / 2 + unitW / 2;
        const by = -r * unitH + shelfH / 2 - unitH / 2;
        const bz = 0;
        const data = slot || {
          slot_id: `R${r + 1}-C${c + 1}`,
          scores: { acidosis: 0, mold: 0, insect: 0, overall: 0, level: 'SAFE' },
          metrics: {}, prediction: {},
        };
        books.push({
          r, c, bx, by, bz, unitW, unitH, unitD,
          data, slot,
        });
      }
    }

    const cosY = Math.cos(this.view.rotY);
    const sinY = Math.sin(this.view.rotY);
    const cosX = Math.cos(this.view.rotX);
    const sinX = Math.sin(this.view.rotX);

    books.forEach(b => {
      const { bx, by, bz } = b;
      let x1 = bx * cosY - bz * sinY;
      let z1 = bx * sinY + bz * cosY;
      let y1 = by;
      let y2 = y1 * cosX - z1 * sinX;
      let z2 = y1 * sinX + z1 * cosX;
      b._sx = this.cx + x1 * this.view.zoom;
      b._sy = this.cy + y2 * this.view.zoom;
      b._depth = z2;
    });
    books.sort((a, b) => a._depth - b._depth);

    this._drawShelfFrame(books, rows, cols, unitW, unitH, unitD, cosY, sinY, cosX, sinX);

    books.forEach(b => {
      this._drawSlot(ctx, b, cosY, sinY, cosX, sinX);
    });

    this._drawLegendOnCanvas();
  }

  _project(x, y, z, cosY, sinY, cosX, sinX) {
    const x1 = x * cosY - z * sinY;
    const z1 = x * sinY + z * cosY;
    const y1 = y;
    const y2 = y1 * cosX - z1 * sinX;
    return {
      sx: this.cx + x1 * this.view.zoom,
      sy: this.cy + y2 * this.view.zoom,
      depth: y1 * sinX + z1 * cosX,
    };
  }

  _drawEmptyState() {
    const ctx = this.ctx;
    ctx.fillStyle = 'rgba(148, 163, 184, .3)';
    ctx.font = '16px "PingFang SC", sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('🪵 选择左侧书架，加载3D模型与病害热力图', this.cx, this.cy);
    ctx.font = '12px sans-serif';
    ctx.fillStyle = 'rgba(148, 163, 184, .5)';
    ctx.fillText('可拖拽旋转 · 滚轮缩放 · 点击格口查看详情', this.cx, this.cy + 30);
  }

  _drawFloorShadow() {
    const ctx = this.ctx;
    const cx = this.cx, cy = this.cy + 160;
    const grad = ctx.createRadialGradient(cx, cy, 10, cx, cy, 350);
    grad.addColorStop(0, 'rgba(139, 90, 43, 0.18)');
    grad.addColorStop(1, 'rgba(139, 90, 43, 0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.ellipse(cx, cy, 380, 90, 0, 0, Math.PI * 2);
    ctx.fill();
  }

  _drawShelfFrame(books, rows, cols, uW, uH, uD, cosY, sinY, cosX, sinX) {
    const ctx = this.ctx;
    const w = cols * uW, h = rows * uH;
    const corners = [
      [-w / 2,  h / 2, -uD / 2], [ w / 2,  h / 2, -uD / 2],
      [ w / 2,  h / 2,  uD / 2], [-w / 2,  h / 2,  uD / 2],
      [-w / 2, -h / 2, -uD / 2], [ w / 2, -h / 2, -uD / 2],
      [ w / 2, -h / 2,  uD / 2], [-w / 2, -h / 2,  uD / 2],
    ].map(p => this._project(p[0], p[1], p[2], cosY, sinY, cosX, sinX));

    ctx.save();
    this._quad(ctx, [corners[4], corners[5], corners[6], corners[7]], '#3d2a18', '#241810');
    this._quad(ctx, [corners[0], corners[3], corners[7], corners[4]], '#5a3a20', '#3d2818');
    this._quad(ctx, [corners[5], corners[1], corners[2], corners[6]], '#4a2f1a', '#2d1c10');
    this._quad(ctx, [corners[0], corners[1], corners[5], corners[4]], '#6b4423', '#4a2e17');
    this._quad(ctx, [corners[3], corners[2], corners[6], corners[7]], '#8b5a2b', '#5c3a1b');

    for (let r = 1; r < rows; r++) {
      const yy = h / 2 - r * uH;
      const p1 = this._project(-w / 2, yy, -uD / 2, cosY, sinY, cosX, sinX);
      const p2 = this._project( w / 2, yy, -uD / 2, cosY, sinY, cosX, sinX);
      const p3 = this._project( w / 2, yy,  uD / 2, cosY, sinY, cosX, sinX);
      const p4 = this._project(-w / 2, yy,  uD / 2, cosY, sinY, cosX, sinX);
      this._quad(ctx, [p1, p2, p3, p4], '#7a4e28', '#4a2e17', 0.9);
    }
    ctx.restore();
  }

  _quad(ctx, pts, fillTop, fillBot, alpha = 1) {
    if (pts.length < 4) return;
    const grad = ctx.createLinearGradient(
      Math.min(...pts.map(p => p.sx)),
      Math.min(...pts.map(p => p.sy)),
      Math.max(...pts.map(p => p.sx)),
      Math.max(...pts.map(p => p.sy)),
    );
    ctx.globalAlpha = alpha;
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, fillBot);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.moveTo(pts[0].sx, pts[0].sy);
    pts.slice(1).forEach(p => ctx.lineTo(p.sx, p.sy));
    ctx.closePath();
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,.4)';
    ctx.lineWidth = 0.8;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  _drawSlot(ctx, b, cosY, sinY, cosX, sinX) {
    const { bx, by, unitW: uW, unitH: uH, unitD: uD, data: d, slot } = b;
    const pad = 3;
    const iw = uW - pad * 2;
    const ih = uH - pad * 2;
    const id = uD - pad * 2;

    const corners = [
      [bx - iw / 2, by + ih / 2, -id / 2], [bx + iw / 2, by + ih / 2, -id / 2],
      [bx + iw / 2, by + ih / 2,  id / 2], [bx - iw / 2, by + ih / 2,  id / 2],
      [bx - iw / 2, by - ih / 2, -id / 2], [bx + iw / 2, by - ih / 2, -id / 2],
      [bx + iw / 2, by - ih / 2,  id / 2], [bx - iw / 2, by - ih / 2,  id / 2],
    ].map(p => this._project(p[0], p[1], p[2], cosY, sinY, cosX, sinX));

    const isHover = this.hoverSlot && slot && this.hoverSlot.slot_id === slot.slot_id;
    const hoverInset = isHover ? 1.5 : 0;

    let heatColor = null;
    let heatAlpha = 0;
    if (slot) {
      const s = d.scores || {};
      const components = [];
      if (this.layers.acidosis) components.push({ v: s.acidosis || 0, c: [99, 102, 241] });
      if (this.layers.mold) components.push({ v: s.mold || 0, c: [13, 148, 136] });
      if (this.layers.insect) components.push({ v: s.insect || 0, c: [180, 83, 9] });
      if (components.length) {
        let r = 0, g = 0, bl = 0, wsum = 0;
        components.forEach(cmp => {
          r += cmp.c[0] * cmp.v;
          g += cmp.c[1] * cmp.v;
          bl += cmp.c[2] * cmp.v;
          wsum += cmp.v;
        });
        if (wsum > 0) {
          heatColor = `rgb(${Math.round(r / wsum)}, ${Math.round(g / wsum)}, ${Math.round(bl / wsum)})`;
          heatAlpha = Math.min(0.88, 0.2 + wsum / components.length * 0.9);
        }
      }
    }

    const paperColor = slot ? this._paperColorByPh(d.metrics?.ph || 6.8) : '#e8d9b8';
    const paperGrad = ctx.createLinearGradient(
      corners[4].sx, corners[4].sy, corners[0].sx, corners[0].sy
    );
    paperGrad.addColorStop(0, paperColor);
    paperGrad.addColorStop(1, this._darken(paperColor, 0.25));

    ctx.save();
    if (heatColor && heatAlpha > 0) {
      ctx.globalAlpha = 1;
      ctx.fillStyle = paperGrad;
    } else {
      ctx.fillStyle = paperGrad;
    }

    const frontPath = new Path2D();
    frontPath.moveTo(corners[4].sx + hoverInset, corners[4].sy + hoverInset);
    frontPath.lineTo(corners[5].sx - hoverInset, corners[5].sy + hoverInset);
    frontPath.lineTo(corners[1].sx - hoverInset, corners[1].sy - hoverInset);
    frontPath.lineTo(corners[0].sx + hoverInset, corners[0].sy - hoverInset);
    frontPath.closePath();
    ctx.fill(frontPath);
    ctx.strokeStyle = isHover ? 'rgba(253, 224, 71, .9)' : 'rgba(30, 20, 10, .7)';
    ctx.lineWidth = isHover ? 2 : 0.8;
    ctx.stroke(frontPath);

    if (slot) {
      this.hitMap.push({ ctx: this.ctx, path: frontPath, slot: b });
    }

    if (heatColor && heatAlpha > 0) {
      ctx.globalAlpha = heatAlpha;
      const hGrad = ctx.createRadialGradient(
        (corners[4].sx + corners[1].sx) / 2, (corners[4].sy + corners[1].sy) / 2, 4,
        (corners[4].sx + corners[1].sx) / 2, (corners[4].sy + corners[1].sy) / 2, iw * this.view.zoom
      );
      hGrad.addColorStop(0, heatColor);
      hGrad.addColorStop(0.7, this._alphaColor(heatColor, 0.6));
      hGrad.addColorStop(1, this._alphaColor(heatColor, 0));
      ctx.fillStyle = hGrad;
      ctx.fill(frontPath);
    }
    ctx.globalAlpha = 1;

    if (slot) {
      this._drawBookSpines(ctx, corners, d, slot);
    }

    const lvl = d.scores?.level;
    if (slot && lvl && lvl !== 'SAFE') {
      const badgeColors = {
        LOW: '#65a30d', MEDIUM: '#f59e0b', HIGH: '#ea580c', CRITICAL: '#dc2626',
      };
      const bc = badgeColors[lvl] || '#16a34a';
      const cx = (corners[5].sx + corners[1].sx) / 2;
      const cy = corners[5].sy + 10;
      ctx.beginPath();
      ctx.arc(cx, cy, 5, 0, Math.PI * 2);
      ctx.fillStyle = bc;
      ctx.fill();
      ctx.strokeStyle = '#fff';
      ctx.lineWidth = 1;
      ctx.stroke();
    }
    ctx.restore();
  }

  _drawBookSpines(ctx, corners, d, slot) {
    const l = corners[4], r = corners[5], tr = corners[1], tl = corners[0];
    const topY = (l.sy + tl.sy) / 2;
    const botY = l.sy;
    const leftX = l.sx, rightX = r.sx;
    const width = rightX - leftX;
    const bookCount = slot?.book_count || 5;
    const nBooks = Math.max(3, Math.min(12, bookCount));
    const dynasty = d.book_dynasty || slot?.book_dynasty || '';
    const spBaseColors = dynasty === '明'
      ? ['#7a5230', '#8b3a3a', '#2f4858', '#5a4e37', '#6b3a3a']
      : ['#4a3a6b', '#2c5a4a', '#6b5a3a', '#5b2a3a', '#3a4a6b'];

    for (let i = 0; i < nBooks; i++) {
      const t = i / nBooks;
      const t2 = (i + 0.85) / nBooks;
      const x1 = leftX + t * width + 1;
      const x2 = leftX + t2 * width - 1;
      const c = spBaseColors[i % spBaseColors.length];
      const grad = ctx.createLinearGradient(x1, 0, x2, 0);
      grad.addColorStop(0, this._darken(c, 0.3));
      grad.addColorStop(0.5, c);
      grad.addColorStop(1, this._darken(c, 0.35));
      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.moveTo(x1, botY);
      ctx.lineTo(x2, botY);
      const tiltTop = (tr.sx - tl.sx) / nBooks;
      ctx.lineTo(x2 + tiltTop * 0.1, topY);
      ctx.lineTo(x1 + tiltTop * 0.1, topY);
      ctx.closePath();
      ctx.fill();
      ctx.strokeStyle = 'rgba(0,0,0,.3)';
      ctx.lineWidth = 0.4;
      ctx.stroke();
    }
  }

  _drawLegendOnCanvas() {
    const ctx = this.ctx;
    const x = this.w - 150, y = 14;
    ctx.fillStyle = 'rgba(15, 23, 42, .75)';
    ctx.strokeStyle = 'rgba(51, 65, 85, .8)';
    ctx.lineWidth = 1;
    this._roundRect(ctx, x, y, 136, 92, 6, true, true);
    ctx.font = '10px "PingFang SC", sans-serif';
    ctx.fillStyle = '#94a3b8';
    ctx.textAlign = 'left';
    ctx.fillText('病害图例', x + 10, y + 18);
    const items = [
      { t: '酸化', c: '#6366f1', on: this.layers.acidosis },
      { t: '霉变', c: '#0d9488', on: this.layers.mold },
      { t: '虫蛀', c: '#b45309', on: this.layers.insect },
    ];
    items.forEach((it, i) => {
      const yy = y + 34 + i * 18;
      ctx.globalAlpha = it.on ? 1 : 0.25;
      ctx.fillStyle = it.c;
      ctx.beginPath();
      ctx.arc(x + 18, yy - 3, 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = it.on ? '#e2e8f0' : '#64748b';
      ctx.fillText(it.t, x + 30, yy);
      ctx.globalAlpha = 1;
    });
  }

  _roundRect(ctx, x, y, w, h, r, fill, stroke) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
    if (fill) ctx.fill();
    if (stroke) ctx.stroke();
  }

  _paperColorByPh(ph) {
    if (ph >= 7.0) return '#f2e6c8';
    if (ph >= 6.5) return '#ecd9b0';
    if (ph >= 6.0) return '#e0c087';
    if (ph >= 5.5) return '#cda468';
    if (ph >= 5.0) return '#b98a4a';
    return '#8f6634';
  }

  _darken(hex, amt) {
    const c = hex.replace('#', '');
    const num = parseInt(c, 16);
    let r = (num >> 16) & 0xff, g = (num >> 8) & 0xff, b = num & 0xff;
    r = Math.max(0, Math.round(r * (1 - amt)));
    g = Math.max(0, Math.round(g * (1 - amt)));
    b = Math.max(0, Math.round(b * (1 - amt)));
    return `rgb(${r}, ${g}, ${b})`;
  }

  _alphaColor(rgbStr, alpha) {
    const m = rgbStr.match(/\d+/g);
    if (!m) return rgbStr;
    return `rgba(${m[0]}, ${m[1]}, ${m[2]}, ${alpha})`;
  }
}
