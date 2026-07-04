import { useEffect, useState } from "react";
import { api } from "../../api";
import { useToast } from "../../components/Toast";
import {
  Badge,
  Button,
  Card,
  Empty,
  Input,
  Skeleton,
  fmt,
  fromDatetimeLocal,
  toDatetimeLocal,
} from "../../components/ui";

export default function Approvals({ refreshKey, onChange }) {
  const toast = useToast();
  const [sends, setSends] = useState(null);
  const [open, setOpen] = useState(null);
  const [editing, setEditing] = useState(null); // send id being edited
  const [draft, setDraft] = useState({ subject: "", body: "", scheduled_at: "" });

  async function load() {
    try {
      setSends(await api.listSends("pending_approval"));
    } catch {
      setSends([]);
    }
  }
  useEffect(() => {
    load();
  }, [refreshKey]);

  async function act(id, fn, verb) {
    try {
      await fn(id);
      toast(`${verb} ✓`, "success");
      await load();
      onChange?.();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  // closeThread cancels any unsent send on the thread AND marks the thread dead in
  // one step — cancelling the send alone would leave the thread "open," blocking
  // re-adding the same contact later ("you already have an open thread").
  async function cancelAndClose(s) {
    try {
      await api.closeThread(s.thread_id);
      toast("Cancelled ✓", "success");
      await load();
      onChange?.();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  function startEdit(s) {
    setEditing(s.id);
    setDraft({
      subject: s.subject,
      body: s.body,
      scheduled_at: toDatetimeLocal(s.scheduled_at),
    });
    setOpen(s.id);
  }

  async function saveEdit(id) {
    try {
      await api.editSend(id, {
        subject: draft.subject,
        body: draft.body,
        scheduled_at: fromDatetimeLocal(draft.scheduled_at),
      });
      toast("Draft updated ✓", "success");
      setEditing(null);
      await load();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  if (sends === null) {
    return (
      <Card title="Pending approvals">
        <div className="space-y-3" aria-busy="true" aria-label="Loading pending approvals">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-24 w-full rounded-xl" />
        </div>
      </Card>
    );
  }

  return (
    <Card title={`Pending approvals (${sends.length})`}>
      {sends.length === 0 && <Empty>Nothing waiting for approval.</Empty>}
      <div className="space-y-3">
        {sends.map((s) => (
          <div key={s.id} className="rounded-xl border border-brand-line bg-brand-panel2 p-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="font-medium text-brand-ink">{s.subject}</span>{" "}
                <Badge status={s.type === "followup" ? "ooo" : s.status} />
              </div>
              <div className="text-xs text-brand-muted">scheduled {fmt(s.scheduled_at)}</div>
            </div>

            {editing === s.id ? (
              <div className="mt-3 space-y-2">
                <Input
                  label="Subject"
                  value={draft.subject}
                  onChange={(e) => setDraft({ ...draft, subject: e.target.value })}
                />
                <label className="block">
                  <span className="block text-sm font-medium text-brand-ink/80 mb-1.5">Body</span>
                  <textarea
                    rows={8}
                    className="w-full rounded-lg border border-brand-line2 bg-white px-3.5 py-2.5 text-sm text-brand-ink outline-none focus:border-brand-blue focus:ring-2 focus:ring-brand-blue/15 transition"
                    value={draft.body}
                    onChange={(e) => setDraft({ ...draft, body: e.target.value })}
                  />
                </label>
                <Input
                  label="Scheduled for"
                  type="datetime-local"
                  value={draft.scheduled_at}
                  onChange={(e) => setDraft({ ...draft, scheduled_at: e.target.value })}
                />
                <p className="text-xs text-brand-muted">
                  Doesn't auto-update from Settings changes — fix it here if it looks stale.
                </p>
                <div className="flex gap-2">
                  <Button onClick={() => saveEdit(s.id)}>Save</Button>
                  <Button variant="ghost" onClick={() => setEditing(null)}>Cancel</Button>
                </div>
              </div>
            ) : (
              <>
                <button
                  className="mt-1 text-xs text-brand-ink underline"
                  onClick={() => setOpen(open === s.id ? null : s.id)}
                >
                  {open === s.id ? "Hide" : "Preview"} body
                </button>
                {open === s.id && (
                  <pre className="mt-2 whitespace-pre-wrap text-sm text-brand-muted font-sans">
                    {s.body}
                  </pre>
                )}
                <div className="mt-3 flex gap-2">
                  <Button variant="success" onClick={() => act(s.id, api.approveSend, "Approved")}>
                    Approve
                  </Button>
                  <Button variant="ghost" onClick={() => startEdit(s)}>Edit</Button>
                  <Button variant="danger" onClick={() => cancelAndClose(s)}>
                    Cancel
                  </Button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>
    </Card>
  );
}
