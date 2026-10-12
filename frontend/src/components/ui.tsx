import { ReactNode, useEffect, useRef, useState } from "react";
import { AlertTriangle, Check, Info, Spinner, X } from "./icons";

/* ------------------------------------------------------------------
   Status pill — color always paired with a text label and dot.
   ------------------------------------------------------------------ */

export function Pill({ tone, children }: { tone: "ok" | "warn" | "danger" | "info" | "off"; children: ReactNode }) {
  return (
    <span className={`pill pill-${tone}`}>
      <span className="dot" />
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------
   Inline notices for success / error / warning / info feedback.
   ------------------------------------------------------------------ */

export function Notice({ kind, children }: { kind: "ok" | "err" | "warn" | "info"; children: ReactNode }) {
  const icon = kind === "ok" ? <Check /> : kind === "err" ? <AlertTriangle /> : kind === "warn" ? <AlertTriangle /> : <Info />;
  return (
    <div className={`notice notice-${kind}`} role={kind === "err" ? "alert" : "status"}>
      <span className="ico">{icon}</span>
      <span>{children}</span>
    </div>
  );
}

/* ------------------------------------------------------------------
   Empty state.
   ------------------------------------------------------------------ */

export function Empty({ icon, title, hint, action }: { icon: ReactNode; title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="ico">{icon}</span>
      <span className="title">{title}</span>
      {hint && <span className="hint">{hint}</span>}
      {action && <div className="action">{action}</div>}
    </div>
  );
}

/* ------------------------------------------------------------------
   Skeleton row for list/table loading states.
   ------------------------------------------------------------------ */

export function SkeletonRows({ cols, rows = 5 }: { cols: number[]; rows?: number }) {
  return (
    <div className="table-wrap" aria-hidden="true">
      <table>
        <thead>
          <tr>
            {cols.map((_w, i) => (
              <th key={i}>
                <span className="skeleton" style={{ display: "inline-block", width: 48 }} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r}>
              {cols.map((w, i) => (
                <td key={i}>
                  <span className="skeleton" style={{ display: "inline-block", width: w }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ------------------------------------------------------------------
   Confirm dialog — used for destructive operations. Optionally asks
   for a text input (e.g. new mail password).
   ------------------------------------------------------------------ */

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "Confirm",
  danger = false,
  input,
  pending = false,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  input?: { placeholder?: string; type?: string };
  pending?: boolean;
  error?: string;
  onConfirm: (value: string) => void;
  onCancel: () => void;
}) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setValue("");
      const t = window.setTimeout(() => {
        (inputRef.current ?? document.activeElement?.closest(".dialog")?.querySelector("button"))?.focus();
      }, 0);
      const onKey = (e: KeyboardEvent) => {
        if (e.key === "Escape") onCancel();
      };
      window.addEventListener("keydown", onKey);
      return () => {
        window.clearTimeout(t);
        window.removeEventListener("keydown", onKey);
      };
    }
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onCancel()}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        {danger && (
          <div className="dlg-ico danger">
            <AlertTriangle size={18} />
          </div>
        )}
        <h2>{title}</h2>
        <div className="dlg-body">{body}</div>
        {input && (
          <div className="field" style={{ marginBottom: 14 }}>
            <input
              ref={inputRef}
              className="input"
              type={input.type ?? "text"}
              placeholder={input.placeholder}
              value={value}
              autoComplete="off"
              onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !pending) onConfirm(value);
              }}
            />
          </div>
        )}
        {error && <Notice kind="err">{error}</Notice>}
        <div className="dlg-actions">
          <button className="btn" onClick={onCancel} disabled={pending}>
            Cancel
          </button>
          <button className={danger ? "btn btn-danger-solid" : "btn btn-primary"} onClick={() => onConfirm(value)} disabled={pending}>
            {pending && <Spinner />}
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------
   Inline confirm for row-level destructive actions: the Delete button
   swaps to Confirm/Cancel in place. No full dialog needed.
   ------------------------------------------------------------------ */

export function InlineConfirm({
  label = "Delete",
  confirmLabel = "Confirm",
  pending = false,
  onConfirm,
}: {
  label?: string;
  confirmLabel?: string;
  pending?: boolean;
  onConfirm: () => void;
}) {
  const [arm, setArm] = useState(false);
  useEffect(() => {
    if (!arm) return;
    const t = window.setTimeout(() => setArm(false), 4000);
    return () => window.clearTimeout(t);
  }, [arm]);

  if (!arm) {
    return (
      <button className="btn btn-danger btn-sm" onClick={() => setArm(true)}>
        {label}
      </button>
    );
  }
  return (
    <span className="row" style={{ gap: 4 }}>
      <button className="btn btn-danger-solid btn-sm" onClick={onConfirm} disabled={pending}>
        {pending ? <Spinner /> : null}
        {confirmLabel}
      </button>
      <button className="btn btn-ghost btn-sm" onClick={() => setArm(false)} aria-label="Cancel deletion">
        <X size={13} />
      </button>
    </span>
  );
}

/* ------------------------------------------------------------------
   Small helpers for mutations: pending state on the triggering button.
   ------------------------------------------------------------------ */

export function PendingLabel({ pending, idle, active }: { pending: boolean; idle: string; active: string }) {
  return (
    <>
      {pending && <Spinner />}
      {pending ? active : idle}
    </>
  );
}