// ParkSight application shell: authentication, navigation and routing.

import { api, busy, clear, errorBox, field, h, icon, modal, setUnauthorizedHandler, toast } from "./core.js";
import * as dashboard from "./views/dashboard.js";
import * as analytics from "./views/analytics.js";
import * as reports from "./views/reports.js";
import * as cameras from "./views/cameras.js";
import * as zones from "./views/zones.js";
import * as editor from "./views/editor.js";
import * as users from "./views/users.js";
import * as settings from "./views/settings.js";

const root = document.getElementById("root");

const ROUTES = [
    { path: "dashboard", label: "Overview", icon: "dashboard", view: dashboard, section: "Monitoring" },
    { path: "analytics", label: "Analytics", icon: "chart", view: analytics },
    { path: "reports", label: "Reports", icon: "report", view: reports },
    { path: "cameras", label: "Cameras", icon: "camera", view: cameras, section: "Configuration" },
    { path: "zones", label: "Zones & spaces", icon: "layout", view: zones },
    { path: "users", label: "Users", icon: "users", view: users, admin: true, section: "Administration" },
    { path: "settings", label: "Settings", icon: "settings", view: settings, admin: true },
];

const state = { user: null, siteName: "ParkSight", cleanup: [] };

setUnauthorizedHandler(() => {
    if (state.user) {
        state.user = null;
        toast("Your session has ended. Please sign in again.", "error");
        start();
    }
});

// --- Auth screens -------------------------------------------------------------

function authCard(title, intro, form) {
    return h("div.auth-screen",
        h("div.auth-card",
            h("div.brand", h("div.brand-mark", "P"), h("div", h("div.brand-name", "ParkSight"),
                h("div.muted.small", "Parking occupancy monitoring"))),
            h("h1", title), intro ? h("p", intro) : null, form));
}

function loginScreen() {
    const error = h("div");
    const form = h("form", { class: "grid", onsubmit: async (event) => {
        event.preventDefault();
        clear(error);
        const button = form.querySelector("button");
        try {
            button.disabled = true;
            state.user = await api("/api/auth/login", { method: "POST", body: {
                username: form.username.value.trim(), password: form.password.value } });
            start();
        } catch (e) {
            error.append(errorBox(e));
            button.disabled = false;
        }
    } },
        field("Username", h("input.input", { name: "username", autocomplete: "username", required: true })),
        field("Password", h("input.input", { name: "password", type: "password",
                                             autocomplete: "current-password", required: true })),
        error,
        h("button.btn.primary", { type: "submit" }, "Sign in"));
    clear(root, authCard("Sign in", null, form));
    form.username.focus();
}

function setupScreen() {
    const error = h("div");
    const form = h("form", { class: "grid", onsubmit: async (event) => {
        event.preventDefault();
        clear(error);
        if (form.password.value !== form.confirm.value) {
            error.append(errorBox(new Error("Passwords do not match.")));
            return;
        }
        const button = form.querySelector("button");
        try {
            button.disabled = true;
            state.user = await api("/api/auth/setup", { method: "POST", body: {
                setup_token: form.token.value.trim(), username: form.username.value.trim(),
                password: form.password.value } });
            toast("Administrator account created.");
            location.hash = "#/cameras";
            start();
        } catch (e) {
            error.append(errorBox(e));
            button.disabled = false;
        }
    } },
        field("Setup token", h("input.input", { name: "token", required: true, autocomplete: "off" }),
              "printed in the server log"),
        field("Administrator username", h("input.input", { name: "username", required: true,
                                                          autocomplete: "username", value: "admin" })),
        field("Password", h("input.input", { name: "password", type: "password", required: true,
                                             minlength: 10, autocomplete: "new-password" }),
              "at least 10 characters"),
        field("Confirm password", h("input.input", { name: "confirm", type: "password", required: true,
                                                     autocomplete: "new-password" })),
        error,
        h("button.btn.primary", { type: "submit" }, "Create administrator"));
    clear(root, authCard("Welcome to ParkSight",
        "Create the first administrator account. For security, setup requires the one-time token shown in the server log (for Docker: docker compose logs parksight).",
        form));
}

// --- Account dialogs ----------------------------------------------------------

