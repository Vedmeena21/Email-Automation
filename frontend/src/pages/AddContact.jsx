import { useState } from "react";
import { api } from "../api";
import { useToast } from "../components/Toast";
import { Button, Card, Input, Select, fmt } from "../components/ui";

// Client-side port of the backend's render() so the preview IS the email that
// sends: blank values drop their whole body line, blank subject vars vanish,
// unknown placeholders stay intact. Keep in sync with services/outreach.render.
const VAR_RE = /\{([a-zA-Z0-9_]+)\}/g;
function renderExact(subject, body, values) {
  const filled = {};
  const blank = new Set();
  for (const [k, v] of Object.entries(values)) {
    if (v != null && String(v).trim()) filled[k] = v;
    else blank.add(k);
  }
  const sub = (s) => s.replace(VAR_RE, (m, k) => (k in filled ? filled[k] : m));
  const renderedSubject = (subject || "").replace(VAR_RE, (m, k) =>
    k in filled ? filled[k] : blank.has(k) ? "" : m
  );
  const keptBody = (body || "")
    .split("\n")
    .filter((line) => ![...blank].some((b) => line.includes("{" + b + "}")))
    .join("\n");
  return { subject: renderedSubject, body: sub(keptBody) };
}

// Turn a variable name into a friendly label: recruiter_name -> "Recruiter name".
function label(v) {
  return v.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
}

export default function AddContact({ templates, onAdded, settings, goTo }) {
  const toast = useToast();
  const [templateId, setTemplateId] = useState("");
  const [email, setEmail] = useState("");
  const [vals, setVals] = useState({}); // variable name -> value (incl. recruiter_name, company)
  const [busy, setBusy] = useState(false);
  const [queued, setQueued] = useState(null);
  const [cooldownBlock, setCooldownBlock] = useState(null); // error msg when a re-contact is blocked

  const tmpl = templates.find((t) => String(t.id) === String(templateId));
  // company is core to the recruiter record (used for dedup), so always collect it
  // even if the template text doesn't reference {company}.
  const templateVars = tmpl?.variables ?? [];
  const fields = tmpl
    ? ["company", ...templateVars.filter((v) => v !== "company")]
    : [];

  const setVar = (k) => (e) => {
    setVals({ ...vals, [k]: e.target.value });
    setQueued(null);
  };

  // the contact-name vars fall back to a generic greeting; link/id vars aren't
  // always relevant, so all of these are optional.
  const optional = new Set(["name", "recruiter_name", "job_id", "job_link"]);
  const ready =
    !!tmpl && !!email && fields.every((v) => optional.has(v) || (vals[v] || "").trim());

  // mirror add_contact(): name falls back to "there", signature comes from Settings.
  // Plain computation — it's cheap regex work, no memoization needed.
  const previewName = (vals.name ?? vals.recruiter_name ?? "").trim() || "there";
  const preview = tmpl
    ? renderExact(tmpl.subject, tmpl.body, {
        ...vals,
        name: previewName,
        recruiter_name: previewName,
        company: vals.company || "",
        signature: settings?.signature || "",
      })
    : null;

  async function confirmQueue(force = false) {
    setBusy(true);
    setCooldownBlock(null);
    try {
      // name/company are first-class ({name} or the {recruiter_name} alias); rest go in variables
      const { name = "", recruiter_name = "", company = "", ...extra } = vals;
      const send = await api.addContact({
        name: name || recruiter_name,
        company,
        email,
        template_id: Number(templateId),
        variables: extra,
        force,
      });
      setQueued(send);
      setVals({});
      setEmail("");
      toast("Draft queued — approve it under Outreach", "success");
      onAdded?.();
      goTo?.("Overview");
    } catch (e) {
      // the cooldown guard is overridable — surface a "send anyway" choice
      if (/force to override/i.test(e.message)) setCooldownBlock(e.message);
      else toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title="1 · Contact details">
        <div className="grid gap-3">
          <Select
            label="Template"
            value={templateId}
            onChange={(e) => {
              setTemplateId(e.target.value);
              setVals({});
              setQueued(null);
            }}
          >
            <option value="">Select a template…</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </Select>

          <Input
            label="Email"
            type="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setQueued(null);
            }}
            placeholder="mohit@company.com"
          />

          {/* company + one input per variable the chosen template uses */}
          {fields.map((v) => (
            <Input
              key={v}
              label={label(v)}
              value={vals[v] || ""}
              onChange={setVar(v)}
              placeholder={
                v === "name" || v === "recruiter_name"
                  ? "e.g. Mohit (blank → generic greeting)"
                  : ""
              }
            />
          ))}

          {!tmpl && (
            <p className="text-xs text-brand-muted">
              Pick a template — the fields it needs will appear here.
            </p>
          )}
          {tmpl && (
            <p className="text-xs text-brand-muted">
              The email updates live on the right. Nothing is sent or saved until you confirm.
            </p>
          )}
        </div>
      </Card>

      <Card title="2 · Final email preview">
        {!preview ? (
          <div className="text-sm text-brand-muted py-10 text-center">
            Fill in the details and pick a template to preview the exact email.
          </div>
        ) : (
          <div>
            <div className="rounded-xl border border-brand-line bg-brand-panel2 p-4">
              <div className="text-xs text-brand-muted">To</div>
              <div className="text-sm text-brand-ink mb-3">{email || "—"}</div>
              <div className="text-xs text-brand-muted">Subject</div>
              <div className="font-medium text-brand-ink mb-3">
                {withPlaceholders(preview.subject)}
              </div>
              <div className="text-xs text-brand-muted">Body</div>
              <pre className="mt-1 whitespace-pre-wrap text-sm text-brand-ink font-sans">
                {withPlaceholders(preview.body)}
              </pre>
              {tmpl?.attach_resume && (
                <div className="mt-3 text-xs text-brand-muted">
                  📎 Your configured resume will be attached.
                </div>
              )}
              {tmpl && !settings?.signature?.trim() && tmpl.body.includes("{signature}") && (
                <div className="mt-2 text-xs text-amber-700">
                  No signature set — its line is dropped from the email. Add one in Settings.
                </div>
              )}
            </div>

            <div className="mt-4 flex items-center gap-3">
              <Button onClick={() => confirmQueue()} disabled={!ready || busy}>
                {busy ? "Queuing…" : "Looks good — queue it"}
              </Button>
              {!ready && (
                <span className="text-xs text-brand-muted">
                  Fill email and all template fields to enable.
                </span>
              )}
            </div>

            {cooldownBlock && (
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm">
                <div className="text-amber-800">{cooldownBlock}</div>
                <div className="mt-2 flex gap-2">
                  <Button onClick={() => confirmQueue(true)} disabled={busy}>
                    Send anyway
                  </Button>
                  <Button variant="ghost" onClick={() => setCooldownBlock(null)}>
                    Never mind
                  </Button>
                </div>
              </div>
            )}

            {queued && (
              <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-sm">
                <span className="text-emerald-700 font-medium">Queued ✓</span>{" "}
                <span className="text-brand-muted">
                  Scheduled {fmt(queued.scheduled_at)} · awaiting your approval under{" "}
                  <b>Outreach → Approvals</b>.
                </span>
              </div>
            )}
          </div>
        )}
      </Card>
    </div>
  );
}
