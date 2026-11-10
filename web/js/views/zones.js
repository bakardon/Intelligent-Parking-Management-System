// Parking zones: create, rename, assign to camera, delete; open the layout editor.

import { api, busy, clear, confirmDialog, errorBox, field, h, icon, modal, toast } from "../core.js";
import { parkingMap } from "./dashboard.js";

export async function render(ctx) {
    const addButton = ctx.isAdmin
        ? h("button.btn.primary", { type: "button", onclick: () => zoneDialog(null).then((z) => z && load()) },
            icon("plus"), "Add zone")
        : null;
    ctx.setHeader("Zones & spaces", "Parking areas and the spaces each camera watches", [addButton]);

    async function load() {
        try {
            const [zones, cameras] = await Promise.all([api("/api/zones"), api("/api/cameras")]);
            draw(zones, cameras);
        } catch (error) {
            clear(ctx.content, errorBox(error));
        }
    }

    function draw(zones, cameras) {
        if (!cameras.length) {
            clear(ctx.content, h("div.card", h("div.empty", h("strong", "Add a camera first"),
                "Each zone belongs to one camera, because parking spaces are drawn in that camera's view.",
                ctx.isAdmin ? h("div", h("a.btn.primary", { href: "#/cameras" }, "Go to cameras")) : null)));
            return;
        }
        if (!zones.length) {
            clear(ctx.content, h("div.card", h("div.empty", h("strong", "No zones yet"),
                "Create a zone (for example “Basement 1 – North”) and draw its parking spaces on the camera image.",
                ctx.isAdmin ? h("div", h("button.btn.primary", { type: "button",
                    onclick: () => zoneDialog(null).then((z) => z && load()) }, icon("plus"), "Add zone")) : null)));
            return;
        }
        clear(ctx.content, h("div.zone-grid", zones.map((zone) => h("div.card.zone-card",
            h("div.card-head",
                h("div", h("h2", zone.name),
                  h("div.small.muted", [zone.area, `Camera: ${zone.camera_name}`].filter(Boolean).join(" · "))),
                h("span.badge.plain.viewer", `${zone.spaces.length} spaces`)),
            zone.spaces.length ? parkingMap(zone)
                               : h("div.empty", "No spaces drawn yet."),
            ctx.isAdmin ? h("div.card-body", { style: { display: "flex", gap: "8px", justifyContent: "flex-end" } },
                h("button.btn.sm.danger", { type: "button", onclick: async () => {
                    const ok = await confirmDialog({ title: "Delete zone",
                        message: `Delete "${zone.name}" and its ${zone.spaces.length} parking spaces? Recorded history is kept.`,
                        confirmLabel: "Delete zone", danger: true });
                    if (!ok) return;
                    try {
                        await api(`/api/zones/${zone.id}`, { method: "DELETE" });
                        toast("Zone deleted.");
                        load();
                    } catch (error) { toast(error.message, "error"); }
                } }, "Delete"),
                h("button.btn.sm", { type: "button", onclick: () => zoneDialog(zone).then((z) => z && load()) }, "Rename / move"),
                h("a.btn.sm.primary", { href: `#/zones/${zone.id}/layout` }, "Edit spaces")) : null))));
    }

    async function zoneDialog(zone) {
        const cameras = await api("/api/cameras");
        return modal((close) => {
            const result = h("div");
            const name = h("input.input", { name: "name", maxlength: 100, value: zone?.name || "",
                                            placeholder: "e.g. Level 1 – North" });
            const area = h("input.input", { name: "area", maxlength: 100, value: zone?.area || "",
                                            placeholder: "e.g. Level 1, Basement 2, Visitor lot" });
            const camera = h("select.input", cameras.map((c) =>
                h("option", { value: c.id, selected: zone?.camera_id === c.id }, c.name)));
            const warning = h("div.alert.warn", { hidden: true },
                "Moving the zone to another camera deletes its drawn spaces: they only fit the original camera's view.");
            camera.addEventListener("change", () => {
                warning.hidden = !zone || Number(camera.value) === zone.camera_id || !zone.spaces.length;
            });
            const save = h("button.btn.primary", { type: "button", onclick: () => busy(save, async () => {
                clear(result);
                const body = { name: name.value.trim(), area: area.value.trim(), camera_id: Number(camera.value) };
                try {
                    const saved = zone ? await api(`/api/zones/${zone.id}`, { method: "PUT", body })
                                       : await api("/api/zones", { method: "POST", body });
                    toast(`Zone "${saved.name}" saved.`);
                    close(saved);
                    if (!zone) location.hash = `#/zones/${saved.id}/layout`;
                } catch (error) { clear(result, errorBox(error)); }
            }) }, zone ? "Save" : "Create and draw spaces");
            return {
                title: zone ? `Edit ${zone.name}` : "Add zone",
                body: [field("Zone name", name), field("Floor / area", area, "used to group zones"),
                       field("Camera", camera), warning, result],
                actions: [h("button.btn", { type: "button", onclick: () => close() }, "Cancel"), save],
            };
        });
    }

    await load();
}
