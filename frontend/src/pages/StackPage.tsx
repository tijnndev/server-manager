import { FormEvent, Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, socketURL, type Stack } from "../api";
import { usePanel } from "../panel";
import { ConfirmDialog, Empty, InlineConfirm, Notice, Pill, SkeletonRows } from "../components/ui";

const CodeEditor = lazy(() => import("../components/CodeEditor").then((m) => ({ default: m.CodeEditor })));
import {
  Check,
  ChevronUp,
  Clock,
  File,
  Folder,
  FolderPlus,
  GitBranch,
  Globe,
  Layers,
  Play,
  Plus,
  Refresh,
  Restart,
  Sliders,
  Spinner,
  Square,
  Terminal,
  Trash,
  Upload,
  Users,
  X,
} from "../components/icons";
import { bytes, servicePill, stackStatus } from "../lib/format";

const tabs = ["console", "files", "git", "domain", "schedule", "access", "settings"] as const;
type Tab = (typeof tabs)[number];

export function StackPage() {
  const { name = "" } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const panel = usePanel();
  const [tab, setTab] = useState<Tab>("console");
  const [error, setError] = useState("");
  const [pendingAction, setPendingAction] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);
  const stacks = useQuery({ queryKey: ["stacks"], queryFn: api.stacks });
  const detail = useQuery({ queryKey: ["stack", name], queryFn: () => api.stack(name) });
  const stack = (stacks.data ?? []).find((s) => s.name === name) ?? detail.data?.stack;

  const subscribe = panel.subscribe;
  const unsubscribe = panel.unsubscribe;
  useEffect(() => {
    subscribe(name);
    return () => unsubscribe(name);
  }, [name, subscribe, unsubscribe]);

  const power = useMutation({
    mutationFn: (action: string) => api.power(name, action),
    onSuccess: () => {
      setError("");
      qc.invalidateQueries({ queryKey: ["stacks"] });
      qc.invalidateQueries({ queryKey: ["stack", name] });
    },
    onError: (err: Error) => setError(err.message),
  });
  const remove = useMutation({
    mutationFn: () => api.deleteStack(name),
    onSuccess: () => nav("/"),
    onError: (err: Error) => setError(err.message),
  });

  if (!stack && stacks.isLoading) {
    return (
      <div className="page">
        <SkeletonRows cols={[200, 120, 300]} />
      </div>
    );
  }
  if (!stack) {
    return (
      <div className="page">
        <div className="panel">
          <Empty icon={<Layers size={28} />} title="Stack not found" hint="It may have been removed." action={<Link className="btn" to="/">Back to stacks</Link>} />
        </div>
      </div>
    );
  }

  const st = stackStatus(stack);
  const busy = (action: string) => pendingAction === action && power.isPending;

  const runPower = (action: string) => {
    setPendingAction(action);
    power.mutate(action, {
      onSettled: () => setPendingAction(""),
    });
  };

  const powerBtn = (action: "start" | "stop" | "restart" | "rebuild", icon: React.ReactNode, label: string, busyLabel: string) => (
    <button
      className="btn"
      disabled={power.isPending}
      onClick={() => runPower(action)}
      aria-label={`${label} stack ${stack.name}`}
    >
      {busy(action) ? <Spinner /> : icon}
      {busy(action) ? busyLabel : label}
    </button>
  );

  return (
    <div className="page">
      <p className="breadcrumb">
        <Link to="/">Stacks</Link>
        <span aria-hidden="true">/</span>
        <span>{stack.name}</span>
      </p>
      <div className="page-head">
        <div>
          <div className="row" style={{ gap: 10 }}>
            <h1>{stack.name}</h1>
            <Pill tone={st.pill === "off" ? "off" : st.pill === "danger" ? "danger" : st.pill}>{st.label}</Pill>
          </div>
          <p className="desc">{stack.description || stack.templateId || stack.source}</p>
          <p className="desc muted" style={{ fontSize: 12 }}>
            Source: {stack.source} · Desired state: {stack.desired}
          </p>
        </div>
        <div className="row actions">
          {powerBtn("start", <Play />, "Start", "Starting…")}
          {powerBtn("stop", <Square />, "Stop", "Stopping…")}
          {powerBtn("restart", <Restart />, "Restart", "Restarting…")}
          {powerBtn("rebuild", <Refresh />, "Rebuild", "Rebuilding…")}
          <button className="btn btn-danger" onClick={() => setConfirmDelete(true)}>
            <Trash />
            Delete
          </button>
        </div>
      </div>

      {error && <Notice kind="err">{error}</Notice>}

      <div className="tabs" role="tablist" aria-label="Stack sections" style={{ marginBottom: 14 }}>
        {(
          [
            ["console", "Console", <Terminal size={14} />],
            ["files", "Files", <Folder size={14} />],
            ["git", "Git", <GitBranch size={14} />],
            ["domain", "Domains", <Globe size={14} />],
            ["schedule", "Schedules", <Clock size={14} />],
            ["access", "Access", <Users size={14} />],
            ["settings", "Settings", <Sliders size={14} />],
          ] as [Tab, string, React.ReactNode][]
        ).map(([id, label, icon]) => (
          <button key={id} role="tab" aria-selected={tab === id} className={`tab${tab === id ? " on" : ""}`} onClick={() => setTab(id)}>
            {icon}
            {label}
          </button>
        ))}
      </div>

      {tab === "console" && <Console stack={stack} logs={panel.logs[stack.name] ?? {}} />}
      {tab === "files" && <Files name={stack.name} />}
      {tab === "git" && <Git name={stack.name} />}
      {tab === "domain" && <Domains name={stack.name} stack={stack} />}
      {tab === "schedule" && <Schedules name={stack.name} />}
      {tab === "access" && <Access name={stack.name} />}
      {tab === "settings" && <Settings stack={stack} />}

      <ConfirmDialog
        open={confirmDelete}
        danger
        title={`Delete ${stack.name}?`}
        body="The stack definition and its containers will be removed. Files inside the stack directory are kept on disk. This cannot be undone."
        confirmLabel="Delete stack"
        pending={remove.isPending}
        onConfirm={() => remove.mutate(undefined, { onSettled: () => setConfirmDelete(false) })}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

/* ------------------------------------------------------------------
   Console: service picker, live logs, exec and interactive shell.
   ------------------------------------------------------------------ */

function Console({ stack, logs }: { stack: Stack; logs: Record<string, string[]> }) {
  const services = stack.services.filter((svc) => svc.logs || svc.shell);
  const [service, setService] = useState(services.find((svc) => svc.shell)?.name || services[0]?.name || "");
  const [command, setCommand] = useState("");
  const [output, setOutput] = useState("");
  const [shell, setShell] = useState("");
  const [shellLine, setShellLine] = useState("");
  const shellRef = useRef<WebSocket | null>(null);
  const logRef = useRef<HTMLPreElement>(null);
  const shellLogRef = useRef<HTMLPreElement>(null);
  const lines = useMemo(() => (logs[service] ?? []).join("\n"), [logs, service]);
  const current = stack.services.find((svc) => svc.name === service);

  // Auto-scroll log output to the newest line.
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [lines]);
  useEffect(() => {
    if (shellLogRef.current) shellLogRef.current.scrollTop = shellLogRef.current.scrollHeight;
  }, [shell]);

  const run = async (e: FormEvent) => {
    e.preventDefault();
    setOutput("");
    try {
      const res = await api.exec(stack.name, service, command);
      setOutput(`$ ${command}\n${res.output}${res.exitCode ? `\nexit ${res.exitCode}` : ""}`);
    } catch (err) {
      setOutput((err as Error).message);
    }
  };

  const openShell = () => {
    shellRef.current?.close();
    const ws = new WebSocket(socketURL(`/api/stacks/${stack.name}/shell?service=${encodeURIComponent(service)}`));
    shellRef.current = ws;
    setShell("");
    ws.binaryType = "arraybuffer";
    ws.onmessage = (ev) => {
      const text = typeof ev.data === "string" ? ev.data : new TextDecoder().decode(ev.data as ArrayBuffer);
      setShell((prev) => (prev + text).slice(-8000));
    };
  };

  if (!services.length) {
    return (
      <div className="panel">
        <Empty icon={<Terminal size={28} />} title="No loggable services" hint="None of the services in this stack expose logs or a shell." />
      </div>
    );
  }

  return (
    <div className="console-grid">
      <div className="svc-list" role="tablist" aria-label="Services">
        {services.map((svc) => (
          <button key={svc.name} role="tab" aria-selected={svc.name === service} className={`svc-item${svc.name === service ? " on" : ""}`} onClick={() => setService(svc.name)}>
            <span className={`svc-dot ${servicePill(svc.status)}`} />
            <span className="mono" style={{ fontSize: 12 }}>{svc.name}</span>
            {svc.hostPort ? <span className="badge port">{svc.hostPort}</span> : null}
          </button>
        ))}
      </div>
      <div>
        <div className="log-panel">
          <div className="log-head">
            <span className="title">{service}</span>
            <Pill tone={current ? servicePill(current.status) : "off"}>{current?.status ?? "unknown"}</Pill>
            <span className="spacer" />
            {current?.hostPort ? <span className="badge">:{current.hostPort}</span> : null}
          </div>
          <pre className="log" ref={logRef}>
            {lines || "No log lines yet. Start the stack to attach to this service."}
          </pre>
        </div>
        {current?.shell && (
          <form className="row" style={{ marginTop: 12 }} onSubmit={run}>
            <input
              className="input mono"
              style={{ fontSize: 12 }}
              value={command}
              onChange={(e) => setCommand(e.target.value)}
              placeholder="Run a command in this container"
              aria-label="Command"
            />
            <button className="btn" disabled={!command.trim()}>
              <Terminal />
              Run
            </button>
            <button type="button" className="btn btn-ghost" onClick={openShell}>
              Shell
            </button>
          </form>
        )}
        {output && (
          <div className="log-panel file-editor">
            <div className="log-head">
              <span className="title">Command output</span>
            </div>
            <pre className="log" style={{ minHeight: 0, maxHeight: 280 }}>{output}</pre>
          </div>
        )}
        {shell && (
          <form
            className="file-editor"
            onSubmit={(e) => {
              e.preventDefault();
              shellRef.current?.send(shellLine + "\n");
              setShellLine("");
            }}
          >
            <div className="log-panel">
              <div className="log-head">
                <span className="title">Interactive shell</span>
                <span className="spacer" />
                <button
                  type="button"
                  className="icon-btn icon-btn-sm"
                  onClick={() => {
                    shellRef.current?.close();
                    setShell("");
                  }}
                  aria-label="Close shell session"
                >
                  <X size={14} />
                </button>
              </div>
              <pre className="log" ref={shellLogRef} style={{ minHeight: 200, maxHeight: 320 }}>{shell}</pre>
            </div>
            <div className="row" style={{ marginTop: 8 }}>
              <input
                className="input mono"
                style={{ fontSize: 12 }}
                value={shellLine}
                onChange={(e) => setShellLine(e.target.value)}
                placeholder="Shell input"
                aria-label="Shell input"
              />
              <button className="btn" type="button" onClick={() => { shellRef.current?.send(shellLine + "\n"); setShellLine(""); }}>
                Send
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------
   Files
   ------------------------------------------------------------------ */

function Files({ name }: { name: string }) {
  const [path, setPath] = useState("");
  const [file, setFile] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState("");
  const qc = useQueryClient();
  const listing = useQuery({ queryKey: ["files", name, path], queryFn: () => api.files(name, path) });
  const open = async (next: string) => {
    setError("");
    try {
      const res = await api.readFile(name, next);
      setFile(next);
      setContent(res.content);
    } catch (err) {
      setError((err as Error).message);
    }
  };
  const refresh = () => qc.invalidateQueries({ queryKey: ["files", name, path] });

  const crumbs = path ? path.split("/") : [];

  return (
    <div>
      <div className="toolbar" style={{ marginBottom: 12 }}>
        <button className="btn btn-sm" onClick={() => setPath(path.split("/").slice(0, -1).join("/"))} disabled={!path} aria-label="Go up one directory">
          <ChevronUp size={14} />
          Up
        </button>
        <span className="badge mono" title={`/${path}`}>/{path}</span>
        <span className="spacer" />
        <form
          className="row"
          style={{ gap: 6 }}
          onSubmit={(e) => {
            e.preventDefault();
            const dir = new FormData(e.currentTarget).get("dir");
            if (typeof dir === "string" && dir) {
              api.mkdir(name, path ? `${path}/${dir}` : dir).then(() => {
                e.currentTarget.reset();
                refresh();
              });
            }
          }}
        >
          <input className="input" style={{ width: 170, height: 26 }} name="dir" placeholder="New directory" aria-label="New directory name" />
          <button className="btn btn-sm">
            <FolderPlus size={14} />
            Create
          </button>
        </form>
        <label className="btn btn-sm" style={{ cursor: "pointer" }}>
          <Upload size={14} />
          Upload
          <input
            type="file"
            style={{ display: "none" }}
            aria-label="Upload file"
            onChange={(e) => {
              const picked = e.target.files?.[0];
              if (picked) api.upload(name, path, picked).then(refresh);
            }}
          />
        </label>
      </div>

      {crumbs.length > 0 && (
        <div className="row" style={{ marginBottom: 8, fontSize: 12 }}>
          <Link to="" onClick={(e) => { e.preventDefault(); setPath(""); }} className="muted">root</Link>
          {crumbs.map((c, i) => (
            <span key={i} className="row" style={{ gap: 5 }}>
              <span className="muted" aria-hidden="true">/</span>
              <Link to="" onClick={(e) => { e.preventDefault(); setPath(crumbs.slice(0, i + 1).join("/")); }} className={i === crumbs.length - 1 ? "dim" : "muted"}>
                {c}
              </Link>
            </span>
          ))}
        </div>
      )}

      {error && <Notice kind="err">{error}</Notice>}
      {listing.isError && <Notice kind="err">{(listing.error as Error).message}</Notice>}

      {listing.isLoading ? (
        <SkeletonRows cols={[280, 100, 160, 80]} rows={4} />
      ) : (listing.data ?? []).length === 0 ? (
        <div className="panel">
          <Empty icon={<Folder size={28} />} title="Empty directory" hint="No files in this directory yet." />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th className="num">Size</th>
                <th>Modified</th>
                <th style={{ width: 130 }} aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {(listing.data ?? []).map((entry) => {
                const full = path ? `${path}/${entry.name}` : entry.name;
                return (
                  <tr key={entry.name}>
                    <td>
                      <span className="row">
                        <span className="muted" style={{ display: "inline-flex" }}>
                          {entry.dir ? <Folder size={15} /> : <File size={15} />}
                        </span>
                        <button
                          className="link"
                          style={{ background: "transparent", border: 0, padding: 0, font: "inherit", cursor: "pointer", color: entry.dir ? "var(--text)" : "var(--text-secondary)" }}
                          onClick={() => {
                            if (entry.dir) setPath(full);
                            else void open(full);
                          }}
                        >
                          {entry.name}
                        </button>
                      </span>
                    </td>
                    <td className="num mono">{entry.dir ? "—" : bytes(entry.size)}</td>
                    <td className="muted" style={{ fontSize: 12.5 }}>{entry.modTime ? new Date(entry.modTime).toLocaleString() : "—"}</td>
                    <td>
                      <span className="row" style={{ justifyContent: "flex-end" }}>
                        {!entry.dir && (
                          <button className="btn btn-sm" onClick={() => void open(full)}>
                            Edit
                          </button>
                        )}
                        <InlineConfirm onConfirm={() => api.deleteFile(name, full).then(refresh)} />
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {file && (
        <form
          className="panel file-editor"
          onSubmit={(e) => {
            e.preventDefault();
            api.writeFile(name, file, content)
              .then(() => setError(""))
              .catch((err: Error) => setError(err.message));
          }}
        >
          <div className="ed-head">
            <File size={15} className="ico" />
            <span className="mono" style={{ fontSize: 12 }}>{file}</span>
            <span className="spacer" />
            <button type="button" className="icon-btn icon-btn-sm" onClick={() => setFile("")} aria-label="Close editor">
              <X size={14} />
            </button>
            <button className="btn btn-primary btn-sm" type="submit">
              Save
            </button>
          </div>
          <div key={file} style={{ borderTop: "1px solid var(--border)" }}>
            <Suspense fallback={<div className="muted" style={{ padding: 16 }}>Loading editor…</div>}>
              <CodeEditor path={file} value={content} onChange={setContent} height={480} />
            </Suspense>
          </div>
        </form>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------
   Git
   ------------------------------------------------------------------ */

function Git({ name }: { name: string }) {
  const git = useQuery({ queryKey: ["git", name], queryFn: () => api.git(name) });
  const [url, setUrl] = useState("");
  const [output, setOutput] = useState("");
  const [error, setError] = useState("");
  const [pulling, setPulling] = useState(false);
  const [cloning, setCloning] = useState(false);
  return (
    <div>
      {git.isError && <Notice kind="err">{(git.error as Error).message}</Notice>}
      <div className="log-panel">
        <div className="log-head">
          <GitBranch size={14} className="ico" />
          <span className="title">git status</span>
        </div>
        <pre className="log" style={{ minHeight: 160, maxHeight: 320 }}>
          {git.isLoading ? "Loading…" : git.data?.repo ? git.data.output || "clean" : "No git repository in this stack."}
        </pre>
      </div>
      {git.data?.repo && (
        <div className="row" style={{ marginTop: 12 }}>
          <button
            className="btn"
            disabled={pulling}
            onClick={() => {
              setPulling(true);
              setError("");
              api.gitPull(name)
                .then((res) => setOutput(res.output))
                .catch((err: Error) => setError(err.message))
                .finally(() => setPulling(false));
            }}
          >
            {pulling ? <Spinner /> : <GitBranch />}
            Pull
          </button>
        </div>
      )}
      <form
        className="row"
        style={{ marginTop: 12 }}
        onSubmit={(e) => {
          e.preventDefault();
          setError("");
          setCloning(true);
          api.gitClone(name, url)
            .then((res) => {
              setOutput(res.output);
              git.refetch();
            })
            .catch((err: Error) => setError(err.message))
            .finally(() => setCloning(false));
        }}
      >
        <input className="input mono" style={{ fontSize: 12 }} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://github.com/org/repo.git" aria-label="Repository URL" />
        <button className="btn" disabled={cloning || !url.trim()}>
          {cloning ? <Spinner /> : <Plus />}
          Clone into stack
        </button>
      </form>
      {output && (
        <div className="log-panel file-editor">
          <div className="log-head">
            <span className="title">Output</span>
          </div>
          <pre className="log" style={{ minHeight: 0, maxHeight: 280 }}>{output}</pre>
        </div>
      )}
      {error && <Notice kind="err">{error}</Notice>}
    </div>
  );
}

/* ------------------------------------------------------------------
   Domains
   ------------------------------------------------------------------ */

function Domains({ name, stack }: { name: string; stack: Stack }) {
  const qc = useQueryClient();
  const domains = useQuery({ queryKey: ["domains", name], queryFn: () => api.domains(name) });
  const [hostname, setHostname] = useState("");
  const [service, setService] = useState(stack.services.find((svc) => svc.http)?.name || stack.services[0]?.name || "");
  const [tls, setTls] = useState(true);
  const [cloudflare, setCloudflare] = useState(false);
  const [error, setError] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [publishing, setPublishing] = useState(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["domains", name] });

  return (
    <div>
      <form
        className="panel panel-pad"
        onSubmit={(e) => {
          e.preventDefault();
          setError("");
          setWarnings([]);
          setPublishing(true);
          api.publish(name, { hostname, service, tls, cloudflare })
            .then((res) => {
              setWarnings(res.warnings ?? []);
              setHostname("");
              refresh();
            })
            .catch((err: Error) => setError(err.message))
            .finally(() => setPublishing(false));
        }}
      >
        <h2 className="section-title">Publish a domain</h2>
        <div className="form-grid" style={{ alignItems: "end" }}>
          <div className="field">
            <span className="label" id="lbl-host">Hostname</span>
            <input className="input mono" style={{ fontSize: 12 }} value={hostname} onChange={(e) => setHostname(e.target.value)} placeholder="app.example.com" aria-labelledby="lbl-host" required />
          </div>
          <div className="field">
            <span className="label" id="lbl-svc">Service</span>
            <select className="select" value={service} onChange={(e) => setService(e.target.value)} aria-labelledby="lbl-svc">
              {stack.services.map((svc) => (
                <option key={svc.name} value={svc.name}>
                  {svc.name}
                  {svc.hostPort ? ` :${svc.hostPort}` : ""}
                </option>
              ))}
            </select>
          </div>
          <label className="check">
            <input type="checkbox" checked={tls} onChange={(e) => setTls(e.target.checked)} />
            TLS certificate
          </label>
          <label className="check">
            <input type="checkbox" checked={cloudflare} onChange={(e) => setCloudflare(e.target.checked)} />
            Cloudflare DNS
          </label>
          <button className="btn btn-primary" disabled={publishing}>
            {publishing ? <Spinner /> : <Globe />}
            Publish
          </button>
        </div>
        {error && <Notice kind="err">{error}</Notice>}
        {warnings.map((item) => (
          <Notice key={item} kind="warn">
            {item}
          </Notice>
        ))}
      </form>

      <div style={{ marginTop: 16 }}>
        {domains.isLoading ? (
          <SkeletonRows cols={[220, 160, 120, 100]} rows={2} />
        ) : (domains.data ?? []).length === 0 ? (
          <div className="panel">
            <Empty icon={<Globe size={28} />} title="No domains published" hint="Publish a hostname above to route traffic to a service." />
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Hostname</th>
                  <th>Upstream</th>
                  <th>Security</th>
                  <th style={{ width: 110 }} aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {(domains.data ?? []).map((domain) => (
                  <tr key={domain.hostname}>
                    <td className="mono" style={{ fontSize: 12.5 }}>{domain.hostname}</td>
                    <td className="mono" style={{ fontSize: 12.5 }}>
                      {domain.service}:{domain.upstreamPort}
                    </td>
                    <td>
                      <span className="row wrap" style={{ gap: 6 }}>
                        {domain.tls && <span className="badge">TLS</span>}
                        {domain.cloudflare && <span className="badge">Cloudflare</span>}
                        {!domain.tls && !domain.cloudflare && <span className="muted">—</span>}
                      </span>
                    </td>
                    <td>
                      <span className="row" style={{ justifyContent: "flex-end" }}>
                        <InlineConfirm label="Remove" onConfirm={() => api.unpublish(name, domain.hostname).then(refresh)} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------
   Schedules
   ------------------------------------------------------------------ */

function Schedules({ name }: { name: string }) {
  const qc = useQueryClient();
  const rows = useQuery({ queryKey: ["schedules", name], queryFn: () => api.schedules(name) });
  const [cron, setCron] = useState("0 4 * * *");
  const [action, setAction] = useState("restart");
  const [error, setError] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["schedules", name] });

  return (
    <div>
      <form
        className="panel panel-pad"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          setError("");
          api.createSchedule(name, action, cron)
            .then(refresh)
            .catch((err: Error) => setError(err.message));
        }}
      >
        <h2 className="section-title">Add a schedule</h2>
        <div className="form-grid" style={{ alignItems: "end" }}>
          <div className="field">
            <span className="label" id="lbl-act">Action</span>
            <select className="select" value={action} onChange={(e) => setAction(e.target.value)} aria-labelledby="lbl-act">
              <option value="start">start</option>
              <option value="stop">stop</option>
              <option value="restart">restart</option>
            </select>
          </div>
          <div className="field">
            <span className="label" id="lbl-cron">Cron expression</span>
            <input className="input mono" style={{ fontSize: 12 }} value={cron} onChange={(e) => setCron(e.target.value)} aria-labelledby="lbl-cron" required />
            <span className="hint">minute hour day month weekday</span>
          </div>
          <button className="btn btn-primary">
            <Plus />
            Add schedule
          </button>
        </div>
        {error && <Notice kind="err">{error}</Notice>}
      </form>

      <div style={{ marginTop: 16 }}>
        {rows.isLoading ? (
          <SkeletonRows cols={[120, 160, 100]} rows={2} />
        ) : (rows.data ?? []).length === 0 ? (
          <div className="panel">
            <Empty icon={<Clock size={28} />} title="No schedules" hint="Automate start, stop or restart actions with a cron expression." />
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Action</th>
                  <th>Cron</th>
                  <th>State</th>
                  <th style={{ width: 110 }} aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {(rows.data ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>
                      <span className="badge" style={{ fontFamily: "var(--font)", fontSize: 12 }}>{row.action}</span>
                    </td>
                    <td className="mono" style={{ fontSize: 12.5 }}>{row.cron}</td>
                    <td>
                      {row.enabled ? <Pill tone="ok">Enabled</Pill> : <Pill tone="off">Disabled</Pill>}
                    </td>
                    <td>
                      <span className="row" style={{ justifyContent: "flex-end" }}>
                        <InlineConfirm onConfirm={() => api.deleteSchedule(name, row.id).then(refresh)} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------
   Access (subusers)
   ------------------------------------------------------------------ */

function Access({ name }: { name: string }) {
  const qc = useQueryClient();
  const rows = useQuery({ queryKey: ["subusers", name], queryFn: () => api.subusers(name) });
  const [username, setUsername] = useState("");
  const [error, setError] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["subusers", name] });

  return (
    <div>
      <form
        className="panel panel-pad"
        onSubmit={(e) => {
          e.preventDefault();
          api.addSubuser(name, username)
            .then(() => {
              setUsername("");
              setError("");
              refresh();
            })
            .catch((err: Error) => setError(err.message));
        }}
      >
        <h2 className="section-title">Grant stack access</h2>
        <div className="form-grid" style={{ alignItems: "end" }}>
          <div className="field">
            <span className="label" id="lbl-user">Username</span>
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="Existing panel user" aria-labelledby="lbl-user" required />
          </div>
          <button className="btn btn-primary">
            <Plus />
            Add access
          </button>
        </div>
        {error && <Notice kind="err">{error}</Notice>}
      </form>

      <div style={{ marginTop: 16 }}>
        {rows.isLoading ? (
          <SkeletonRows cols={[220, 110]} rows={1} />
        ) : (rows.data ?? []).length === 0 ? (
          <div className="panel">
            <Empty icon={<Users size={28} />} title="No additional users" hint="Only the stack owner has access. Add a user to grant access." />
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>User</th>
                  <th style={{ width: 110 }} aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {(rows.data ?? []).map((row) => (
                  <tr key={row.id}>
                    <td>{row.username}</td>
                    <td>
                      <span className="row" style={{ justifyContent: "flex-end" }}>
                        <InlineConfirm label="Revoke" onConfirm={() => api.removeSubuser(name, row.userId).then(refresh)} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------
 Settings: stack metadata. Runtime behaviour lives in compose.yaml;
 domains live in the Domains tab.
 ------------------------------------------------------------------ */

function Settings({ stack }: { stack: Stack }) {
  const qc = useQueryClient();
  const [desc, setDesc] = useState(stack.description);
  const [err, setErr] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => setDesc(stack.description), [stack.description]);

  const save = useMutation({
    mutationFn: () => api.patchStack(stack.name, { description: desc }),
    onSuccess: () => {
      setErr("");
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      qc.invalidateQueries({ queryKey: ["stacks"] });
      qc.invalidateQueries({ queryKey: ["stack", stack.name] });
    },
    onError: (e: Error) => setErr(e.message),
  });

  const info: [string, React.ReactNode][] = [
    ["Name", <span className="mono">{stack.name}</span>],
    ["Source", stack.source === "template" ? `template: ${stack.templateId || "custom"}` : stack.source],
    ["Owner", stack.owner],
    ["Created", new Date(stack.createdAt).toLocaleString()],
    ["Services", stack.services.map((s) => s.name).join(", ") || "—"],
    ["Ports", stack.services.map((s) => s.hostPort).filter(Boolean).join(", ") || "—"],
  ];

  return (
    <div>
      <form className="panel panel-pad" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <h2 className="section-title">Stack settings</h2>
        <div className="form-grid" style={{ alignItems: "end" }}>
          <div className="field">
            <span className="label" id="lbl-desc">Description</span>
            <input className="input" value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What runs here?" aria-labelledby="lbl-desc" />
          </div>
          <button className="btn btn-primary" disabled={save.isPending}>
            {save.isPending ? <Spinner /> : <Check />}
            {saved ? "Saved" : "Save"}
          </button>
        </div>
        {err && <Notice kind="err">{err}</Notice>}
      </form>

      <div className="panel panel-pad" style={{ marginTop: 16 }}>
        <h2 className="section-title">Details</h2>
        <div className="table-wrap">
          <table>
            <tbody>
              {info.map(([k, v]) => (
                <tr key={k}>
                  <th style={{ width: 140, textAlign: "left" }}>{k}</th>
                  <td>{v}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="desc muted" style={{ fontSize: 12, marginBottom: 0 }}>
          Runtime behaviour (type, command, ports, volumes) is defined in <span className="mono">compose.yaml</span> — edit it in the Files tab.
        </p>
      </div>
    </div>
  );
}