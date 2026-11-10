// Shared date-range and zone filter toolbar (analytics and reports).

import { api, h, toLocalInput } from "../core.js";

const PRESETS = [
    ["24h", "Last 24 hours", () => [new Date(Date.now() - 864e5), new Date()]],
    ["today", "Today", () => { const s = new Date(); s.setHours(0, 0, 0, 0); return [s, new Date()]; }],
    ["7d", "7 days", () => [new Date(Date.now() - 7 * 864e5), new Date()]],
    ["30d", "30 days", () => [new Date(Date.now() - 30 * 864e5), new Date()]],
    ["90d", "90 days", () => [new Date(Date.now() - 90 * 864e5), new Date()]],
];

/** Returns { element, value(), query() } and calls onChange when the filter changes. */
export async function rangeFilter(onChange, initial = "24h") {
    let zones = [];
    try { zones = await api("/api/zones"); } catch { /* zone filter optional */ }

    const [s0, e0] = PRESETS.find((p) => p[0] === initial)[2]();
    const start = h("input.input", { type: "datetime-local", value: toLocalInput(s0) });
    const end = h("input.input", { type: "datetime-local", value: toLocalInput(e0) });
    const zone = h("select.input",
        h("option", { value: "" }, "All zones (site total)"),
        zones.map((z) => h("option", { value: z.id }, `${z.name}${z.area ? ` · ${z.area}` : ""}`)));

    const buttons = PRESETS.map(([key, label, fn]) => h("button", { type: "button", class: key === initial ? "active" : "",
        onclick: (event) => {
            const [s, e] = fn();
            start.value = toLocalInput(s);
            end.value = toLocalInput(e);
            for (const b of event.currentTarget.parentElement.children) b.classList.remove("active");
            event.currentTarget.classList.add("active");
            onChange();
        } }, label));
    const segmented = h("div.segmented", buttons);
    const clearPreset = () => { for (const b of buttons) b.classList.remove("active"); };
    start.addEventListener("change", () => { clearPreset(); onChange(); });
    end.addEventListener("change", () => { clearPreset(); onChange(); });
    zone.addEventListener("change", onChange);

    const element = h("div.card", h("div.card-body", h("div.toolbar",
        h("div.field", h("span", "Period"), segmented),
        h("label.field", h("span", "From"), start),
        h("label.field", h("span", "To"), end),
        h("label.field", { style: { minWidth: "220px" } }, h("span", "Zone"), zone))));

    function value() {
        const s = new Date(start.value);
        const e = new Date(end.value);
        return { start: s, end: e, zoneId: zone.value || null,
                 zoneName: zone.value ? zone.selectedOptions[0].textContent : "All zones" };
    }
    function query() {
        const v = value();
        const params = new URLSearchParams({ start: v.start.toISOString(), end: v.end.toISOString() });
        if (v.zoneId) params.set("zone_id", v.zoneId);
        return params.toString();
    }
    return { element, value, query };
}
