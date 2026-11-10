// Core helpers: API client, DOM builder, formatting, toasts, modals.

export class ApiError extends Error {
    constructor(status, message) {
        super(message);
        this.status = status;
    }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(handler) { onUnauthorized = handler; }

export async function api(path, { method = "GET", body, raw = false } = {}) {
    const options = { method, headers: { "X-Requested-With": "ParkSight" }, credentials: "same-origin" };
    if (body !== undefined) {
        options.headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(body);
    }
    let response;
    try {
        response = await fetch(path, options);
    } catch {
        throw new ApiError(0, "Cannot reach the ParkSight server. Check the network connection.");
    }
    if (response.status === 401 && !path.startsWith("/api/auth/")) {
        onUnauthorized();
    }
    if (!response.ok) {
        let message = `Request failed (${response.status})`;
        try {
            const data = await response.json();
            if (data.detail) message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
        } catch { /* not JSON */ }
        throw new ApiError(response.status, message);
    }
    if (raw) return response;
    if (response.status === 204) return null;
    return response.json();
}

// --- DOM -------------------------------------------------------------------

const SVG_NS = "http://www.w3.org/2000/svg";
const SVG_TAGS = new Set(["svg", "g", "path", "polygon", "polyline", "line", "rect", "circle", "text", "title"]);

/** h("div.card#id", {attrs / on*: handlers}, ...children). Text is never parsed as HTML. */
export function h(spec, attrs, ...children) {
    if (attrs == null || typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs)) {
        children.unshift(attrs);
        attrs = {};
    }
    const [, tag = "div", rest = ""] = spec.match(/^([a-z0-9]+)?(.*)$/i);
    const el = SVG_TAGS.has(tag) ? document.createElementNS(SVG_NS, tag) : document.createElement(tag);
    for (const part of rest.match(/[.#][^.#]+/g) || []) {
        if (part[0] === ".") el.classList.add(part.slice(1));
        else el.id = part.slice(1);
    }
    for (const [key, value] of Object.entries(attrs)) {
        if (value === undefined || value === null || value === false) continue;
        if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2), value);
        else if (key === "class") el.setAttribute("class", [el.getAttribute("class"), value].filter(Boolean).join(" "));
        else if (key === "style" && typeof value === "object") Object.assign(el.style, value);
        else if (key === "value" && "value" in el) el.value = value;
        else if (key === "checked" || key === "selected" || key === "disabled") el[key] = Boolean(value);
        else el.setAttribute(key, value === true ? "" : value);
    }
    append(el, children);
    return el;
}

