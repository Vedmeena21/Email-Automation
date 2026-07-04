// UI primitives — standardized on a Dropbox-style visual language: pill buttons,
// soft-grey pill badges, underlined text-links, bold rounded headings, lots of white.

export function Card({ title, action, children }) {
  return (
    <div className="bg-brand-panel rounded-2xl border border-brand-line overflow-hidden">
      {(title || action) && (
        <div className="flex items-center justify-between px-6 py-5 border-b border-brand-line">
          <h2 className="text-[15px] font-bold text-brand-ink tracking-tight">{title}</h2>
          {action}
        </div>
      )}
      <div className="p-6">{children}</div>
    </div>
  );
}

export function Button({ variant = "primary", className = "", ...props }) {
  const base =
    "px-5 py-2.5 rounded-full text-sm font-semibold transition-colors duration-150 disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-blue";
  const variants = {
    primary: "text-white bg-brand-blue hover:bg-brand-blueDark",
    ghost: "text-brand-ink bg-white border-2 border-brand-ink hover:bg-brand-panel2",
    danger: "text-rose-600 bg-white border-2 border-rose-200 hover:bg-rose-50",
    success: "text-white bg-brand-blue hover:bg-brand-blueDark",
  };
  return <button className={`${base} ${variants[variant]} ${className}`} {...props} />;
}

// Underlined text-action, for secondary CTAs ("Learn more →" style).
export function TextLink({ className = "", children, ...props }) {
  return (
    <a
      className={`inline-flex items-center gap-1.5 text-sm font-semibold text-brand-ink underline underline-offset-4 decoration-2 hover:text-brand-blue transition-colors cursor-pointer ${className}`}
      {...props}
    >
      {children}
    </a>
  );
}

// Soft-grey pill label, used above headlines ("Organise"-style eyebrow tag).
export function Eyebrow({ icon, children }) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-panel2 border border-brand-line px-3.5 py-1.5 text-sm font-medium text-brand-muted">
      {icon}
      {children}
    </span>
  );
}

export function Input({ label, ...props }) {
  return (
    <label className="block">
      {label && (
        <span className="block text-sm font-semibold text-brand-ink mb-1.5">{label}</span>
      )}
      <input
        className="w-full rounded-lg border border-brand-line2 bg-white px-3.5 py-2.5 text-sm text-brand-ink placeholder-brand-muted/60 outline-none focus:border-brand-blue focus:ring-4 focus:ring-brand-blue/10 transition"
        {...props}
      />
    </label>
  );
}

export function Select({ label, children, className = "", ...props }) {
  return (
    <label className="block">
      {label && (
        <span className="block text-sm font-semibold text-brand-ink mb-1.5">{label}</span>
      )}
      <select
        className={`w-full rounded-lg border border-brand-line2 bg-white px-3.5 py-2.5 text-sm text-brand-ink outline-none focus:border-brand-blue focus:ring-4 focus:ring-brand-blue/10 transition ${className}`}
        {...props}
      >
        {children}
      </select>
    </label>
  );
}

const STATUS_STYLES = {
  pending_approval: "bg-amber-50 text-amber-700 border-amber-200",
  approved: "bg-brand-blueSoft text-brand-blue border-brand-blue/20",
  sent: "bg-emerald-50 text-emerald-700 border-emerald-200",
  failed: "bg-rose-50 text-rose-700 border-rose-200",
  cancelled: "bg-gray-100 text-gray-500 border-gray-200",
  active: "bg-brand-blueSoft text-brand-blue border-brand-blue/20",
  replied_unlabeled: "bg-indigo-50 text-indigo-700 border-indigo-200",
  replied_positive: "bg-emerald-50 text-emerald-700 border-emerald-200",
  replied_negative: "bg-rose-50 text-rose-700 border-rose-200",
  ooo: "bg-amber-50 text-amber-700 border-amber-200",
  bounced: "bg-orange-50 text-orange-700 border-orange-200",
  dead: "bg-gray-100 text-gray-500 border-gray-200",
};

export function Badge({ status }) {
  const cls = STATUS_STYLES[status] || "bg-gray-100 text-gray-600 border-gray-200";
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold border ${cls}`}>
      {status}
    </span>
  );
}

export function Empty({ children }) {
  return <p className="text-sm text-brand-muted py-10 text-center">{children}</p>;
}

// A pulsing placeholder block, for content that's still loading. Using a real
// element (not a blank screen) keeps layout stable and signals "this is coming"
// instead of looking broken.
export function Skeleton({ className = "" }) {
  return <div className={`animate-pulse rounded-lg bg-brand-line ${className}`} aria-hidden="true" />;
}

// A Card-shaped skeleton, for pages that show a grid of Cards while loading.
export function SkeletonCard() {
  return (
    <div className="bg-brand-panel rounded-2xl border border-brand-line overflow-hidden">
      <div className="px-6 py-5 border-b border-brand-line">
        <Skeleton className="h-4 w-32" />
      </div>
      <div className="p-6 space-y-2.5">
        <Skeleton className="h-11 w-full rounded-xl" />
        <Skeleton className="h-11 w-full rounded-xl" />
        <Skeleton className="h-11 w-3/4 rounded-xl" />
      </div>
    </div>
  );
}

// Pill-style secondary toggle used inside grouped pages.
export function SubTabs({ tabs, active, onChange, counts = {} }) {
  return (
    <div className="inline-flex gap-1 p-1 rounded-xl bg-brand-panel2 border border-brand-line mb-6">
      {tabs.map((t) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          aria-current={active === t ? "true" : undefined}
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition flex items-center gap-1.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-brand-blue ${
            active === t
              ? "bg-brand-blue text-white"
              : "text-brand-muted hover:text-brand-ink hover:bg-brand-panel2"
          }`}
        >
          {t}
          {counts[t] > 0 && (
            <span
              className={`text-[10px] font-bold rounded-full min-w-[16px] h-4 px-1 inline-flex items-center justify-center ${
                active === t ? "bg-white/25" : "bg-brand-blueSoft text-brand-blue"
              }`}
            >
              {counts[t]}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}

export function fmt(dt) {
  if (!dt) return "—";
  // browser's own locale/timezone — the app is not region-hardcoded
  return new Date(dt).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

// <input type="datetime-local"> wants "YYYY-MM-DDTHH:mm" in LOCAL time, with no
// timezone suffix — Date's own ISO string is UTC, so this reads the browser's
// local fields directly instead of slicing the ISO string (which would silently
// shift the displayed time by the UTC offset).
export function toDatetimeLocal(dt) {
  if (!dt) return "";
  const d = new Date(dt);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// Reverse of the above: a "YYYY-MM-DDTHH:mm" local-time string back into a real
// Date, which JS then serializes with the correct UTC offset for the API.
export function fromDatetimeLocal(value) {
  return value ? new Date(value) : null;
}
