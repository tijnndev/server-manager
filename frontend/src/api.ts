export type User = { id: number; username: string; role: string };

export type Service = {
  name: string;
  http: boolean;
  internalPort: number;
  hostPort: number;
  logs: boolean;
  shell: boolean;
  status: string;
  cpu: number;
  memory: number;
  memoryLimit: number;
  containerId: string;
};

export type Stack = {
  id: string;
  name: string;
  desired: string;
  source: string;
  templateId: string;
  description: string;
  owner: string;
  createdAt: string;
  services: Service[];
};

export type TemplateField = { key: string; label: string; default: string };

export type Template = {
  id: string;
  name: string;
  description: string;
  dockerfile?: string;
  fields?: TemplateField[];
  services: { name: string; shell: boolean; logs: boolean; http: boolean }[];
  yaml?: string;
};

export type Domain = {
  id: number;
  service: string;
  hostname: string;
  upstreamPort: number;
  tls: boolean;
  cloudflare: boolean;
};

export type Schedule = { id: number; action: string; cron: string; enabled: boolean };
export type Subuser = { id: number; username: string; userId: number };
export type Activity = {
  id: number;
  username: string;
  stack: string;
  action: string;
  detail: string;
  createdAt: string;
};

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("X-SM-Request", "1");
  if (init?.body && !headers.has("Content-Type") && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(path, { credentials: "include", ...init, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error((data as { error?: string }).error || res.statusText);
  }
  return data as T;
}

export const api = {
  me: () => req<User>("/api/auth/me"),
  login: (username: string, password: string) =>
    req<User>("/api/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => req<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  stacks: () => req<Stack[]>("/api/stacks"),
  stack: (name: string) => req<{ stack: Stack; domains: Domain[] }>(`/api/stacks/${name}`),
  createStack: (body: {
    name: string;
    templateId?: string;
    description?: string;
    overrides?: Record<string, string>;
    compose?: string;
  }) => req<{ name: string }>("/api/stacks", { method: "POST", body: JSON.stringify(body) }),
  deleteStack: (name: string) => req(`/api/stacks/${name}`, { method: "DELETE" }),
  power: (name: string, action: string) =>
    req(`/api/stacks/${name}/power/${action}`, { method: "POST" }),
  exec: (name: string, service: string, command: string) =>
    req<{ output: string; exitCode: number }>(`/api/stacks/${name}/exec`, {
      method: "POST",
      body: JSON.stringify({ service, command }),
    }),
  files: (name: string, path = "") =>
    req<{ name: string; dir: boolean; size: number; modTime: string }[]>(
      `/api/stacks/${name}/files?path=${encodeURIComponent(path)}`,
    ),
  readFile: (name: string, path: string) =>
    req<{ content: string }>(`/api/stacks/${name}/files/content?path=${encodeURIComponent(path)}`),
  writeFile: (name: string, path: string, content: string) =>
    req(`/api/stacks/${name}/files/content?path=${encodeURIComponent(path)}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  deleteFile: (name: string, path: string) =>
    req(`/api/stacks/${name}/files?path=${encodeURIComponent(path)}`, { method: "DELETE" }),
  mkdir: (name: string, path: string) =>
    req(`/api/stacks/${name}/files/mkdir`, { method: "POST", body: JSON.stringify({ path }) }),
  upload: async (name: string, dir: string, file: File) => {
    const body = new FormData();
    body.set("file", file);
    return req(`/api/stacks/${name}/files/upload?path=${encodeURIComponent(dir)}`, { method: "POST", body });
  },
  git: (name: string) => req<{ repo: boolean; output: string; error?: string }>(`/api/stacks/${name}/git`),
  gitPull: (name: string) => req<{ output: string }>(`/api/stacks/${name}/git/pull`, { method: "POST" }),
  gitClone: (name: string, url: string) =>
    req<{ output: string }>(`/api/stacks/${name}/git/clone`, { method: "POST", body: JSON.stringify({ url }) }),
  domains: (name: string) => req<Domain[]>(`/api/stacks/${name}/domains`),
  publish: (name: string, body: { hostname: string; service: string; tls: boolean; cloudflare: boolean }) =>
    req<{ nginx: boolean; tls: boolean; cloudflare: boolean; warnings?: string[] }>(`/api/stacks/${name}/publish`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  unpublish: (name: string, hostname: string) =>
    req(`/api/stacks/${name}/domains/${hostname}`, { method: "DELETE" }),
  schedules: (name: string) => req<Schedule[]>(`/api/stacks/${name}/schedules`),
  createSchedule: (name: string, action: string, cron: string) =>
    req(`/api/stacks/${name}/schedules`, { method: "POST", body: JSON.stringify({ action, cron }) }),
  deleteSchedule: (name: string, id: number) => req(`/api/stacks/${name}/schedules/${id}`, { method: "DELETE" }),
  subusers: (name: string) => req<Subuser[]>(`/api/stacks/${name}/subusers`),
  addSubuser: (name: string, username: string) =>
    req(`/api/stacks/${name}/subusers`, { method: "POST", body: JSON.stringify({ username }) }),
  removeSubuser: (name: string, userId: number) =>
    req(`/api/stacks/${name}/subusers/${userId}`, { method: "DELETE" }),
  templates: () => req<Template[]>("/api/templates"),
  saveTemplate: (id: string, yaml: string) =>
    req(`/api/templates/${id}`, { method: "PUT", body: JSON.stringify({ yaml }) }),
  resetTemplate: (id: string) => req(`/api/templates/${id}`, { method: "DELETE" }),
  activity: () => req<Activity[]>("/api/activity"),
  settings: () =>
    req<{ discordWebhook: string; cloudflareToken: string; publicIP: string; acmeEmail: string }>("/api/settings"),
  saveSettings: (body: { discordWebhook: string; cloudflareToken: string; publicIP: string; acmeEmail: string }) =>
    req("/api/settings", { method: "PUT", body: JSON.stringify(body) }),
  users: () => req<User[]>("/api/users"),
  createUser: (username: string, password: string, role: string) =>
    req("/api/users", { method: "POST", body: JSON.stringify({ username, password, role }) }),
  mail: () => req<{ users: string[]; error?: string }>("/api/mail"),
  createMail: (email: string, password: string) =>
    req("/api/mail", { method: "POST", body: JSON.stringify({ email, password }) }),
  deleteMail: (email: string) => req("/api/mail/delete", { method: "POST", body: JSON.stringify({ email }) }),
  mailPassword: (email: string, password: string) =>
    req("/api/mail/password", { method: "POST", body: JSON.stringify({ email, password }) }),
};

export function socketURL(path: string) {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${location.host}${path}`;
}
