// User administration (administrators only).

import { api, busy, clear, confirmDialog, errorBox, field, fmtDateTime, h, icon, modal, toast } from "../core.js";

export async function render(ctx) {
    ctx.setHeader("Users", "Who can access this ParkSight installation", [
        h("button.btn.primary", { type: "button", onclick: () => userDialog().then((u) => u && load()) },
          icon("plus"), "Add user")]);
    const card = h("div.card");
    clear(ctx.content, h("div.alert.info",
        "Administrators manage cameras, zones, users and settings. Viewers see the dashboard, analytics and reports."), card);

    async function load() {
        try {
            const users = await api("/api/users");
            clear(card, h("div.table-wrap", h("table.table",
                h("thead", h("tr", ["User", "Role", "Status", "Last sign-in", ""].map((t) => h("th", t)))),
                h("tbody", users.map((user) => {
                    const self = user.id === ctx.user.id;
                    return h("tr",
                        h("td", h("b", user.username), self ? h("span.muted", " (you)") : null,
                          h("div.sub", `Created ${fmtDateTime(user.created_at)}`)),
                        h("td", h("span.badge.plain", { class: user.role }, user.role === "admin" ? "Administrator" : "Viewer")),
                        h("td", h("span.badge", { class: user.active ? "online" : "disabled" }, user.active ? "Active" : "Deactivated")),
                        h("td.nowrap", fmtDateTime(user.last_login_at)),
                        h("td.actions",
                            h("button.btn.sm", { type: "button", onclick: (e) => busy(e.currentTarget, async () => {
                                await api(`/api/users/${user.id}`, { method: "PATCH",
                                    body: { role: user.role === "admin" ? "viewer" : "admin" } });
                                toast(`${user.username} is now ${user.role === "admin" ? "a viewer" : "an administrator"}.`);
                                load();
                            }) }, user.role === "admin" ? "Make viewer" : "Make admin"),
                            h("button.btn.sm", { type: "button", onclick: (e) => busy(e.currentTarget, async () => {
                                await api(`/api/users/${user.id}`, { method: "PATCH", body: { active: !user.active } });
                                toast(`${user.username} ${user.active ? "deactivated" : "reactivated"}.`);
                                load();
                            }) }, user.active ? "Deactivate" : "Reactivate"),
                            h("button.btn.sm", { type: "button", onclick: () => resetDialog(user) }, "Reset password"),
                            self ? null : h("button.btn.sm.danger", { type: "button", onclick: async () => {
                                const ok = await confirmDialog({ title: "Delete user",
                                    message: `Delete the account "${user.username}"?`, confirmLabel: "Delete", danger: true });
                                if (!ok) return;
                                try {
                                    await api(`/api/users/${user.id}`, { method: "DELETE" });
                                    toast("User deleted.");
                                    load();
                                } catch (error) { toast(error.message, "error"); }
                            } }, "Delete")));
                })))));
        } catch (error) {
            clear(card, h("div.card-body", errorBox(error)));
        }
    }
    await load();
}

function userDialog() {
    return modal((close) => {
        const result = h("div");
        const username = h("input.input", { autocomplete: "off", maxlength: 64 });
        const password = h("input.input", { type: "password", autocomplete: "new-password" });
        const role = h("select.input", h("option", { value: "viewer" }, "Viewer — dashboards and reports"),
                       h("option", { value: "admin" }, "Administrator — full access"));
        const save = h("button.btn.primary", { type: "button", onclick: () => busy(save, async () => {
            clear(result);
            try {
                const user = await api("/api/users", { method: "POST", body: {
                    username: username.value.trim(), password: password.value, role: role.value } });
                toast(`User ${user.username} created.`);
                close(user);
            } catch (error) { clear(result, errorBox(error)); }
        }) }, "Create user");
        return { title: "Add user",
                 body: [field("Username", username, "letters, digits, _ . @ -"),
                        field("Initial password", password, "at least 10 characters; share it securely"),
                        field("Role", role), result],
                 actions: [h("button.btn", { type: "button", onclick: () => close() }, "Cancel"), save] };
    });
}

function resetDialog(user) {
    return modal((close) => {
        const result = h("div");
        const password = h("input.input", { type: "password", autocomplete: "new-password" });
        const save = h("button.btn.primary", { type: "button", onclick: () => busy(save, async () => {
            clear(result);
            try {
                await api(`/api/users/${user.id}`, { method: "PATCH", body: { password: password.value } });
                toast(`Password for ${user.username} reset. Their sessions were signed out.`);
                close(true);
            } catch (error) { clear(result, errorBox(error)); }
        }) }, "Reset password");
        return { title: `Reset password · ${user.username}`,
                 body: [field("New password", password, "at least 10 characters"), result],
                 actions: [h("button.btn", { type: "button", onclick: () => close() }, "Cancel"), save] };
    });
}
