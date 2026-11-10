// Camera management.

import { api, busy, clear, confirmDialog, errorBox, field, fmtAgo, fmtDateTime, h, icon, modal,
         stateBadge, toast } from "../core.js";

export async function render(ctx) {
    const addButton = ctx.isAdmin
        ? h("button.btn.primary", { type: "button", onclick: () => cameraDialog(null).then((saved) => saved && load()) },
            icon("plus"), "Add camera")
        : null;
    ctx.setHeader("Cameras", "Video sources and connection health", [addButton]);

    const listCard = h("div.card");
    const eventsCard = h("div.card");
    clear(ctx.content, listCard, eventsCard);

    async function load() {
        try {
            const [cameras, events] = await Promise.all([api("/api/cameras"), api("/api/cameras/events?limit=25")]);
            drawList(listCard, cameras, ctx, load);
            drawEvents(eventsCard, events);
        } catch (error) {
            clear(listCard, h("div.card-body", errorBox(error)));
        }
    }
    await load();
    const timer = setInterval(() => { if (!document.hidden && !document.querySelector(".overlay")) load(); }, 5000);
    ctx.onCleanup(() => clearInterval(timer));
}

function drawList(card, cameras, ctx, reload) {
    if (!cameras.length) {
        clear(card, h("div.empty", h("strong", "No cameras yet"),
            "Add an RTSP camera from your CCTV network, or a demonstration video file.",
            ctx.isAdmin ? h("div", h("button.btn.primary", { type: "button",
                onclick: () => cameraDialog(null).then((s) => s && reload()) }, icon("plus"), "Add camera")) : null));
        return;
    }
    clear(card,
        h("div.card-head", h("h2", "Cameras"), h("span.meta", `${cameras.length} configured`)),
        h("div.table-wrap", h("table.table",
            h("thead", h("tr", ["Camera", "Source", "Status", "Last frame", "Zones", ""].map((t) => h("th", t)))),
            h("tbody", cameras.map((camera) => h("tr",
                h("td", h("b", camera.name), h("div.sub", camera.location || "—")),
                h("td", h("div.mono", camera.source_type === "file" ? `video: ${camera.source_url}` : camera.source_url),
                  camera.username ? h("div.sub", `user ${camera.username}${camera.has_password ? " · password set" : ""}`) : null),
                h("td", stateBadge(camera.status.state),
                  camera.status.message && camera.status.state !== "online"
                      ? h("div.sub", { style: { maxWidth: "280px" } }, camera.status.message) : null),
                h("td.nowrap", camera.status.state === "online" ? fmtAgo(camera.status.last_frame_at) : "—",
                  camera.status.frame_size ? h("div.sub", camera.status.frame_size.join("×")) : null),
                h("td.num", String(camera.zone_count)),
                h("td.actions", ctx.isAdmin ? [
                    h("button.btn.sm", { type: "button", onclick: (e) => busy(e.currentTarget, async () => {
                        await api(`/api/cameras/${camera.id}`, { method: "PATCH", body: { enabled: !camera.enabled } });
                        toast(`${camera.name} ${camera.enabled ? "disabled" : "enabled"}.`);
                        reload();
                    }) }, camera.enabled ? "Disable" : "Enable"),
                    h("button.btn.sm", { type: "button", onclick: () => cameraDialog(camera).then((s) => s && reload()) }, "Edit"),
                    h("button.btn.sm.danger", { type: "button", onclick: async () => {
                        const ok = await confirmDialog({
                            title: "Delete camera",
                            message: `Delete "${camera.name}"? Its ${camera.zone_count} zone(s) and their parking spaces will be removed. Recorded history is kept.`,
                            confirmLabel: "Delete camera", danger: true });
                        if (!ok) return;
                        try {
                            await api(`/api/cameras/${camera.id}`, { method: "DELETE" });
                            toast("Camera deleted.");
                            reload();
                        } catch (error) { toast(error.message, "error"); }
                    } }, "Delete"),
                ] : null)))))));
}

function drawEvents(card, events) {
    clear(card, h("div.card-head", h("h2", "Recent connection events"), h("span.meta", "Latest 25")),
        events.length
            ? h("div.table-wrap", h("table.table",
                h("thead", h("tr", ["Time", "Camera", "Event", "Details"].map((t) => h("th", t)))),
                h("tbody", events.map((e) => h("tr",
                    h("td.nowrap", fmtDateTime(e.recorded_at)), h("td", e.camera_name || "—"),
                    h("td", stateBadge(e.status)), h("td.small", e.message || "—"))))))
            : h("div.empty", "No connection events recorded."));
}

