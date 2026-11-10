// Reports: CSV export and a paginated view of recorded snapshots.

import { api, clear, errorBox, fmtDateTime, fmtPercent, h, icon } from "../core.js";
import { rangeFilter } from "./range.js";

const PAGE = 50;

export async function render(ctx) {
    ctx.setHeader("Reports", "Export recorded occupancy history");
    const table = h("div.card");
    const exportButton = h("a.btn.primary", { href: "#", download: "" }, icon("download"), "Download CSV");
    let offset = 0;
    const filter = await rangeFilter(() => { offset = 0; load(); }, "7d");

    const exportCard = h("div.card", h("div.card-body", { style: { display: "flex", alignItems: "center",
                                                                   justifyContent: "space-between", gap: "16px", flexWrap: "wrap" } },
        h("div", h("h2", "Occupancy history (CSV)"),
          h("div.small.muted", "One row per zone per snapshot: time (site time zone and UTC), camera, zone, capacity, occupied, available, unknown and occupancy %. Opens in Excel or any spreadsheet.")),
        exportButton));

    clear(ctx.content, filter.element, exportCard, table);

    async function load() {
        const range = filter.value();
        if (!(range.start < range.end)) {
            clear(table, h("div.card-body", h("div.alert.error", "The start of the period must be before its end.")));
            exportButton.setAttribute("aria-disabled", "true");
            return;
        }
        exportButton.href = `/api/reports/occupancy.csv?${filter.query()}`;
        exportButton.removeAttribute("aria-disabled");
        clear(table, h("div.loading", "Loading records…"));
        try {
            const page = await api(`/api/history?${filter.query()}&limit=${PAGE}&offset=${offset}`);
            draw(page);
        } catch (error) {
            clear(table, h("div.card-body", errorBox(error)));
        }
    }

    function draw(page) {
        if (!page.total) {
            clear(table, h("div.empty", h("strong", "No records in this period"), "Nothing to export for the selected filter."));
            return;
        }
        const last = Math.min(page.offset + page.items.length, page.total);
        clear(table,
            h("div.card-head", h("h2", "Records"), h("span.meta", `${page.offset + 1}–${last} of ${page.total}`)),
            h("div.table-wrap", h("table.table",
                h("thead", h("tr", ["Time", "Zone", "Camera", "Capacity", "Occupied", "Available", "Unknown", "Occupancy"]
                    .map((t) => h("th", t)))),
                h("tbody", page.items.map((r) => h("tr",
                    h("td.nowrap", fmtDateTime(r.recorded_at)),
                    h("td", r.zone_name || h("span.muted", "Site total (legacy)")),
                    h("td", r.camera_name || "—"),
                    h("td.num", String(r.capacity)), h("td.num", String(r.occupied)),
                    h("td.num", String(r.available)), h("td.num", String(r.unknown)),
                    h("td.num", fmtPercent(r.capacity - r.unknown > 0 ? r.occupied / (r.capacity - r.unknown) : null, 1))))))),
            h("div.card-body", { style: { display: "flex", justifyContent: "flex-end", gap: "8px" } },
                h("button.btn.sm", { type: "button", disabled: page.offset === 0,
                                     onclick: () => { offset = Math.max(0, offset - PAGE); load(); } }, "Previous"),
                h("button.btn.sm", { type: "button", disabled: last >= page.total,
                                     onclick: () => { offset += PAGE; load(); } }, "Next")));
    }

    await load();
}
