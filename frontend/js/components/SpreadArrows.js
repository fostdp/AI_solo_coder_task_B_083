class SpreadArrows {
    constructor(canvas, directions = []) {
        this.canvas = canvas;
        this.ctx = canvas.getContext ? canvas.getContext('2d') : canvas;
        this.directions = directions;
        this.shelfPositions = {};
        this.visible = false;
        this.animationFrame = null;
        this.animationProgress = 0;
        this.isWebGL = !!(canvas.WebGLRenderingContext || canvas.WebGL2RenderingContext);
    }

    setDirections(directions) {
        this.directions = directions || [];
        if (this.visible) {
            this.draw();
        }
    }

    setShelfPositions(positions) {
        this.shelfPositions = positions || {};
        if (this.visible) {
            this.draw();
        }
    }

    draw() {
        if (!this.visible || !this.directions || this.directions.length === 0) {
            return;
        }

        this.clear();

        this.directions.forEach(direction => {
            const fromPos = this.shelfPositions[direction.from_shelf];
            const toPos = this.shelfPositions[direction.to_shelf];

            if (!fromPos || !toPos) {
                return;
            }

            this._drawArrow(fromPos, toPos, direction.weight);
        });

        this._startAnimation();
    }

    _drawArrow(from, to, weight) {
        const ctx = this.ctx;

        const lineWidth = this._getLineWidth(weight);
        const color = this._getArrowColor(weight);
        const opacity = this._getOpacity(weight);

        const arrowLength = 10;
        const arrowAngle = Math.PI / 6;

        const dx = to.x - from.x;
        const dy = to.y - from.y;
        const angle = Math.atan2(dy, dx);

        const endX = to.x - arrowLength * Math.cos(angle);
        const endY = to.y - arrowLength * Math.sin(angle);

        ctx.save();
        ctx.strokeStyle = color;
        ctx.fillStyle = color;
        ctx.lineWidth = lineWidth;
        ctx.globalAlpha = opacity;
        ctx.lineCap = 'round';

        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(endX, endY);
        ctx.stroke();

        ctx.beginPath();
        ctx.moveTo(to.x, to.y);
        ctx.lineTo(
            endX + arrowLength * Math.cos(angle - arrowAngle),
            endY + arrowLength * Math.sin(angle - arrowAngle)
        );
        ctx.lineTo(
            endX + arrowLength * Math.cos(angle + arrowAngle),
            endY + arrowLength * Math.sin(angle + arrowAngle)
        );
        ctx.closePath();
        ctx.fill();

        ctx.restore();

        if (this.animationProgress > 0) {
            this._drawFlowAnimation(from, to, weight, color);
        }
    }

    _drawFlowAnimation(from, to, weight, baseColor) {
        const ctx = this.ctx;
        const dx = to.x - from.x;
        const dy = to.y - from.y;
        const distance = Math.sqrt(dx * dx + dy * dy);

        const dotCount = Math.max(1, Math.floor(distance / 30));
        const dotRadius = this._getLineWidth(weight) * 1.5;

        for (let i = 0; i < dotCount; i++) {
            const progress = (this.animationProgress + i / dotCount) % 1;
            const dotX = from.x + dx * progress;
            const dotY = from.y + dy * progress;

            ctx.save();
            ctx.globalAlpha = 0.8 * (1 - Math.abs(progress - 0.5) * 2);
            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.arc(dotX, dotY, dotRadius, 0, Math.PI * 2);
            ctx.fill();
            ctx.restore();
        }
    }

    _getLineWidth(weight) {
        const minWidth = 1;
        const maxWidth = 6;
        return minWidth + (maxWidth - minWidth) * Math.min(weight, 1);
    }

    _getArrowColor(weight) {
        if (weight >= 0.8) {
            return '#cf1322';
        } else if (weight >= 0.5) {
            return '#ff4d4f';
        } else if (weight >= 0.3) {
            return '#faad14';
        } else {
            return '#52c41a';
        }
    }

    _getOpacity(weight) {
        return 0.5 + Math.min(weight, 1) * 0.5;
    }

    _startAnimation() {
        if (this.animationFrame) {
            return;
        }

        const animate = () => {
            if (!this.visible) {
                this.animationFrame = null;
                return;
            }

            this.animationProgress = (this.animationProgress + 0.015) % 1;
            this.draw();

            this.animationFrame = requestAnimationFrame(animate);
        };

        this.animationFrame = requestAnimationFrame(animate);
    }

    _stopAnimation() {
        if (this.animationFrame) {
            cancelAnimationFrame(this.animationFrame);
            this.animationFrame = null;
        }
        this.animationProgress = 0;
    }

    toggleVisibility(forceState) {
        if (typeof forceState === 'boolean') {
            this.visible = forceState;
        } else {
            this.visible = !this.visible;
        }

        if (this.visible) {
            this.draw();
        } else {
            this._stopAnimation();
            this.clear();
        }

        return this.visible;
    }

    clear() {
        if (this.ctx && this.canvas.clearRect) {
            const width = this.canvas.width || 0;
            const height = this.canvas.height || 0;
            this.ctx.clearRect(0, 0, width, height);
        }
    }
}

window.SpreadArrows = SpreadArrows;
