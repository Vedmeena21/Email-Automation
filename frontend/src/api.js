// Thin REST client for the FastAPI backend.
const BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";
// Every app router lives under /api/v1 (see backend/app/main.py). /health does not
// and is never called from here — it's an infra probe, not app data.
const API_BASE = BASE + "/api/v1";

const API_TOKEN = import.meta.env.VITE_API_TOKEN;

async function req(path, options = {}) {
  const res = await fetch(API_BASE + path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(API_TOKEN ? { "X-API-Token": API_TOKEN } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

export const api = {
  // stats & metrics
  stats: () => req("/stats"),
  metrics: () => req("/metrics"),

  // app settings (timezone, send windows, working days)
  getSettings: () => req("/settings"),
  updateSettings: (s) => req("/settings", { method: "PUT", body: JSON.stringify(s) }),
  listTimezones: () => req("/settings/timezones"),
  setupStatus: () => req("/settings/setup"),
  // Download the CSV via fetch + blob so the export token travels in a HEADER,
  // never in a URL (URLs end up in server logs and browser history).
  downloadExportCsv: async () => {
    const token = import.meta.env.VITE_EXPORT_TOKEN;
    const res = await fetch(API_BASE + "/export/outreach.csv", {
      headers: token ? { "X-Export-Token": token } : {},
    });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail || detail;
      } catch {
        /* non-JSON error body */
      }
      throw new Error(detail);
    }
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "outreach.csv";
    a.click();
    URL.revokeObjectURL(url);
  },

  // suppression / opt-out list
  listSuppression: () => req("/suppression"),
  addSuppression: (email, note) =>
    req("/suppression", { method: "POST", body: JSON.stringify({ email, note }) }),
  removeSuppression: (email) =>
    req(`/suppression/${encodeURIComponent(email)}`, { method: "DELETE" }),

  // GDPR-style erasure: permanently deletes the contact + all threads/sends/
  // replies derived from them, and suppresses the address (distinct from
  // suppression alone, which keeps history).
  eraseContact: (email) =>
    req(`/privacy/contacts/${encodeURIComponent(email)}`, { method: "DELETE" }),

  // templates
  listTemplates: () => req("/templates"),
  createTemplate: (t) => req("/templates", { method: "POST", body: JSON.stringify(t) }),
  updateTemplate: (id, t) =>
    req(`/templates/${id}`, { method: "PUT", body: JSON.stringify(t) }),

  // contacts / sends
  addContact: (c) => req("/contacts", { method: "POST", body: JSON.stringify(c) }),
  listSends: (status) => req("/sends" + (status ? `?status=${status}` : "")),
  editSend: (id, patch) =>
    req(`/sends/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  approveSend: (id) => req(`/sends/${id}/approve`, { method: "POST" }),
  unapproveSend: (id) => req(`/sends/${id}/unapprove`, { method: "POST" }),
  cancelSend: (id) => req(`/sends/${id}/cancel`, { method: "POST" }),
  closeThread: (id) => req(`/threads/${id}/close`, { method: "POST" }),

  // threads / replies
  listThreads: (status, search) => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (search) params.set("search", search);
    const qs = params.toString();
    return req("/threads" + (qs ? `?${qs}` : ""));
  },
  listReplies: (threadId) =>
    req("/replies" + (threadId ? `?thread_id=${threadId}` : "")),
  labelThread: (threadId, payload) =>
    req(`/threads/${threadId}/label`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  pollReplies: () => req("/replies/poll", { method: "POST" }),
};