async function cameraDialog(camera) {
    let videos = [];
    try { videos = (await api("/api/videos")).files; } catch { /* only needed for file sources */ }

    return modal((close) => {
        const isEdit = Boolean(camera);
        const result = h("div");
        const type = h("select.input", { name: "source_type" },
            h("option", { value: "rtsp", selected: !camera || camera.source_type === "rtsp" }, "RTSP / IP camera"),
            h("option", { value: "file", selected: camera?.source_type === "file" }, "Demonstration video file"));
        const rtspUrl = h("input.input", { name: "rtsp_url", placeholder: "rtsp://192.168.1.64:554/Streaming/Channels/101",
                                           value: camera?.source_type === "rtsp" ? camera.source_url : "" });
        const videoSelect = h("select.input", { name: "video" },
            videos.length ? videos.map((v) => h("option", { value: v, selected: camera?.source_url === v }, v))
                          : h("option", { value: "" }, "No video files in data/videos"));
        const username = h("input.input", { name: "username", autocomplete: "off", value: camera?.username || "" });
        const password = h("input.input", { name: "password", type: "password", autocomplete: "new-password",
            placeholder: camera?.has_password ? "Unchanged (stored encrypted)" : "" });
        const clearPassword = h("input", { type: "checkbox", name: "clear_password" });
        const transport = h("select.input", { name: "rtsp_transport" },
            ["tcp", "udp"].map((t) => h("option", { value: t, selected: (camera?.rtsp_transport || "tcp") === t },
                                        t.toUpperCase())));
        const rtspFields = h("div.form-grid.full",
            h("div.full", field("Stream URL", rtspUrl, "credentials may be included; they are stored encrypted and never shown")),
            field("Username", username, "optional"),
            field("Password", password, "optional"),
            field("Transport", transport, "TCP is more reliable on most networks"),
            camera?.has_password ? h("label.check", { style: { alignSelf: "end" } }, clearPassword, "Remove stored password") : h("span"));
        const fileFields = h("div.full", field("Video file", videoSelect, "files placed in the server's video directory"));
        const sync = () => {
            rtspFields.hidden = type.value !== "rtsp";
            fileFields.hidden = type.value !== "file";
        };
        type.addEventListener("change", sync);
        sync();

        const name = h("input.input", { name: "name", required: true, maxlength: 100, value: camera?.name || "" });
        const location = h("input.input", { name: "location", maxlength: 200, value: camera?.location || "",
                                            placeholder: "e.g. Basement 1, north ramp" });
        const enabled = h("input", { type: "checkbox", checked: camera ? camera.enabled : true });

        const payload = () => {
            const isRtsp = type.value === "rtsp";
            const body = {
                name: name.value.trim(), location: location.value.trim(), source_type: type.value,
                source_url: isRtsp ? rtspUrl.value.trim() : videoSelect.value,
                username: isRtsp ? username.value.trim() || null : null,
                rtsp_transport: transport.value, enabled: enabled.checked,
            };
            if (isRtsp && password.value) body.password = password.value;
            if (isRtsp && clearPassword.checked) body.password = "";
            return body;
        };

        const testButton = h("button.btn", { type: "button", onclick: () => busy(testButton, async () => {
            clear(result, h("div.alert.info", "Connecting… this can take up to 10 seconds."));
            const body = payload();
            const request = { source_type: body.source_type, source_url: body.source_url,
                              username: body.username, rtsp_transport: body.rtsp_transport };
            if (body.password !== undefined) request.password = body.password;
            if (isEdit) request.camera_id = camera.id;
            const response = await api("/api/cameras/test", { method: "POST", body: request });
            clear(result, h("div.alert", { class: response.ok ? "ok" : "error" }, response.message));
        }) }, "Test connection");

        const save = h("button.btn.primary", { type: "button", onclick: () => busy(save, async () => {
            clear(result);
            try {
                const body = payload();
                const saved = isEdit
                    ? await api(`/api/cameras/${camera.id}`, { method: "PUT", body })
                    : await api("/api/cameras", { method: "POST", body });
                toast(`Camera "${saved.name}" saved.`);
                close(saved);
            } catch (error) {
                clear(result, errorBox(error));
            }
        }) }, isEdit ? "Save changes" : "Add camera");

        return {
            title: isEdit ? `Edit ${camera.name}` : "Add camera",
            body: [h("div.form-grid",
                field("Name", name), field("Location", location),
                h("div.full", field("Source type", type)),
                rtspFields, fileFields,
                h("label.check.full", enabled, "Enabled — process this camera's video")),
                result],
            left: testButton,
            actions: [h("button.btn", { type: "button", onclick: () => close() }, "Cancel"), save],
        };
    });
}
