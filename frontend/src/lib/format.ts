import type { Service, Stack } from "../api";

export function bytes(n: number): string {
  if (!n) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

export function cpu(n: number): string {
  return n ? `${n.toFixed(1)}%` : "—";
}

/** Relative timestamp: "3 min ago", with absolute time in the title attribute. */
export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diff = Date.now() - then;
  const min = Math.round(diff / 60000);
  if (min < 1) return "just now";
  if (min < 60) return `${min} min ago`;
  const h = Math.round(min / 60);
  if (h < 24) return `${h} h ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} d ago`;
  return new Date(iso).toLocaleDateString();
}

export function fullTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}

type Pill = "ok" | "warn" | "danger" | "off";

const SERVICE_PILL: Record<string, Pill> = {
  running: "ok",
  restarting: "warn",
  paused: "warn",
  created: "warn",
  exited: "off",
  dead: "danger",
  removing: "warn",
};

export function servicePill(status: string): Pill {
  return SERVICE_PILL[status] ?? "warn";
}

export type StackStatus = { pill: Pill; label: string };

/** Derive the overall stack status from its services. */
export function stackStatus(stack: Stack): StackStatus {
  const states = stack.services.map((s: Service) => s.status);
  if (!states.length) return { pill: "off", label: "No services" };
  const running = states.filter((s) => s === "running").length;
  if (running === states.length) {
    return stack.desired === "running"
      ? { pill: "ok", label: "Running" }
      : { pill: "warn", label: "Running · desired " + stack.desired };
  }
  if (running === 0) {
    return stack.desired === "running"
      ? { pill: "danger", label: "Stopped · desired running" }
      : { pill: "off", label: "Stopped" };
  }
  return { pill: "warn", label: `${running}/${states.length} running` };
}