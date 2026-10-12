import { FormEvent, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ConfirmDialog, Empty, InlineConfirm, Notice, SkeletonRows } from "../components/ui";
import { Mail as MailIcon, Plus, Spinner } from "../components/icons";

export function Mail() {
  const qc = useQueryClient();
  const mail = useQuery({ queryKey: ["mail"], queryFn: api.mail });
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [pwTarget, setPwTarget] = useState<string | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [pending, setPending] = useState(false);
  const [dialogError, setDialogError] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["mail"] });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    setCreating(true);
    api.createMail(email, password)
      .then(() => {
        setEmail("");
        setPassword("");
        refresh();
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setCreating(false));
  };

  const changePassword = (value: string) => {
    if (!pwTarget || !value) return;
    setPending(true);
    setDialogError("");
    api.mailPassword(pwTarget, value)
      .then(() => setPwTarget(null))
      .catch((err: Error) => setDialogError(err.message))
      .finally(() => setPending(false));
  };

  const doDelete = () => {
    if (!deleteTarget) return;
    setPending(true);
    setDialogError("");
    api.deleteMail(deleteTarget)
      .then(() => {
        setDeleteTarget(null);
        refresh();
      })
      .catch((err: Error) => setDialogError(err.message))
      .finally(() => setPending(false));
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Mail</h1>
          <p className="desc">Accounts on the mailserver container</p>
        </div>
      </div>

      {mail.data?.error && <Notice kind="err">{mail.data.error}</Notice>}
      {mail.isError && <Notice kind="err">{(mail.error as Error).message}</Notice>}
      {error && <Notice kind="err">{error}</Notice>}

      <form className="panel panel-pad" onSubmit={submit}>
        <h2 className="section-title">Create account</h2>
        <div className="form-grid" style={{ alignItems: "end" }}>
          <div className="field">
            <span className="label" id="lbl-email">Email address</span>
            <input className="input mono" style={{ fontSize: 12 }} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="user@domain" aria-labelledby="lbl-email" required />
          </div>
          <div className="field">
            <span className="label" id="lbl-pass">Password</span>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" aria-labelledby="lbl-pass" required />
          </div>
          <button className="btn btn-primary" disabled={creating}>
            {creating ? <Spinner /> : <Plus />}
            Add account
          </button>
        </div>
      </form>

      <div style={{ marginTop: 16 }}>
        {mail.isLoading ? (
          <SkeletonRows cols={[240, 200]} rows={3} />
        ) : (mail.data?.users ?? []).length === 0 ? (
          <div className="panel">
            <Empty icon={<MailIcon size={28} />} title="No mail accounts" hint="Create an account above to start sending and receiving mail." />
          </div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Address</th>
                  <th style={{ width: 220 }} aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {(mail.data?.users ?? []).map((user) => (
                  <tr key={user}>
                    <td className="mono" style={{ fontSize: 12.5 }}>{user}</td>
                    <td>
                      <span className="row" style={{ justifyContent: "flex-end" }}>
                        <button className="btn btn-sm" onClick={() => { setDialogError(""); setPwTarget(user); }}>
                          Password
                        </button>
                        <InlineConfirm label="Delete" onConfirm={() => { setPending(true); setDialogError(""); api.deleteMail(user).then(refresh).catch((err: Error) => setError(err.message)).finally(() => setPending(false)); }} />
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pwTarget !== null}
        title="Set a new password"
        body={pwTarget ? <>Set a new password for <strong>{pwTarget}</strong>.</> : ""}
        confirmLabel="Update password"
        input={{ type: "password", placeholder: "New password" }}
        pending={pending}
        error={dialogError}
        onConfirm={changePassword}
        onCancel={() => setPwTarget(null)}
      />
      <ConfirmDialog
        open={deleteTarget !== null}
        danger
        title="Delete mail account?"
        body={deleteTarget ? <>The account <strong>{deleteTarget}</strong> and its mail will be removed. This cannot be undone.</> : ""}
        confirmLabel="Delete account"
        pending={pending}
        error={dialogError}
        onConfirm={doDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  );
}