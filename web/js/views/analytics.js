// Historical analytics. Every number comes from recorded snapshots; when a
// period has no data the page says so instead of drawing placeholder values.

import { api, clear, errorBox, fmtDateTime, fmtNumber, fmtPercent, h } from "../core.js";
import { barChart, legend, lineChart } from "../charts.js";
import { rangeFilter } from "./range.js";

const COLORS = { occupancy: "#2459d6", available: "#1f9d55", peak: "#d23f3f", average: "#2459d6" };

export async function render(ctx) {
    ctx.setHeader("Analytics", "Occupancy trends from recorded history");
    const results = h("div", { style: { display: "flex", flexDirection: "column", gap: "20px" } });
    let seq = 0;
    const filter = await rangeFilter(load, "7d");
    clear(ctx.content, filter.element, results);

    async function load() {
        const mine = ++seq;
        const range = filter.value();
        if (!(range.start < range.end)) {
            clear(results, h("div.alert.error", "The start of the period must be before its end."));
            return;
        }
        clear(results, h("div.loading", "Loading history…"));
        try {
            const data = await api(`/api/analytics?${filter.query()}`);
            if (mine === seq) draw(data, range);
        } catch (error) {
            if (mine === seq) clear(results, errorBox(error));
        }
    }

    function draw(data, range) {
        const s = data.summary;
        if (!s.samples) {
            clear(results, h("div.card", h("div.empty", h("strong", "No history recorded in this period"),
                "ParkSight stores a snapshot at the interval set in Settings while cameras are monitored. ",
                "Choose a different period or zone.")));
            return;
        }
        const spanDays = (range.end - range.start) / 864e5;
        const tFormat = (t, long) => long || spanDays > 2
            ? t.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })
            : t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
        const series = data.series.map((p) => ({ t: new Date(p.bucket), ...p }));
        const gapMs = data.bucket_seconds * 1000 * 2.5;

        const kpis = h("div.grid.grid-4",
            stat("Average occupancy", fmtPercent(s.avg_rate),
                 s.avg_occupied === null ? "of spaces with a known state" : `${fmtNumber(s.avg_occupied, 1)} spaces on average`),
            stat("Peak occupancy", fmtPercent(s.peak_rate), s.peak_at ? `at ${fmtDateTime(s.peak_at)}` : ""),
            stat("Lowest availability", fmtNumber(s.min_available),
                 s.min_available === null ? "no snapshot with every space known" : "free spaces at the busiest moment"),
            stat("Snapshots", String(s.samples),
                 s.complete_samples < s.samples
                     ? `${s.samples - s.complete_samples} with some spaces unknown (camera offline or starting)`
                     : `${fmtDateTime(s.first_at)} – ${fmtDateTime(s.last_at)}`));

        const occupancyChart = card("Occupancy over time",
            `${range.zoneName} · averaged per ${bucketLabel(data.bucket_seconds)}`,
            lineChart({ label: "Occupancy over time", tFormat, gapMs, yMax: 1, yFormat: (v) => fmtPercent(v),
                        series: [{ name: "Occupancy", color: COLORS.occupancy, area: true,
                                   points: series.map((p) => ({ t: p.t, y: p.rate })) }] }));

        const availableChart = card("Available capacity over time", "Average free spaces",
            lineChart({ label: "Available spaces over time", tFormat, gapMs,
                        yFormat: (v) => fmtNumber(v, v % 1 ? 1 : 0),
                        series: [{ name: "Available", color: COLORS.available, area: true,
                                   points: series.map((p) => ({ t: p.t, y: p.available })) },
                                 { name: "Capacity", color: "#8b97a8",
                                   points: series.map((p) => ({ t: p.t, y: p.capacity })) }] }));

        const daily = card("Daily peak and average", `Days in ${data.timezone}`,
            [legend([["Peak", COLORS.peak], ["Average", COLORS.average]]),
             barChart({ label: "Daily peak and average occupancy", yMax: 1, yFormat: (v) => fmtPercent(v),
                        colors: [COLORS.peak, COLORS.average], names: ["Peak", "Average"],
                        bars: data.daily.map((d) => ({
                            label: new Date(`${d.day}T00:00:00`).toLocaleDateString([], { month: "short", day: "numeric" }),
                            values: [d.peak_rate, d.avg_rate] })) })]);

        const hourly = card("Busiest hours", `Average occupancy by hour of day (${data.timezone})`,
            barChart({ label: "Average occupancy by hour", yMax: 1, yFormat: (v) => fmtPercent(v),
                       colors: [COLORS.average], names: ["Average"],
                       bars: Array.from({ length: 24 }, (_, hour) => {
                           const row = data.hourly.find((r) => r.hour === hour);
                           return { label: `${String(hour).padStart(2, "0")}:00`, values: [row ? row.avg_rate : null] };
                       }) }));

        const zones = data.zones.length ? card("Zone comparison", "Average (bar) and peak (red mark) occupancy",
            h("div.bars", data.zones.map((z) => h("div.bar-row",
                h("div", h("b", z.zone_name), h("div.small.muted", z.zone_id ? z.camera_name : "deleted zone")),
                h("div.track", h("div.fill", { style: { width: `${(z.avg_rate || 0) * 100}%` } }),
                  z.peak_rate !== null ? h("div.peak", { style: { left: `calc(${z.peak_rate * 100}% - 1px)` } }) : null),
                h("div.small.num", `${fmtPercent(z.avg_rate)} avg · ${fmtPercent(z.peak_rate)} peak`))))) : null;

        clear(results, kpis, h("div.grid.grid-2", occupancyChart, availableChart),
              h("div.grid.grid-2", daily, hourly), zones);
    }

    await load();
}

function stat(label, value, foot) {
    return h("div.card.kpi", h("div.kpi-label", label), h("div.kpi-value", value), h("div.kpi-foot", foot));
}

function card(title, meta, body) {
    return h("div.card", h("div.card-head", h("h2", title), h("span.meta", meta)), h("div.card-body", body));
}

function bucketLabel(seconds) {
    if (seconds < 3600) return `${seconds / 60} min`;
    if (seconds < 86400) return `${seconds / 3600} h`;
    return "day";
}
