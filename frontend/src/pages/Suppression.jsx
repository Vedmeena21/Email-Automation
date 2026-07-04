import { useEffect, useState } from "react";
import { api } from "../api";
import { useToast } from "../components/Toast";
import { Button, Card, Empty, Input, Skeleton, fmt } from "../components/ui";

// Human-readable label + color per suppression reason — shown as a badge with
// a tooltip, instead of the bare backend enum string (manual/bounced/negative/complaint).
const REASON = {
  manual: { label: "Manually added", className: "bg-gray-100 text-gray-600", hint: "Added by you from this page." },
  bounced: { label: "Bounced", className: "bg-orange-50 text-orange-700", hint: "A send to this address failed to deliver, so it was blocked automatically." },
  negative: { label: "Marked negative", className: "bg-rose-50 text-rose-700", hint: "You labeled a reply from this address as Negative, so it was blocked automatically." },
  complaint: { label: "Complaint", className: "bg-rose-50 text-rose-700", hint: "This address reported the email as spam/abuse, so it was blocked automatically." },
};

function ReasonBadge({ reason }) {
  const r = REASON[reason] || { label: reason, className: "bg-gray-100 text-gray-600", hint: "" };
  return (
    <span
      title={r.hint}
      className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${r.className}`}
    >
      {r.label}
    </span>
  );
}

export default function Suppression({ refreshKey }) {
  const toast = useToast();
  const [rows, setRows] = useState(null);
  const [showAdd, setShowAdd] = useState(false);
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [eraseEmail, setEraseEmail] = useState("");
  const [erasing, setErasing] = useState(false);

  async function load() {
    try {
      setRows(await api.listSuppression());
    } catch {
      setRows([]);
    }
  }
  useEffect(() => {
    load();
  }, [refreshKey]);

  async function add(e) {
    e.preventDefault();
    try {
      await api.addSuppression(email.trim(), note.trim() || null);
      toast(`${email} will never be emailed`, "success");
      setEmail("");
      setNote("");
      setShowAdd(false);
      await load();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function remove(addr) {
    try {
      await api.removeSuppression(addr);
      toast(`Removed ${addr}`, "info");
      await load();
    } catch (err) {
      toast(err.message, "error");
    }
  }

  async function eraseContact(e) {
    e.preventDefault();
    const addr = eraseEmail.trim();
    if (!addr) return;
    if (
      !window.confirm(
        `Permanently delete ${addr} and every thread, send, and reply on record for them? This cannot be undone.`
      )
    ) {
      return;
    }
    setErasing(true);
    try {
      await api.eraseContact(addr);
      toast(`${addr} and all their data has been erased`, "success");
      setEraseEmail("");
      await load();
    } catch (err) {
      toast(err.message, "error");
    } finally {
      setErasing(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-lg font-bold text-brand-ink">Do Not Contact</h1>
        <p className="mt-1 text-sm text-brand-muted max-w-2xl">
          Every address below is permanently blocked — the app checks this list before
          every send, so nothing ever goes out to them again. Most entries are added
          automatically (a bounced send, or a reply you labeled "Negative"); you can
          also add one manually below.
        </p>
      </div>

      <Card title={rows === null ? "Blocked addresses" : `Blocked addresses (${rows.length})`}>
        {rows === null && (
          <div className="space-y-2" aria-busy="true" aria-label="Loading blocked addresses">
            <Skeleton className="h-14 w-full rounded-xl" />
            <Skeleton className="h-14 w-3/4 rounded-xl" />
          </div>
        )}
        {rows?.length === 0 && <Empty>Nothing blocked yet — this list fills up automatically as you send.</Empty>}
        <div className="space-y-2">
          {(rows || []).map((r) => (
            <div
              key={r.email}
              className="flex items-center justify-between rounded-xl border border-brand-line bg-brand-panel2 px-4 py-3"
            >
              <div className="min-w-0">
                <div className="font-medium text-brand-ink truncate">{r.email}</div>
                <div className="mt-1 flex items-center gap-2 text-xs text-brand-muted">
                  <ReasonBadge reason={r.reason} />
                  {r.note ? <span>{r.note}</span> : null}
                  <span>· {fmt(r.created_at)}</span>
                </div>
              </div>
              <Button variant="ghost" onClick={() => remove(r.email)}>
                Unblock
              </Button>
            </div>
          ))}
        </div>

        <div className="mt-4 pt-4 border-t border-brand-line">
          {!showAdd ? (
            <Button variant="ghost" onClick={() => setShowAdd(true)}>
              + Block an address manually
            </Button>
          ) : (
            <form onSubmit={add} className="flex flex-wrap items-end gap-3">
              <div className="w-64">
                <Input
                  label="Email"
                  type="email"
                  required
                  autoFocus
                  placeholder="contact@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="flex-1 min-w-[200px]">
                <Input
                  label="Note (optional)"
                  placeholder="e.g. asked to stop"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </div>
              <Button type="submit">Block</Button>
              <Button type="button" variant="ghost" onClick={() => setShowAdd(false)}>
                Cancel
              </Button>
            </form>
          )}
        </div>
      </Card>

      <div className="rounded-2xl border-2 border-rose-200 bg-rose-50/40 p-5">
        <div className="text-sm font-extrabold text-rose-700">Danger zone</div>
        <p className="mt-1 text-xs text-brand-muted max-w-2xl">
          Erasing a contact permanently deletes every thread, send, and reply on
          record for them (not just future emails) and adds them here so they can't
          be re-imported by accident. This cannot be undone — use "Block an address"
          above if you just want to stop emailing someone without losing the history.
        </p>
        <form onSubmit={eraseContact} className="mt-3 flex flex-wrap items-end gap-3">
          <div className="w-64">
            <Input
              label="Email"
              type="email"
              required
              placeholder="contact@company.com"
              value={eraseEmail}
              onChange={(e) => setEraseEmail(e.target.value)}
            />
          </div>
          <Button type="submit" variant="danger" disabled={erasing}>
            {erasing ? "Erasing…" : "Erase permanently"}
          </Button>
        </form>
      </div>
    </div>
  );
}
