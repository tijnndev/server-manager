import { Suspense, lazy, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type Template } from "../api";
import { ConfirmDialog, Empty, Notice, SkeletonRows } from "../components/ui";

const CodeEditor = lazy(() => import("../components/CodeEditor").then((m) => ({ default: m.CodeEditor })));
import { FileCode, Refresh, Spinner } from "../components/icons";

export function Templates() {
  const qc = useQueryClient();
  const templates = useQuery({ queryKey: ["templates"], queryFn: api.templates });
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const [current, setCurrent] = useState<Template | null>(null);
  const [yaml, setYaml] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [confirmReset, setConfirmReset] = useState(false);

  const save = useMutation({
    mutationFn: () => api.saveTemplate(current?.id || "", yaml),
    onSuccess: () => {
      setError("");
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["templates"] });
      window.setTimeout(() => setSaved(false), 2500);
    },
    onError: (err: Error) => setError(err.message),
  });
  const reset = useMutation({
    mutationFn: () => api.resetTemplate(current!.id),
    onSuccess: () => {
      setError("");
      setConfirmReset(false);
      qc.invalidateQueries({ queryKey: ["templates"] });
      const id = current?.id;
      if (id) {
        api.templates().then((all) => {
          const t = all.find((x) => x.id === id);
          if (t) {
            setCurrent(t);
            setYaml(t.yaml || "");
          }
        });
      }
    },
    onError: (err: Error) => setError(err.message),
  });

  const isAdmin = me.data?.role === "admin";

  const sorted = (templates.data ?? []).slice().sort((a, b) => a.name.localeCompare(b.name));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Templates</h1>
          <p className="desc">Stack blueprints as YAML. Saving stores an override; reset restores the file on disk.</p>
        </div>
      </div>

      {templates.isLoading && <SkeletonRows cols={[200, 260]} rows={3} />}
      {templates.isError && <Notice kind="err">{(templates.error as Error).message}</Notice>}

      {templates.data && sorted.length === 0 && (
        <div className="panel">
          <Empty icon={<FileCode size={28} />} title="No templates" hint="Templates define reusable stack blueprints." />
        </div>
      )}

      {sorted.length > 0 && (
        <div className="tpl-grid">
          <div className="panel">
            {sorted.map((tpl) => (
              <button
                key={tpl.id}
                className={`tpl-item${current?.id === tpl.id ? " on" : ""}`}
                onClick={() => {
                  setCurrent(tpl);
                  setYaml(tpl.yaml || "");
                  setError("");
                  setSaved(false);
                }}
                aria-pressed={current?.id === tpl.id}
              >
                <div className="tpl-name">{tpl.name}</div>
                <div className="tpl-desc">{tpl.description || tpl.id}</div>
              </button>
            ))}
          </div>

          <div>
            {current ? (
              <form
                className="panel"
                onSubmit={(e) => {
                  e.preventDefault();
                  setError("");
                  save.mutate();
                }}
              >
                <div className="log-head">
                  <FileCode size={15} className="ico" />
                  <span className="title">{current.name}</span>
                  <span className="muted" style={{ fontSize: 12 }}>{current.services.length} service{current.services.length === 1 ? "" : "s"}</span>
                  <span className="spacer" />
                  {isAdmin && (
                    <button type="button" className="btn btn-sm" onClick={() => setConfirmReset(true)} disabled={reset.isPending}>
                      {reset.isPending ? <Spinner /> : <Refresh size={13} />}
                      Reset
                    </button>
                  )}
                  {isAdmin && (
                    <button className="btn btn-primary btn-sm" disabled={save.isPending}>
                      {save.isPending ? <Spinner /> : null}
                      {saved ? "Saved" : "Save override"}
                    </button>
                  )}
                </div>
                {saved && <div style={{ padding: "8px 12px 0" }}><Notice kind="ok">Template override saved.</Notice></div>}
                {error && <div style={{ padding: "8px 12px 0" }}><Notice kind="err">{error}</Notice></div>}
                <div key={current.id} style={{ borderTop: "1px solid var(--border)" }}>
                  <Suspense fallback={<div className="muted" style={{ padding: 16 }}>Loading editor…</div>}>
                    <CodeEditor path={`${current.id}.yaml`} value={yaml} onChange={setYaml} readOnly={!isAdmin} height={480} />
                  </Suspense>
                </div>
                {!isAdmin && (
                  <div style={{ padding: "8px 12px 12px" }}>
                    <Notice kind="info">Only admins can edit template overrides.</Notice>
                  </div>
                )}
              </form>
            ) : (
              <div className="panel">
                <Empty icon={<FileCode size={28} />} title="Select a template" hint="Pick a template on the left to view and edit its YAML." />
              </div>
            )}
          </div>
        </div>
      )}

      {current && (
        <ConfirmDialog
          open={confirmReset}
          danger
          title="Reset template override?"
          body={`The saved override for "${current.name}" will be removed and the template will fall back to the file on disk.`}
          confirmLabel="Reset"
          pending={reset.isPending}
          onConfirm={() => reset.mutate()}
          onCancel={() => setConfirmReset(false)}
        />
      )}
    </div>
  );
}