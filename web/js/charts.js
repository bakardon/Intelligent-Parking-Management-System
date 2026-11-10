// Small dependency-free SVG charts with hover tooltips. Charts are drawn at
// their container's real pixel width (re-drawn on resize) so text stays legible.

import { h } from "./core.js";

const H = 240;
const PAD = { top: 14, right: 14, bottom: 28, left: 46 };

function niceMax(value) {
    if (value <= 0) return 1;
    const exp = 10 ** Math.floor(Math.log10(value));
    for (const step of [1, 2, 2.5, 5, 10]) {
        if (step * exp >= value) return step * exp;
    }
    return 10 * exp;
}

function responsive(draw) {
    const wrap = h("div.chart-wrap");
    let last = 0;
    const observer = new ResizeObserver((entries) => {
        const width = Math.round(entries[0].contentRect.width);
        if (width > 0 && Math.abs(width - last) > 2) {
            last = width;
            wrap.replaceChildren(...draw(width));
        }
    });
    observer.observe(wrap);
    return wrap;
}

function yAxis(svg, W, y, top, yFormat) {
    for (let i = 0; i <= 4; i++) {
        const value = (top / 4) * i;
        svg.append(h("line.grid-line", { x1: PAD.left, x2: W - PAD.right, y1: y(value), y2: y(value) }),
                   h("text.axis-label", { x: PAD.left - 8, y: y(value) + 4, "text-anchor": "end" }, yFormat(value)));
    }
}

/**
 * Time-series line chart.
 * series: [{ name, color, points: [{ t: Date, y: number|null }], area?: bool }]
 * Gaps (null, or a jump larger than `gapMs`) break the line instead of
 * drawing through periods without data.
 */
export function lineChart({ series, yMax, yFormat = (v) => v, tFormat, gapMs, label }) {
    return responsive((W) => {
        const all = series.flatMap((s) => s.points.filter((p) => p.y !== null));
        const tMin = Math.min(...all.map((p) => p.t.getTime()));
        const tMax = Math.max(...all.map((p) => p.t.getTime()));
        const top = yMax ?? niceMax(Math.max(...all.map((p) => p.y), 0));
        const span = Math.max(tMax - tMin, 1);
        const x = (t) => PAD.left + ((t.getTime() - tMin) / span) * (W - PAD.left - PAD.right);
        const y = (v) => PAD.top + (1 - v / top) * (H - PAD.top - PAD.bottom);

        const svg = h("svg.chart", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": label });
        yAxis(svg, W, y, top, yFormat);
        const ticks = Math.max(2, Math.min(6, Math.floor(W / 120)));
        for (let i = 0; i <= ticks; i++) {
            const t = new Date(tMin + (span * i) / ticks);
            svg.append(h("text.axis-label", { x: x(t), y: H - 8,
                "text-anchor": i === 0 ? "start" : i === ticks ? "end" : "middle" }, tFormat(t)));
        }
        for (const s of series) {
            const segments = [];
            let current = [];
            let prev = null;
            for (const p of s.points) {
                if (p.y === null || (prev && gapMs && p.t - prev.t > gapMs)) {
                    if (current.length) segments.push(current);
                    current = [];
                }
                if (p.y !== null) current.push(p);
                prev = p;
            }
            if (current.length) segments.push(current);
            for (const seg of segments) {
                const d = seg.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.y).toFixed(1)}`).join("");
                if (s.area && seg.length > 1) {
                    svg.append(h("path.area", { d: `${d}L${x(seg.at(-1).t)},${y(0)}L${x(seg[0].t)},${y(0)}Z`, fill: s.color }));
                }
                if (seg.length === 1) svg.append(h("circle", { cx: x(seg[0].t), cy: y(seg[0].y), r: 3, fill: s.color }));
                else svg.append(h("path.line", { d, stroke: s.color }));
            }
        }

        const tip = h("div.tooltip", { hidden: true });
        const hover = h("line.hover-line", { y1: PAD.top, y2: H - PAD.bottom, visibility: "hidden" });
        svg.append(hover);
        const base = series[0].points;
        svg.addEventListener("pointermove", (event) => {
            const rect = svg.getBoundingClientRect();
            const vx = event.clientX - rect.left;
            let best = null;
            for (const p of base) {
                if (best === null || Math.abs(x(p.t) - vx) < Math.abs(x(best.t) - vx)) best = p;
            }
            if (!best) return;
            const index = base.indexOf(best);
            hover.setAttribute("x1", x(best.t));
            hover.setAttribute("x2", x(best.t));
            hover.setAttribute("visibility", "visible");
            tip.hidden = false;
            tip.replaceChildren(h("div", tFormat(best.t, true)),
                ...series.map((s) => h("div", `${s.name}: `,
                    h("b", s.points[index]?.y === null ? "no data" : yFormat(s.points[index].y)))));
            tip.style.left = `${x(best.t)}px`;
            tip.style.top = `${event.clientY - rect.top}px`;
        });
        svg.addEventListener("pointerleave", () => { tip.hidden = true; hover.setAttribute("visibility", "hidden"); });
        return [svg, tip];
    });
}

/** Vertical bar chart. bars: [{ label, values: [number|null] }]; one color per value index. */
export function barChart({ bars, colors, yMax, yFormat = (v) => v, names, label }) {
    return responsive((W) => {
        const top = yMax ?? niceMax(Math.max(...bars.flatMap((b) => b.values.filter((v) => v !== null)), 0));
        const y = (v) => PAD.top + (1 - v / top) * (H - PAD.top - PAD.bottom);
        const svg = h("svg.chart", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": label });
        yAxis(svg, W, y, top, yFormat);
        const slot = (W - PAD.left - PAD.right) / Math.max(bars.length, 1);
        const groupWidth = Math.min(slot * 0.75, 48);
        const barWidth = groupWidth / colors.length;
        const labelEvery = Math.ceil(bars.length / Math.max(1, Math.floor(W / 56)));
        const tip = h("div.tooltip", { hidden: true });
        bars.forEach((bar, i) => {
            const x0 = PAD.left + slot * i + (slot - groupWidth) / 2;
            bar.values.forEach((v, j) => {
                if (v === null) return;
                const rect = h("rect", { x: x0 + j * barWidth, y: y(v), width: Math.max(barWidth - 2, 1),
                                         height: Math.max(y(0) - y(v), 0), fill: colors[j], rx: 2 });
                rect.addEventListener("pointermove", (event) => {
                    const box = svg.getBoundingClientRect();
                    tip.hidden = false;
                    tip.replaceChildren(h("div", bar.label), ...bar.values.map((value, k) =>
                        h("div", `${names[k]}: `, h("b", value === null ? "no data" : yFormat(value)))));
                    tip.style.left = `${event.clientX - box.left}px`;
                    tip.style.top = `${event.clientY - box.top}px`;
                });
                rect.addEventListener("pointerleave", () => { tip.hidden = true; });
                svg.append(rect);
            });
            if (i % labelEvery === 0) {
                svg.append(h("text.axis-label", { x: x0 + groupWidth / 2, y: H - 8, "text-anchor": "middle" }, bar.label));
            }
        });
        return [svg, tip];
    });
}

export function legend(items) {
    return h("div.legend", items.map(([name, color]) =>
        h("span", h("span.dot", { style: { background: color } }), name)));
}
