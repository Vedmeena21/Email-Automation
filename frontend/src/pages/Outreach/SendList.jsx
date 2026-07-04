import { useCallback, useEffect, useState } from "react";
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

// Reused for both the Scheduled Queue (status=approved) and Sent Log (status=sent).
export default function SendList({
  title,
  status,
  refreshKey,
  timeField = "scheduled_at",
  onChange,
  onEdited,
}) {
  const toast = useToast();
  const [sends, setSends] = useState(null);
  const [editing, setEditing] = useState(null); // send id being edited
  const [draft, setDraft] = useState({ subject: "", body: "", scheduled_at: "" });
  const [busy, setBusy] = useState(false);
  const editable = status === "approved";

  const load = useCallback(async () => {
    try {
      setSends(await api.listSends(status));
    } catch {
      setSends([]);
    }
  }, [status]);
  useEffect(() => {
    load();
  }, [refreshKey, load]);

  // Editing only opens local fields here — nothing changes on the backend until
  // Save, so the row doesn't disappear out from under the form while it's open.
  function startEdit(s) {
    setEditing(s.id);
    setDraft({
      subject: s.subject,
      body: s.body,
      scheduled_at: toDatetimeLocal(s.scheduled_at),
    });
  }

  async function saveEdit(id) {
    setBusy(true);
    try {
      // Approved sends can't be edited directly (human-in-the-loop safety), so this
      // un-approves it and applies the edit as one atomic user action, then hands
      // off to Approvals — where the now-pending draft actually lives — instead of
      // leaving the user staring at a Scheduled list the item just vanished from.
      await api.unapproveSend(id);
      await api.editSend(id, {
        subject: draft.subject,
        body: draft.body,
        scheduled_at: fromDatetimeLocal(draft.scheduled_at),
      });
      toast("Draft updated — moved to Approvals for re-approval", "success");
      setEditing(null);
      await load();
      onChange?.();
      onEdited?.();
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function remove(s) {
    try {
      // closeThread cancels any unsent send on the thread AND marks the thread
      // dead in one step — cancelling the send alone would leave the thread
      // "open," blocking re-adding the same contact later.
      await api.closeThread(s.thread_id);
      toast("Cancelled ✓", "success");
      await load();
      onChange?.();
    } catch (e) {
      toast(e.message, "error");
    }
  }

  if (sends === null) {
    return (
      <Card title={title}>
        <div className="space-y-2" aria-busy="true" aria-label={`Loading ${title}`}>
          <Skeleton className="h-11 w-full rounded-lg" />
          <Skeleton className="h-11 w-full rounded-lg" />
          <Skeleton className="h-11 w-3/4 rounded-lg" />
        </div>
      </Card>
    );
  }

  return (
    <Card title={`${title} (${sends.length})`}>
      {sends.length === 0 && <Empty>{emptyText}</Empty>}
      <div className="space-y-2">
        {sends.map((s) =>
          editing === s.id ? (
            <div key={s.id} className="rounded-lg border border-brand-line bg-brand-panel2 p-4 space-y-2">
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
                Saving moves this back to Approvals for re-approval before it can send.
              </p>
              <div className="flex gap-2">
                <Button onClick={() => saveEdit(s.id)} disabled={busy}>
                  {busy ? "Saving…" : "Save"}
                </Button>
                <Button variant="ghost" onClick={() => setEditing(null)} disabled={busy}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : (
            <div
              key={s.id}
              className="flex items-center justify-between rounded-lg border border-brand-line bg-brand-panel2 hover:bg-brand-blueSoft transition px-4 py-2.5"
            >
              <div className="min-w-0">
                <div className="truncate font-medium text-brand-ink">{s.subject}</div>
                <div className="text-xs text-brand-muted">
                  {s.type} · {fmt(s[timeField])}
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <Badge status={s.status} />
                {editable && (
                  <>
                    <Button variant="ghost" onClick={() => startEdit(s)}>Edit</Button>
                    <Button variant="danger" onClick={() => remove(s)}>Delete</Button>
                  </>
                )}
              </div>
            </div>
          )
        )}
      </div>
    </Card>
  );
}
