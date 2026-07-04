import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useToast } from "../components/Toast";
import { Button, Card, Input, Select } from "../components/ui";

const DAYS = [
  { n: 1, label: "Mon" },
  { n: 2, label: "Tue" },
  { n: 3, label: "Wed" },
  { n: 4, label: "Thu" },
  { n: 5, label: "Fri" },
  { n: 6, label: "Sat" },
  { n: 7, label: "Sun" },
];

// Computes a zone's current UTC offset as "GMT+5:30" by diffing a formatted
// local wall-clock reading against UTC — never a hardcoded label, so it can't
// go stale across a DST transition.
function gmtOffset(zone) {
  const now = new Date();
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
    .formatToParts(now)
    .reduce((a, p) => ((a[p.type] = p.value), a), {});
  const asUTC = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute);
  const offsetMin = Math.round(
    (asUTC -
      Date.UTC(
        now.getUTCFullYear(),
        now.getUTCMonth(),
        now.getUTCDate(),
        now.getUTCHours(),
        now.getUTCMinutes()
      )) /
      60000
  );
  const sign = offsetMin >= 0 ? "+" : "-";
  const abs = Math.abs(offsetMin);
  const mins = abs % 60;
  return `GMT${sign}${Math.floor(abs / 60)}${mins ? ":" + String(mins).padStart(2, "0") : ""}`;
}

function zoneCityLabel(zone) {
  const parts = zone.split("/");
  return parts[parts.length - 1].replace(/_/g, " ");
}

// e.g. "India Standard Time" — real, DST-aware, no hand-maintained name table.
function zoneLongName(zone) {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    timeZoneName: "long",
  }).formatToParts(new Date());
  return parts.find((p) => p.type === "timeZoneName")?.value || zone;
}

function zoneRowLabel(zone) {
  return `${zoneLongName(zone)} - ${zoneCityLabel(zone)}`;
}

function zoneTriggerLabel(zone) {
  return `(${gmtOffset(zone)}) ${zoneRowLabel(zone)}`;
}

const _countryNames = new Intl.DisplayNames(["en"], { type: "region" });
function countryName(code) {
  if (!code) return null;
  try {
    return _countryNames.of(code);
  } catch {
    return null;
  }
}