function changePasswordDialog() {
    modal((close) => {
        const form = h("form.grid",
            field("Current password", h("input.input", { name: "current", type: "password", autocomplete: "current-password" })),
            field("New password", h("input.input", { name: "next", type: "password", autocomplete: "new-password" }),
                  "at least 10 characters"),
            field("Confirm new password", h("input.input", { name: "confirm", type: "password", autocomplete: "new-password" })));
        const save = h("button.btn.primary", { type: "button", onclick: () => busy(save, async () => {
            if (form.next.value !== form.confirm.value) throw new Error("New passwords do not match.");
            await api("/api/auth/password", { method: "POST", body: {
                current_password: form.current.value, new_password: form.next.value } });
            toast("Password changed. Other sessions were signed out.");
            close(true);
        }) }, "Change password");
        return { title: "Change password", body: form,
                 actions: [h("button.btn", { type: "button", onclick: () => close() }, "Cancel"), save] };
    });
}

async function signOut() {
    try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ }
    state.user = null;
    shell = null;
    start();
}

// --- Shell and routing ----------------------------------------------------------

let shell;

function buildShell() {
    const nav = h("nav.nav");
    for (const route of ROUTES) {
        if (route.admin && state.user.role !== "admin") continue;
        if (route.section) nav.append(h("div.nav-label", route.section));
        nav.append(h("a", { href: `#/${route.path}`, "data-path": route.path }, icon(route.icon), route.label));
    }
    const title = h("h1");
    const subtitle = h("div.subtitle");
    const actions = h("div.topbar-actions");
    const content = h("div.content");
    const siteLabel = h("div.brand-site", state.siteName);
    clear(root, h("div.app",
        h("aside.sidebar",
            h("div.brand", h("div.brand-mark", "P"), h("div", h("div.brand-name", "ParkSight"), siteLabel)),
            nav,
            h("div.sidebar-foot",
                h("div.who", state.user.username), h("div.role.muted", state.user.role),
                h("div.links",
                    h("button", { type: "button", onclick: changePasswordDialog }, "Password"),
                    h("button", { type: "button", onclick: signOut }, "Sign out")))),
        h("main.main", h("header.topbar", h("div", title, subtitle), actions), content)));
    shell = { nav, title, subtitle, actions, content, siteLabel };
}

function runCleanup() {
    for (const fn of state.cleanup.splice(0)) {
        try { fn(); } catch { /* ignore */ }
    }
}

async function route() {
    if (!state.user || !shell || !document.body.contains(shell.content)) return;
    runCleanup();
    const hash = location.hash.replace(/^#\/?/, "") || "dashboard";
    const parts = hash.split("/");
    let match = ROUTES.find((r) => r.path === parts[0]);
    let view = match?.view;
    let params = {};
    if (parts[0] === "zones" && parts[2] === "layout") {
        view = editor;
        params = { zoneId: Number(parts[1]) };
        match = ROUTES.find((r) => r.path === "zones");
    }
    if (!view || (match.admin && state.user.role !== "admin")) {
        location.hash = "#/dashboard";
        return;
    }
    for (const link of shell.nav.querySelectorAll("a")) {
        link.classList.toggle("active", link.dataset.path === match.path);
    }
    clear(shell.actions);
    shell.subtitle.textContent = "";
    clear(shell.content, h("div.loading", "Loading…"));
    const ctx = {
        user: state.user,
        isAdmin: state.user.role === "admin",
        params,
        content: shell.content,
        setHeader(title, subtitle = "", actions = []) {
            shell.title.textContent = title;
            shell.subtitle.textContent = subtitle;
            clear(shell.actions, actions);
            document.title = `${title} · ParkSight`;
        },
        setSiteName(name) {
            state.siteName = name;
            shell.siteLabel.textContent = name;
        },
        onCleanup(fn) { state.cleanup.push(fn); },
    };
    try {
        await view.render(ctx);
    } catch (error) {
        clear(shell.content, errorBox(error));
    }
}

async function start() {
    runCleanup();
    let authState;
    try {
        authState = await api("/api/auth/state");
    } catch (error) {
        clear(root, authCard("ParkSight is unavailable", null, errorBox(error)));
        return;
    }
    if (authState.setup_required) return setupScreen();
    state.user = authState.user;
    if (!state.user) return loginScreen();
    try {
        state.siteName = (await api("/api/settings")).site_name;
    } catch { /* keep default */ }
    buildShell();
    route();
}

window.addEventListener("hashchange", route);
start();