function append(el, children) {
    for (const child of children.flat(Infinity)) {
        if (child === null || child === undefined || child === false) continue;
        el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
}

export function clear(el, ...children) {
    el.replaceChildren();
    append(el, children);
    return el;
}

const ICONS = {
    dashboard: "M3 13h8V3H3zm0 8h8v-6H3zm10 0h8V11h-8zm0-18v6h8V3z",
    camera: "M4 7h3l2-3h6l2 3h3a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V8a1 1 0 0 1 1-1zm8 3a4 4 0 1 0 0 8 4 4 0 0 0 0-8z",
    layout: "M3 3h18v18H3zM3 9h18M9 21V9",
    chart: "M4 20V10m6 10V4m6 16v-8m4 8H2",
    report: "M14 3H6a1 1 0 0 0-1 1v16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1V8zm0 0v5h5M9 13h6m-6 4h6",
    users: "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2m7-10a4 4 0 1 0 0-8 4 4 0 0 0 0 8zm13 10v-2a4 4 0 0 0-3-3.9M16 3.1a4 4 0 0 1 0 7.8",
    settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm7.4-3a7.4 7.4 0 0 0-.1-1.3l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2.2-1.3L14.4 3h-4l-.4 2.4a7.6 7.6 0 0 0-2.2 1.3l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.6l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2.2 1.3l.4 2.4h4l.4-2.4a7.6 7.6 0 0 0 2.2-1.3l2.4 1 2-3.4-2-1.6c.1-.4.1-.9.1-1.3z",
    plus: "M12 5v14M5 12h14",
    download: "M12 3v12m0 0-4-4m4 4 4-4M4 17v3h16v-3",
    refresh: "M20 11a8 8 0 1 0-2.3 5.7M20 4v7h-7",
};

export function icon(name) {
    return h("svg", { viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.8",
                      "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true" },
             h("path", { d: ICONS[name] }));
}

// --- Formatting ------------------------------------------------------------

export function fmtPercent(rate, digits = 0) {
    return rate === null || rate === undefined ? "—" : `${(rate * 100).toFixed(digits)}%`;
}

export function fmtNumber(value, digits = 0) {
    return value === null || value === undefined ? "—" : Number(value).toFixed(digits);
}

export function fmtDateTime(value) {
    if (!value) return "—";
    return new Date(value).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

export function fmtTime(value) {
    if (!value) return "—";
    return new Date(value).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function fmtAgo(value) {
    if (!value) return "never";
    const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
    if (seconds < 5) return "just now";
    if (seconds < 60) return `${seconds}s ago`;
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    return fmtDateTime(value);
}

export const STATE_LABELS = {
    occupied: "Occupied", available: "Available", unknown: "Unknown",
    camera_unavailable: "Camera unavailable",
    online: "Online", offline: "Offline", stale: "No video", connecting: "Connecting",
    pending: "Starting", disabled: "Disabled", not_monitored: "Not monitored",
};

export function stateBadge(state) {
    return h("span.badge", { class: state }, STATE_LABELS[state] || state);
}

// --- Toasts and modals -----------------------------------------------------

export function toast(message, kind = "ok") {
    const el = h("div.toast", { class: kind === "error" ? "error" : "", role: "status" }, message);
    document.getElementById("toasts").append(el);
    setTimeout(() => el.remove(), kind === "error" ? 7000 : 3500);
}

/** Opens a modal. `build(close)` returns {title, body, actions[], wide}. Resolves with close(value). */
export function modal(build) {
    return new Promise((resolve) => {
        let overlay;
        const close = (value) => {
            overlay.remove();
            document.removeEventListener("keydown", onKey);
            resolve(value);
        };
        const onKey = (event) => { if (event.key === "Escape") close(undefined); };
        const { title, body, actions = [], wide = false, left } = build(close);
        overlay = h("div.overlay", { onmousedown: (e) => { if (e.target === overlay) close(undefined); } },
            h("div.modal", { class: wide ? "wide" : "", role: "dialog", "aria-modal": "true", "aria-label": title },
                h("div.modal-head", h("h2", title),
                  h("button.btn.ghost.sm", { type: "button", onclick: () => close(undefined), "aria-label": "Close" }, "✕")),
                h("div.modal-body", body),
                h("div.modal-foot", left ? h("div.left", left) : null, actions)));
        document.body.append(overlay);
        document.addEventListener("keydown", onKey);
        const first = overlay.querySelector("input:not([type=hidden]), select, textarea");
        if (first) first.focus();
    });
}

export function confirmDialog({ title, message, confirmLabel = "Confirm", danger = false, requireText }) {
    return modal((close) => {
        const input = requireText ? h("input.input", { placeholder: requireText, autocomplete: "off" }) : null;
        const button = h("button.btn", { class: danger ? "danger solid" : "primary", type: "button",
                                         disabled: Boolean(requireText),
                                         onclick: () => close(true) }, confirmLabel);
        if (input) input.addEventListener("input", () => { button.disabled = input.value !== requireText; });
        return {
            title,
            body: [h("p", { style: { margin: 0 } }, message),
                   input ? h("label.field", h("span", `Type ${requireText} to confirm`), input) : null],
            actions: [h("button.btn", { type: "button", onclick: () => close(false) }, "Cancel"), button],
        };
    });
}

/** Run an async action with a busy button and error toast. */
export async function busy(button, action) {
    const label = button.textContent;
    button.disabled = true;
    try {
        return await action();
    } catch (error) {
        toast(error.message, "error");
        return undefined;
    } finally {
        button.disabled = false;
        button.textContent = label;
    }
}

export function errorBox(error) {
    return h("div.alert.error", error.message || String(error));
}

export function formValues(form) {
    const data = {};
    for (const el of form.querySelectorAll("[name]")) {
        if (el.type === "checkbox") data[el.name] = el.checked;
        else if (el.type === "number") data[el.name] = el.value === "" ? null : Number(el.value);
        else data[el.name] = el.value;
    }
    return data;
}

export function field(label, control, hint) {
    return h("label.field", h("span", label, hint ? h("span.hint", ` — ${hint}`) : null), control);
}

/** Local-datetime helpers for <input type=datetime-local>. */
export function toLocalInput(date) {
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}
