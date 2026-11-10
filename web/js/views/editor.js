// Parking-space calibration editor.
//
// Works like the original OpenCV selector (click the 4 corners of a space)
// but in the browser, on a live snapshot of the zone's camera:
//   * "Add space", then click 4 corners (Enter closes a 3+ point polygon).
//   * Click a space to select it; drag its corners to adjust.
//   * Rename or delete spaces in the side panel; Delete key removes the selection.
//   * "Show detections" displays the installer debug overlay.

import { api, ApiError, busy, clear, confirmDialog, errorBox, field, h, icon, toast } from "../core.js";
import { scalePolygon } from "./geometry.js";

export async function render(ctx) {
    if (!ctx.isAdmin) {
        location.hash = "#/zones";
        return;
    }
    const zoneId = ctx.params.zoneId;
    const zone = await api(`/api/zones/${zoneId}`);
    ctx.setHeader(`Edit spaces · ${zone.name}`, `Camera: ${zone.camera_name}`);

    const state = {
        spaces: zone.spaces.map((s) => ({ id: s.id, label: s.label, polygon: s.polygon.map((p) => [...p]) })),
        selected: null,
        drawing: null, // array of points while adding
        dirty: false,
        overlay: false,
        width: 0,
        height: 0,
        imageUrl: null,
    };

    const img = h("img", { alt: "Camera snapshot" });
    const svg = h("svg", { tabindex: "0" });
    const hint = h("div.editor-hint");
    const stage = h("div.editor-stage", img, svg, hint);
    const stageStatus = h("div");
    const list = h("div.space-list");
    const overlayToggle = h("input", { type: "checkbox" });
    const addButton = h("button.btn.primary", { type: "button", onclick: () => startDrawing() }, icon("plus"), "Add space");
    const saveButton = h("button.btn.primary", { type: "button", onclick: () => save() }, "Save layout");
    const refreshButton = h("button.btn", { type: "button", onclick: () => loadImage() }, icon("refresh"), "Refresh image");

    ctx.setHeader(`Edit spaces · ${zone.name}`, `Camera: ${zone.camera_name}`, [
        h("a.btn", { href: "#/zones" }, "Back to zones"), refreshButton, saveButton]);

    clear(ctx.content,
        h("div.editor",
            h("div", stage, stageStatus),
            h("div.card",
                h("div.card-head", h("h2", "Parking spaces"), h("span.meta", h("span#count"))),
                h("div.card-body", { style: { display: "flex", flexDirection: "column", gap: "12px" } },
                    addButton,
                    list,
                    h("label.check.small", overlayToggle, "Show detections (installer view)"),
                    h("div.small.muted",
                        "Click the four corners of each bay at ground level, following the painted lines. ",
                        "A space counts as occupied when a vehicle's tyre line falls inside it, so draw the bay itself, not the roof area of the vehicles.")))));

    overlayToggle.addEventListener("change", () => { state.overlay = overlayToggle.checked; loadImage(); });

    // --- Image -----------------------------------------------------------------

    async function loadImage() {
        clear(stageStatus, h("div.loading", "Fetching a frame from the camera…"));
        try {
            const response = await api(`/api/cameras/${zone.camera_id}/snapshot?overlay=${state.overlay}`, { raw: true });
            const blob = await response.blob();
            if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
            state.imageUrl = URL.createObjectURL(blob);
            await new Promise((resolve, reject) => {
                img.onload = resolve;
                img.onerror = () => reject(new Error("The camera image could not be decoded."));
                img.src = state.imageUrl;
            });
            const first = !state.width;
            state.width = img.naturalWidth;
            state.height = img.naturalHeight;
            if (first && zone.frame_width && (zone.frame_width !== state.width || zone.frame_height !== state.height)) {
                // Camera resolution changed since the layout was drawn: rescale.
                for (const space of state.spaces) {
                    space.polygon = scalePolygon(space.polygon, [zone.frame_width, zone.frame_height], [state.width, state.height]);
                }
                state.dirty = true;
                stageStatus.replaceChildren(h("div.alert.warn",
                    `The camera now delivers ${state.width}×${state.height} instead of ${zone.frame_width}×${zone.frame_height}. Spaces were rescaled — check them and save.`));
            } else {
                clear(stageStatus);
            }
            svg.setAttribute("viewBox", `0 0 ${state.width} ${state.height}`);
            redraw();
        } catch (error) {
            const message = error instanceof ApiError && error.status === 503
                ? `${error.message}. Check the camera on the Cameras page.` : error.message;
            clear(stageStatus, h("div.alert.error", message));
        }
    }

    // --- Drawing ----------------------------------------------------------------

    const VERTEX_R = () => Math.max(4, state.width / 140);

    function redraw() {
        const r = VERTEX_R();
        const fontSize = Math.max(12, state.width / 50);
        clear(svg);
        state.spaces.forEach((space, index) => {
            const selected = state.selected === index;
            const cx = space.polygon.reduce((a, p) => a + p[0], 0) / space.polygon.length;
            const cy = space.polygon.reduce((a, p) => a + p[1], 0) / space.polygon.length;
            svg.append(h("polygon", {
                points: space.polygon.map((p) => p.join(",")).join(" "),
                class: selected ? "selected" : "",
                onpointerdown: (event) => {
                    if (state.drawing) return;
                    event.stopPropagation();
                    select(index);
                },
            }));
            svg.append(h("text", { x: cx, y: cy, "font-size": fontSize }, space.label));
            if (selected) {
                space.polygon.forEach((point, vi) => {
                    svg.append(h("circle.vertex", { cx: point[0], cy: point[1], r,
                        onpointerdown: (event) => startDrag(event, index, vi) }));
                });
            }
        });
        if (state.drawing) {
            if (state.drawing.length) {
                svg.append(h("polyline", { points: state.drawing.map((p) => p.join(",")).join(" ") }));
            }
            state.drawing.forEach((p) => svg.append(h("circle.vertex.pending", { cx: p[0], cy: p[1], r })));
        }
        hint.textContent = state.drawing
            ? `Click corner ${state.drawing.length + 1} of 4 · Enter to finish early · Esc to cancel`
            : state.selected !== null ? "Drag the corners to adjust · Delete key removes the space"
                                      : "Click “Add space”, then click the 4 corners of a parking bay";
        drawList();
        saveButton.disabled = !state.width;
    }

    function drawList() {
        document.getElementById("count").textContent = `${state.spaces.length} defined`;
        if (!state.spaces.length) {
            clear(list, h("div.muted.small", "No spaces yet."));
            return;
        }
        clear(list, state.spaces.map((space, index) => {
            const input = h("input.input.sm", { value: space.label, maxlength: 30, "aria-label": "Space label" });
            input.addEventListener("focus", () => select(index, false));
            input.addEventListener("input", () => {
                space.label = input.value;
                state.dirty = true;
                const labels = svg.querySelectorAll("text");
                if (labels[index]) labels[index].textContent = input.value;
            });
            return h("div.space-item", { class: state.selected === index ? "selected" : "" },
                input,
                h("button.btn.sm.ghost.danger", { type: "button", title: "Delete space",
                    onclick: () => removeSpace(index) }, "✕"));
        }));
    }

    function select(index, rerender = true) {
        state.selected = index;
        if (rerender) redraw();
        else {
            list.querySelectorAll(".space-item").forEach((el, i) => el.classList.toggle("selected", i === index));
        }
    }

    function removeSpace(index) {
        state.spaces.splice(index, 1);
        state.selected = null;
        state.dirty = true;
        redraw();
    }

    function nextLabel() {
        const used = new Set(state.spaces.map((s) => s.label.toLowerCase()));
        let n = state.spaces.length + 1;
        while (used.has(`p${n}`)) n += 1;
        return `P${n}`;
    }

    function startDrawing() {
        if (!state.width) {
            toast("A camera image is needed to draw spaces.", "error");
            return;
        }
        state.drawing = [];
        state.selected = null;
        redraw();
        svg.focus();
    }

    function finishDrawing() {
        if (state.drawing && state.drawing.length >= 3) {
            state.spaces.push({ id: null, label: nextLabel(), polygon: state.drawing });
            state.selected = state.spaces.length - 1;
            state.dirty = true;
        }
        state.drawing = null;
        redraw();
    }

    function toImage(event) {
        const point = svg.createSVGPoint();
        point.x = event.clientX;
        point.y = event.clientY;
        const p = point.matrixTransform(svg.getScreenCTM().inverse());
        return [Math.round(Math.min(Math.max(p.x, 0), state.width)), Math.round(Math.min(Math.max(p.y, 0), state.height))];
    }

    svg.addEventListener("pointerdown", (event) => {
        if (!state.drawing) {
            if (state.selected !== null) { state.selected = null; redraw(); }
            return;
        }
        state.drawing.push(toImage(event));
        if (state.drawing.length === 4) finishDrawing();
        else redraw();
    });

    let drag = null;
    function startDrag(event, spaceIndex, vertexIndex) {
        event.stopPropagation();
        drag = { spaceIndex, vertexIndex };
        svg.setPointerCapture(event.pointerId);
    }
    svg.addEventListener("pointermove", (event) => {
        if (!drag) return;
        state.spaces[drag.spaceIndex].polygon[drag.vertexIndex] = toImage(event);
        state.dirty = true;
        redraw();
    });
    svg.addEventListener("pointerup", () => { drag = null; });

    const onKey = (event) => {
        if (event.target.tagName === "INPUT") return;
        if (event.key === "Escape" && state.drawing) { state.drawing = null; redraw(); }
        if (event.key === "Enter" && state.drawing) finishDrawing();
        if ((event.key === "Delete" || event.key === "Backspace") && state.selected !== null && !state.drawing) {
            event.preventDefault();
            removeSpace(state.selected);
        }
    };
    document.addEventListener("keydown", onKey);

    const onLeave = (event) => {
        if (state.dirty) { event.preventDefault(); event.returnValue = ""; }
    };
    window.addEventListener("beforeunload", onLeave);
    ctx.onCleanup(() => {
        document.removeEventListener("keydown", onKey);
        window.removeEventListener("beforeunload", onLeave);
        if (state.imageUrl) URL.revokeObjectURL(state.imageUrl);
    });

    // --- Save ------------------------------------------------------------------

    async function save() {
        const empty = state.spaces.find((s) => !s.label.trim());
        if (empty) {
            toast("Every space needs a label.", "error");
            return;
        }
        await busy(saveButton, async () => {
            const saved = await api(`/api/zones/${zoneId}/layout`, { method: "PUT", body: {
                frame_width: state.width, frame_height: state.height,
                spaces: state.spaces.map((s) => ({ id: s.id, label: s.label.trim(), polygon: s.polygon })) } });
            state.spaces = saved.spaces.map((s) => ({ id: s.id, label: s.label, polygon: s.polygon }));
            state.dirty = false;
            state.selected = null;
            redraw();
            toast(`Layout saved: ${saved.spaces.length} spaces. Monitoring restarts for this camera.`);
        });
    }

    // Warn when navigating away inside the app with unsaved changes.
    const guard = async (event) => {
        if (!state.dirty) return;
        const target = location.hash;
        history.replaceState(null, "", `#/zones/${zoneId}/layout`);
        event.stopImmediatePropagation();
        const leave = await confirmDialog({ title: "Unsaved changes",
            message: "You have unsaved changes to this layout. Leave without saving?",
            confirmLabel: "Discard changes", danger: true });
        if (leave) {
            state.dirty = false;
            location.hash = target;
        }
    };
    window.addEventListener("hashchange", guard, { capture: true });
    ctx.onCleanup(() => window.removeEventListener("hashchange", guard, { capture: true }));

    redraw();
    await loadImage();
}
