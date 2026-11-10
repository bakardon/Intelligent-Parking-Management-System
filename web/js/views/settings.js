// Settings (administrators only): site, detection, smoothing, cameras,
// history and data retention, system information.

import { api, busy, clear, confirmDialog, errorBox, field, fmtDateTime, h, toast } from "../core.js";

const CLASSES = ["car", "motorcycle", "bus", "truck"];

export async function render(ctx) {
    ctx.setHeader("Settings", "Detection, history and data retention");
    const [settings, system] = await Promise.all([api("/api/settings"), api("/api/system")]);

    const num = (name, attrs) => h("input.input", { type: "number", name, value: settings[name], ...attrs });
    const result = h("div");
    const form = h("form.form-grid", { onsubmit: (e) => e.preventDefault() },
        h("div.form-section", "Site"),
        field("Site name", h("input.input", { name: "site_name", value: settings.site_name, maxlength: 100 })),
        field("Reporting time zone", h("input.input", { name: "timezone", value: settings.timezone,
                                                        placeholder: "Asia/Karachi" }), "IANA name, e.g. Asia/Karachi"),

        h("div.form-section", "Vehicle detection"),
        field("Confidence threshold", num("confidence_threshold", { min: 0.05, max: 0.95, step: 0.05 }),
              "higher = fewer false detections, more misses"),
        field("Processing interval (s)", num("processing_interval_seconds", { min: 0.2, max: 60, step: 0.1 }),
              "how often each camera frame is analysed"),
        h("div.field.full", h("span", "Vehicle types counted"),
          h("div", { style: { display: "flex", gap: "18px", flexWrap: "wrap" } },
            CLASSES.map((c) => h("label.check", h("input", { type: "checkbox", "data-class": c,
                                                            checked: settings.vehicle_classes.includes(c) }),
                                 c[0].toUpperCase() + c.slice(1))))),

        h("div.form-section", "Temporal smoothing"),
        field("Observation window", num("history_length", { min: 1, max: 60, step: 1 }), "last N analysed frames"),
        field("Votes to mark occupied", num("occupied_threshold", { min: 1, max: 60, step: 1 }),
              "space is occupied when at least this many of the window saw a vehicle"),

        h("div.form-section", "Camera health"),
        field("Mark video as stale after (s)", num("stale_after_seconds", { min: 3, max: 600, step: 1 })),
        field("Reconnect delay min / max (s)", h("div", { style: { display: "flex", gap: "8px" } },
            num("reconnect_min_seconds", { min: 1, max: 300, step: 1 }),
            num("reconnect_max_seconds", { min: 1, max: 3600, step: 1 })), "doubles after each failure"),

        h("div.form-section", "History and privacy"),
        field("Snapshot interval (s)", num("snapshot_interval_seconds", { min: 10, max: 3600, step: 1 }),
              "how often occupancy is written to history"),
        field("Retention (days)", num("retention_days", { min: 1, max: 3650, step: 1 }),
              "older history and camera events are deleted automatically"));

    const save = h("button.btn.primary", { type: "button", onclick: () => busy(save, async () => {
        clear(result);
        const body = {};
        for (const el of form.querySelectorAll("[name]")) {
            body[el.name] = el.type === "number" ? Number(el.value) : el.value.trim();
        }
        body.vehicle_classes = [...form.querySelectorAll("[data-class]")].filter((c) => c.checked).map((c) => c.dataset.class);
        try {
            const saved = await api("/api/settings", { method: "PUT", body });
            ctx.setSiteName(saved.site_name);
            clear(result, h("div.alert.ok", "Settings saved. Cameras pick up the changes within a few seconds."));
        } catch (error) { clear(result, errorBox(error)); }
    }) }, "Save settings");

    const history = system.history;
    const before = h("input.input", { type: "date" });
    const deleteButton = h("button.btn.danger", { type: "button", onclick: async () => {
        if (!before.value) { toast("Choose a date first.", "error"); return; }
        const date = new Date(`${before.value}T00:00:00`);
        const ok = await confirmDialog({ title: "Delete history",
            message: `Permanently delete all occupancy history recorded before ${date.toLocaleDateString()}? This cannot be undone.`,
            confirmLabel: "Delete history", danger: true, requireText: "DELETE" });
        if (!ok) return;
        await busy(deleteButton, async () => {
            const response = await api("/api/history/delete", { method: "POST",
                body: { before: date.toISOString(), confirm: "DELETE" } });
            toast(`${response.deleted} history records deleted.`);
        });
    } }, "Delete history before date");

    const monitor = system.monitor;
    clear(ctx.content,
        h("div.grid.grid-3",
            h("div.card.span-2", h("div.card-head", h("h2", "Operational settings")),
              h("div.card-body", form, h("div", { style: { marginTop: "16px", display: "flex", gap: "12px",
                                                          alignItems: "center", flexWrap: "wrap" } }, save, result))),
            h("div", { style: { display: "flex", flexDirection: "column", gap: "16px" } },
                h("div.card", h("div.card-head", h("h2", "Stored history")),
                  h("div.card-body", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
                    info("Records", String(history.records)),
                    info("Oldest", fmtDateTime(history.oldest)),
                    info("Newest", fmtDateTime(history.newest)),
                    info("Table size", `${(history.size_bytes / 1048576).toFixed(1)} MB`),
                    h("div.small.muted", "ParkSight stores occupancy counts only. No video, images, faces or number plates are recorded."),
                    field("Delete records before", before), deleteButton)),
                h("div.card", h("div.card-head", h("h2", "System")),
                  h("div.card-body", { style: { display: "flex", flexDirection: "column", gap: "10px" } },
                    info("Version", system.version),
                    info("Database schema", system.schema_version),
                    info("Detection model", `${system.model_file} on ${system.device.toUpperCase()}`),
                    info("Detector", monitor.detector_ready ? "Running" : (monitor.detector_error || "Not running")),
                    info("Last inference", monitor.inference_ms ? `${monitor.inference_ms.toFixed(0)} ms` : "—"),
                    info("Last history snapshot", fmtDateTime(monitor.last_snapshot_at)),
                    h("a.small", { href: "/api/docs", target: "_blank", rel: "noopener" }, "API documentation"))))));
}

function info(label, value) {
    return h("div", { style: { display: "flex", justifyContent: "space-between", gap: "12px" } },
             h("span.muted", label), h("span", { style: { textAlign: "right" } }, value));
}
