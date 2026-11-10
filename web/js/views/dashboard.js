// Live overview: site KPIs, per-zone parking maps, camera health.

import { api, clear, errorBox, fmtAgo, fmtPercent, fmtTime, h, STATE_LABELS, stateBadge } from "../core.js";

const POLL_MS = 3000;

export async function render(ctx) {
    ctx.setHeader("Overview", "Live parking occupancy");
    let timer = null;
    let lastGood = null;
    let failures = 0;

    const tick = async () => {
        if (document.hidden) return;
        try {
            const status = await api("/api/status");
            lastGood = status;
            failures = 0;
            draw(ctx, status);
            ctx.setSiteName(status.site_name);
        } catch (error) {
            failures += 1;
            if (!lastGood) clear(ctx.content, errorBox(error));
            else if (failures === 2) {
                ctx.content.prepend(h("div.alert.error", `Live updates interrupted: ${error.message}. Retrying…`));
            }
        }
    };
    await tick();
    timer = setInterval(tick, POLL_MS);
    const onVisible = () => { if (!document.hidden) tick(); };
    document.addEventListener("visibilitychange", onVisible);
    ctx.onCleanup(() => {
        clearInterval(timer);
        document.removeEventListener("visibilitychange", onVisible);
    });
}

function draw(ctx, status) {
    const { site } = status;
    ctx.setHeader("Overview", `Live parking occupancy · updated ${fmtTime(status.updated_at)}`);

    const alerts = [];
    if (status.monitor.processing_enabled && !status.monitor.detector_ready) {
        alerts.push(h("div.alert.error", "Vehicle detection is not running: ",
                      status.monitor.detector_error || "model not loaded", ". Occupancy cannot be determined."));
    }
    if (!status.monitor.processing_enabled) {
        alerts.push(h("div.alert.warn", "Video processing is switched off on this server (PARKSIGHT_MONITOR_ENABLED=false)."));
    }
    const down = status.cameras.filter((c) => c.enabled && c.state !== "online");
    if (down.length) {
        alerts.push(h("div.alert.warn", `${down.length} camera${down.length > 1 ? "s are" : " is"} not delivering video: `,
                      down.map((c) => c.name).join(", "), ". Their spaces are shown as camera unavailable."));
    }
    if (status.monitor.last_snapshot_error) {
        alerts.push(h("div.alert.error", "History could not be saved: ", status.monitor.last_snapshot_error));
    }

    const known = site.capacity - site.unknown;
    const pct = (n) => (site.capacity ? `${(100 * n) / site.capacity}%` : "0");
    const kpis = h("div.grid.grid-4",
        kpi("Total capacity", site.capacity, "spaces",
            `${status.zones.length} zone${status.zones.length === 1 ? "" : "s"} monitored`),
        kpi("Occupied", site.occupied, null, h("span", h("span.dot.occupied"), " ",
            known ? `${fmtPercent(site.occupancy_rate)} of known spaces` : "no live data")),
        kpi("Available", site.available, null,
            site.unknown ? `${site.unknown} space${site.unknown === 1 ? "" : "s"} unknown` : "all spaces reporting"),
        h("div.card.kpi",
            h("div.kpi-label", "Occupancy"),
            h("div.kpi-value", fmtPercent(site.occupancy_rate)),
            h("div.kpi-bar",
                h("span", { style: { width: pct(site.occupied), background: "var(--occupied)" } }),
                h("span", { style: { width: pct(site.available), background: "var(--available)" } })),
            h("div.kpi-foot", `Cameras online: ${status.cameras_online} of ${status.cameras_total}`)));

    const zoneArea = status.zones.length
        ? h("div.zone-grid", status.zones.map(zoneCard))
        : h("div.card", h("div.empty", h("strong", "No parking zones configured yet"),
            ctx.isAdmin ? "Add a camera, then create a zone and draw its parking spaces."
                        : "An administrator needs to configure cameras and zones.",
            ctx.isAdmin ? h("div", h("a.btn.primary", { href: "#/cameras" }, "Set up cameras")) : null));

    const legend = h("div.legend",
        ["occupied", "available", "unknown", "camera_unavailable"].map((s) =>
            h("span", h("span.dot", { class: s }), STATE_LABELS[s])));

    const camerasCard = h("div.card",
        h("div.card-head", h("h2", "Camera health"), h("a.small", { href: "#/cameras" }, "Manage")),
        status.cameras.length
            ? h("div.camera-list", status.cameras.map((camera) => h("div.camera-row",
                h("div", h("div", h("b", camera.name)),
                  h("div.small.muted", camera.state === "online"
                      ? `Last frame ${fmtAgo(camera.last_frame_at)}`
                      : camera.message || camera.location || "")),
                stateBadge(camera.state))))
            : h("div.empty", "No cameras configured."));

    clear(ctx.content, alerts, kpis,
          h("div", { class: "toolbar", style: { justifyContent: "space-between", alignItems: "center" } },
            h("h2", "Parking zones"), legend),
          zoneArea, camerasCard);
}

function kpi(label, value, unit, foot) {
    return h("div.card.kpi", h("div.kpi-label", label),
             h("div.kpi-value", String(value), unit ? h("small", unit) : null),
             h("div.kpi-foot", foot));
}

export function parkingMap(zone, { labels = true } = {}) {
    const spaces = zone.spaces;
    let width = zone.frame_width;
    let height = zone.frame_height;
    if (!width || !height) {
        const xs = spaces.flatMap((s) => s.polygon.map((p) => p[0]));
        const ys = spaces.flatMap((s) => s.polygon.map((p) => p[1]));
        width = Math.max(...xs, 1) * 1.05;
        height = Math.max(...ys, 1) * 1.05;
    }
    const fontSize = Math.max(11, Math.round(width / 45));
    return h("svg.parking-map", { viewBox: `0 0 ${width} ${height}`, role: "img",
                                  "aria-label": `Parking layout of ${zone.name}` },
        spaces.map((space) => {
            const cx = space.polygon.reduce((a, p) => a + p[0], 0) / space.polygon.length;
            const cy = space.polygon.reduce((a, p) => a + p[1], 0) / space.polygon.length;
            const state = space.state || "unknown";
            return h("g",
                h("polygon", { points: space.polygon.map((p) => p.join(",")).join(" "), class: `s-${state}` },
                  h("title", `${space.label}: ${STATE_LABELS[state]}`)),
                labels ? h("text", { x: cx, y: cy, "font-size": fontSize }, space.label) : null);
        }));
}

function zoneCard(zone) {
    return h("div.card.zone-card",
        h("div.card-head",
            h("div", h("h2", zone.name), h("div.small.muted", [zone.area, zone.camera_name].filter(Boolean).join(" · "))),
            h("div.zone-stats",
                h("span", h("b", String(zone.available)), " free"),
                h("span", h("b", String(zone.occupied)), " occupied"),
                h("span", h("b", fmtPercent(zone.occupancy_rate)))) ),
        zone.spaces.length
            ? [parkingMap(zone),
               h("div.space-chips", zone.spaces.map((s) =>
                   h("span.chip", { class: s.state, title: STATE_LABELS[s.state] }, s.label)))]
            : h("div.empty", "No parking spaces drawn for this zone."));
}