// Google Calendar-style timezone picker: closed by default, showing the
// current selection as "(GMT+5:30) India Standard Time - Kolkata". Click
// opens a searchable dropdown; each row is two lines — bold "City, Country"
// on top, muted "Zone name - City (GMT offset)" below, matching Calendar's
// actual "Event time zone" dropdown. Click a row to select and close;
// dismiss via outside click or Escape.
function TimezonePicker({ zones, value, onChange }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const wrapRef = useRef(null);
  const searchRef = useRef(null);

  const byZone = useMemo(() => {
    const m = new Map();
    for (const z of zones) m.set(z.zone, z.country_code);
    return m;
  }, [zones]);

  // Ranks a match so "India" surfaces Kolkata (country match) before
  // Indianapolis (an incidental city-name substring hit) — plain substring
  // search with no ranking put unrelated cities ahead of the actual country.
  function matchRank(needle, city, country) {
    const c = city.toLowerCase();
    const co = (country || "").toLowerCase();
    if (co === needle || c === needle) return 0; // exact match
    if (co.startsWith(needle) || c.startsWith(needle)) return 1; // prefix match
    if (co.includes(needle)) return 2; // country contains it
    if (c.includes(needle)) return 3; // city contains it
    return 4; // only matched zone id / long name
  }

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return zones.slice(0, 200);

    const scored = [];
    for (const z of zones) {
      const { zone, country_code } = z;
      const city = zoneCityLabel(zone);
      const country = countryName(country_code);
      const haystack = `${zone} ${zone.replace(/_/g, " ")} ${zoneRowLabel(zone)} ${
        country || ""
      }`.toLowerCase();
      if (!haystack.includes(needle)) continue;
      scored.push({ z, rank: matchRank(needle, city, country) });
    }
    scored.sort((a, b) => a.rank - b.rank);
    return scored.slice(0, 200).map((s) => s.z);
  }, [q, zones]);

  useEffect(() => {
    if (!open) return;
    setQ("");
    const t = setTimeout(() => searchRef.current?.focus(), 0);
    const onClickAway = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onClickAway);
    document.addEventListener("keydown", onKey);
    return () => {
      clearTimeout(t);
      document.removeEventListener("mousedown", onClickAway);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div>
      <span className="block text-sm font-semibold text-brand-ink mb-1.5">Timezone</span>
      <div ref={wrapRef} className="relative max-w-sm">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="w-full flex items-center justify-between gap-2 rounded-lg border border-brand-line2 bg-white px-3.5 py-2.5 text-sm text-brand-ink outline-none focus:border-brand-blue focus:ring-4 focus:ring-brand-blue/10 transition"
        >
          <span>{zoneTriggerLabel(value)}</span>
          <span className="text-brand-muted text-xs">▾</span>
        </button>

        {open && (
          <div className="absolute top-[calc(100%+6px)] left-0 right-0 z-10 rounded-lg border border-brand-line2 bg-white shadow-lg overflow-hidden">
            <div className="p-2">
              <input
                ref={searchRef}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                placeholder="Search e.g. New York, London, Kolkata…"
                className="w-full rounded-lg border border-brand-line2 bg-white px-3 py-2 text-sm outline-none focus:border-brand-blue"
              />
            </div>
            <div className="max-h-64 overflow-y-auto border-t border-brand-line">
              {filtered.length === 0 && (
                <div className="px-3.5 py-3 text-sm text-brand-muted text-center">
                  No matching timezone
                </div>
              )}
              {filtered.map(({ zone: z, country_code }) => {
                const selected = z === value;
                const country = countryName(country_code);
                return (
                  <button
                    key={z}
                    type="button"
                    onClick={() => {
                      onChange(z);
                      setOpen(false);
                    }}
                    className={`w-full text-left px-3.5 py-2 transition-colors ${
                      selected ? "bg-brand-blueSoft" : "hover:bg-brand-panel2"
                    }`}
                  >
                    <div
                      className={`text-sm font-semibold ${
                        selected ? "text-brand-blue" : "text-brand-ink"
                      }`}
                    >
                      {zoneCityLabel(z)}
                      {country ? `, ${country}` : ""}
                    </div>
                    <div className="text-xs text-brand-muted mt-0.5">
                      {zoneRowLabel(z)} ({gmtOffset(z)})
                    </div>
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Window({ title, start, end, onStart, onEnd }) {
  return (
    <div className="rounded-xl border border-brand-line bg-brand-panel2 p-4">
      <div className="text-sm font-medium text-brand-ink mb-2">{title}</div>
      <div className="flex items-center gap-2">
        <input
          type="time"
          value={start}
          onChange={(e) => onStart(e.target.value)}
          className="rounded-lg border border-brand-line2 bg-white px-3 py-2 text-sm"
        />
        <span className="text-brand-muted">to</span>
        <input
          type="time"
          value={end}
          onChange={(e) => onEnd(e.target.value)}
          className="rounded-lg border border-brand-line2 bg-white px-3 py-2 text-sm"
        />
      </div>
    </div>
  );
}

export default function Settings({ goTo }) {
  const toast = useToast();
  const [zones, setZones] = useState([]);
  const [s, setS] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.listTimezones().then(setZones).catch(() => setZones([]));
    api
      .getSettings()
      .then((row) => setS({ ...row, working_days: row.working_days || [1, 2, 3, 4, 5] }))
      .catch((e) => toast(e.message, "error"));
  }, [toast]);

  if (!s) return <Card title="Settings">Loading… (run migration 003 if this stays empty)</Card>;

  const set = (k, v) => setS({ ...s, [k]: v });
  const toggleDay = (n) =>
    set(
      "working_days",
      s.working_days.includes(n)
        ? s.working_days.filter((d) => d !== n)
        : [...s.working_days, n].sort()
    );

  async function save() {
    setBusy(true);
    try {
      const saved = await api.updateSettings({
        timezone: s.timezone,
        window_a_start: s.window_a_start,
        window_a_end: s.window_a_end,
        window_b_start: s.window_b_start,
        window_b_end: s.window_b_end,
        working_days: s.working_days,
        followup_after_working_days: Number(s.followup_after_working_days),
        holiday_mode: s.holiday_mode,
        holiday_country: s.holiday_country || "IN",
        sender_name: s.sender_name || "",
        signature: s.signature || "",
      });
      setS({ ...saved });
      toast("Settings saved ✓", "success");
      goTo?.("Overview");
    } catch (e) {
      toast(e.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid gap-5 lg:grid-cols-2">
      <Card title="Timezone & working days">
        <TimezonePicker zones={zones} value={s.timezone} onChange={(v) => set("timezone", v)} />

        <div className="mt-4">
          <span className="block text-sm font-medium text-brand-ink/80 mb-1.5">Working days</span>
          <div className="flex flex-wrap gap-1.5">
            {DAYS.map((d) => {
              const on = s.working_days.includes(d.n);
              return (
                <button
                  key={d.n}
                  onClick={() => toggleDay(d.n)}
                  className={`px-3 py-1.5 rounded-lg text-sm font-medium border transition ${
                    on
                      ? "bg-brand-blue text-white border-brand-blue"
                      : "bg-white text-brand-muted border-brand-line2 hover:bg-brand-panel2"
                  }`}
                >
                  {d.label}
                </button>
              );
            })}
          </div>
          <p className="mt-1 text-xs text-brand-muted">Emails only send on selected days.</p>
        </div>
      </Card>

      <Card title="Send windows">
        <p className="text-sm text-brand-muted mb-3">
          Each email sends at a random time inside one of these two windows (human-looking).
        </p>
        <div className="grid gap-3">
          <Window
            title="Morning window"
            start={s.window_a_start}
            end={s.window_a_end}
            onStart={(v) => set("window_a_start", v)}
            onEnd={(v) => set("window_a_end", v)}
          />
          <Window
            title="Afternoon window"
            start={s.window_b_start}
            end={s.window_b_end}
            onStart={(v) => set("window_b_start", v)}
            onEnd={(v) => set("window_b_end", v)}
          />
        </div>
      </Card>

      <Card title="Follow-ups & holidays">
        <div className="grid gap-3">
          <Input
            label="Follow up after (working days with no reply)"
            type="number"
            min={1}
            max={30}
            value={s.followup_after_working_days}
            onChange={(e) => set("followup_after_working_days", e.target.value)}
          />
          <Select
            label="Skip public holidays"
            value={s.holiday_mode}
            onChange={(e) => set("holiday_mode", e.target.value)}
          >
            <option value="none">No — send on any working day</option>
            <option value="country">Yes — skip my country's public holidays</option>
          </Select>
          {s.holiday_mode === "country" && (
            <Input
              label="Country code (ISO, e.g. IN, US, GB)"
              value={s.holiday_country}
              onChange={(e) => set("holiday_country", e.target.value.toUpperCase())}
            />
          )}
        </div>
      </Card>

      <Card title="Your identity">
        <div className="grid gap-3">
          <Input
            label="Your name"
            placeholder="e.g. Jordan Lee"
            value={s.sender_name || ""}
            onChange={(e) => set("sender_name", e.target.value)}
          />
          <label className="block">
            <span className="block text-sm font-medium text-brand-ink/80 mb-1.5">
              Email signature (use {"{signature}"} in a template to insert this)
            </span>
            <textarea
              rows={4}
              className="w-full rounded-lg border border-brand-line2 bg-white px-3.5 py-2.5 text-sm text-brand-ink outline-none focus:border-brand-blue focus:ring-2 focus:ring-brand-blue/15 transition"
              placeholder={"Best regards,\nJordan Lee\n+1 555 0100"}
              value={s.signature || ""}
              onChange={(e) => set("signature", e.target.value)}
            />
          </label>
        </div>
      </Card>

      <Card title="">
        <Button onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save settings"}
        </Button>
        <p className="mt-2 text-xs text-brand-muted">
          Changes apply to newly scheduled emails immediately.
        </p>
      </Card>
    </div>
  );
}
