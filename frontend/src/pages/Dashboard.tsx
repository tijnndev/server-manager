import { FormEvent, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type Stack, type Template } from "../api";
import { Empty, Notice, Pill, SkeletonRows } from "../components/ui";
import { ChevronRight, Layers, Plus, Search, Spinner, X } from "../components/icons";
import { bytes, cpu, servicePill, stackStatus } from "../lib/format";

export function Dashboard() {
  const qc = useQueryClient();
  const stacks = useQuery({ queryKey: ["stacks"], queryFn: api.stacks });
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [compose, setCompose] = useState("");
  const [mode, setMode] = useState<"template" | "compose">("template");
  const [overrides, setOverrides] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  const selected = templates.data?.find((t) => t.id === templateId);
  const create = useMutation({
    mutationFn: () =>
      api.createStack(
        mode === "compose"
          ? { name, description, compose }
          : { name, description, templateId, overrides },
      ),
    onSuccess: () => {
      setOpen(false);
      setName("");
      setCompose("");
      setError("");
      qc.invalidateQueries({ queryKey: ["stacks"] });
    },
    onError: (err: Error) => setError(err.message),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    create.mutate();
  };

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const list = stacks.data ?? [];
    if (!q) return list;
    return list.filter(
      (s: Stack) =>
        s.name.toLowerCase().includes(q) ||
        (s.description ?? "").toLowerCase().includes(q) ||
        (s.templateId ?? "").toLowerCase().includes(q),
    );
  }, [stacks.data, search]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Stacks</h1>
          <p className="desc">
            {stacks.data
              ? `${stacks.data.length} stack${stacks.data.length === 1 ? "" : "s"} deployed`
              : "Docker compose stacks on this host"}
          </p>
        </div>
        <div className="row actions">
          <div className="search">
            <Search />
            <input
              className="input"
              style={{ width: 220 }}
              placeholder="Search stacks…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search stacks"
            />
          </div>
          <button className="btn btn-primary" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
            {open ? <X /> : <Plus />}
            {open ? "Close" : "New stack"}
          </button>
        </div>
      </div>

      {open && (
        <form className="panel panel-pad" style={{ marginBottom: 16 }} onSubmit={submit}>
          <div className="row" style={{ marginBottom: 14 }}>
            <div className="tabs" role="tablist" aria-label="Creation mode">
              <button
                type="button"
                className={`tab${mode === "template" ? " on" : ""}`}
                role="tab"
                aria-selected={mode === "template"}
                onClick={() => setMode("template")}
              >
                From template
              </button>
              <button
                type="button"
                className={`tab${mode === "compose" ? " on" : ""}`}
                role="tab"
                aria-selected={mode === "compose"}
                onClick={() => setMode("compose")}
              >
                Own compose file
              </button>
            </div>
          </div>
          <div className="form-grid">
            <div className="field">
              <span className="label" id="lbl-name">Name</span>
              <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="my-app" aria-labelledby="lbl-name" required />
            </div>
            <div className="field">
              <span className="label" id="lbl-desc">Description</span>
              <input className="input" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" aria-labelledby="lbl-desc" />
            </div>
            {mode === "template" &&
              (selected?.fields ?? []).map((field) => (
                <div className="field" key={field.key}>
                  <span className="label">{field.label}</span>
                  <input
                    className="input"
                    value={overrides[field.key] ?? ""}
                    onChange={(e) => setOverrides({ ...overrides, [field.key]: e.target.value })}
                  />
                </div>
              ))}
          </div>
          {mode === "template" && (
            <div className="field" style={{ marginTop: 12 }}>
              <span className="label" id="lbl-tpl">Template</span>
              <select
                className="select"
                value={templateId}
                required
                aria-labelledby="lbl-tpl"
                onChange={(e) => {
                  const id = e.target.value;
                  setTemplateId(id);
                  const tpl = templates.data?.find((t) => t.id === id);
                  const next: Record<string, string> = {};
                  for (const field of tpl?.fields ?? []) next[field.key] = field.default;
                  setOverrides(next);
                }}
              >
                <option value="">Select a template…</option>
                {(templates.data ?? [])
                  .slice()
                  .sort((a, b) => a.name.localeCompare(b.name))
                  .map((t: Template) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
              </select>
              {selected?.description && <span className="hint">{selected.description}</span>}
            </div>
          )}
          {mode === "compose" && (
            <div className="field" style={{ marginTop: 12 }}>
              <span className="label" id="lbl-compose">compose.yaml</span>
              <textarea
                className="textarea code"
                rows={12}
                value={compose}
                onChange={(e) => setCompose(e.target.value)}
                placeholder={'services:\n  web:\n    image: nginx\n    ports:\n      - "8080:80"'}
                aria-labelledby="lbl-compose"
                required
              />
            </div>
          )}
          {error && <Notice kind="err">{error}</Notice>}
          <div className="row" style={{ justifyContent: "flex-end", marginTop: 14 }}>
            <button className="btn btn-primary" disabled={create.isPending}>
              {create.isPending && <Spinner />}
              Create stack
            </button>
          </div>
        </form>
      )}

      {stacks.isLoading && <SkeletonRows cols={[140, 100, 200, 80, 60, 70]} />}
      {stacks.isError && <Notice kind="err">{(stacks.error as Error).message}</Notice>}

      {stacks.data &&
        (filtered.length === 0 ? (
          <div className="panel">
            <Empty
              icon={<Layers size={28} />}
              title={search ? "No stacks match your search" : "No stacks yet"}
              hint={
                search
                  ? "Try a different name, description or template."
                  : "Create your first stack from a template or your own compose file."
              }
              action={
                search ? undefined : (
                  <button className="btn btn-primary" onClick={() => setOpen(true)}>
                    <Plus />
                    New stack
                  </button>
                )
              }
            />
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Stack</th>
                  <th>Status</th>
                  <th>Services</th>
                  <th>Ports</th>
                  <th className="num">CPU</th>
                  <th className="num">Memory</th>
                  <th aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {filtered.map((stack) => {
                  const st = stackStatus(stack);
                  const ports = stack.services.filter((s) => s.hostPort).map((s) => s.hostPort);
                  const totalCpu = stack.services.reduce((a, s) => a + (s.cpu || 0), 0);
                  const totalMem = stack.services.reduce((a, s) => a + (s.memory || 0), 0);
                  return (
                    <tr key={stack.id}>
                      <td>
                        <Link to={`/stacks/${stack.name}`} className="primary-link">
                          {stack.name}
                        </Link>
                        {(stack.description || stack.templateId || stack.source) && (
                          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 1 }}>
                            {stack.description || stack.templateId || stack.source}
                          </div>
                        )}
                      </td>
                      <td>
                        <Pill tone={st.pill === "off" ? "off" : st.pill === "danger" ? "danger" : st.pill}>{st.label}</Pill>
                      </td>
                      <td>
                        <div className="row wrap" style={{ gap: 10 }}>
                          {stack.services.map((svc) => (
                            <span key={svc.name} className="svc-row" title={`${svc.name} · ${svc.status}`}>
                              <span className={`svc-dot ${servicePill(svc.status)}`} />
                              <span style={{ fontSize: 12.5 }}>{svc.name}</span>
                            </span>
                          ))}
                        </div>
                      </td>
                      <td>
                        {ports.length ? (
                          <span className="mono">{ports.join(", ")}</span>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td className="num mono">{cpu(totalCpu)}</td>
                      <td className="num mono">{bytes(totalMem)}</td>
                      <td style={{ width: 36 }}>
                        <Link to={`/stacks/${stack.name}`} aria-label={`Open ${stack.name}`} style={{ color: "var(--text-muted)", display: "inline-flex" }}>
                          <ChevronRight size={15} />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
    </div>
  );
}