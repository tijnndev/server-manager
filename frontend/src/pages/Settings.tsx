import { FormEvent, useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { Empty, Notice, Pill, SkeletonRows } from "../components/ui";
import { Plus, Sliders, Spinner, Users } from "../components/icons";

export function Settings() {
  const qc = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: api.settings });
  const users = useQuery({ queryKey: ["users"], queryFn: api.users });
  const [discordWebhook, setDiscord] = useState("");
  const [cloudflareToken, setToken] = useState("");
  const [publicIP, setIP] = useState("");
  const [acmeEmail, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("user");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [userError, setUserError] = useState("");
  const [creatingUser, setCreatingUser] = useState(false);

  useEffect(() => {
    if (!settings.data) return;
    setDiscord(settings.data.discordWebhook);
    setToken(settings.data.cloudflareToken);
    setIP(settings.data.publicIP);
    setEmail(settings.data.acmeEmail);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: () =>
      api.saveSettings({ discordWebhook, cloudflareToken, publicIP, acmeEmail }),
    onSuccess: () => {
      setError("");
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["settings"] });
      window.setTimeout(() => setSaved(false), 2500);
    },
    onError: (err: Error) => setError(err.message),
  });

  const createUser = (e: FormEvent) => {
    e.preventDefault();
    setUserError("");
    setCreatingUser(true);
    api.createUser(username, password, role)
      .then(() => {
        setUsername("");
        setPassword("");
        qc.invalidateQueries({ queryKey: ["users"] });
      })
      .catch((err: Error) => setUserError(err.message))
      .finally(() => setCreatingUser(false));
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Settings</h1>
          <p className="desc">Integrations, certificates and panel users</p>
        </div>
      </div>

      {settings.isError && <Notice kind="err">{(settings.error as Error).message}</Notice>}

      <form
        className="panel panel-pad"
        onSubmit={(e: FormEvent) => {
          e.preventDefault();
          setError("");
          save.mutate();
        }}
      >
        <h2 className="section-title">Integrations</h2>
        <div className="form-grid">
          <div className="field">
            <span className="label" id="lbl-discord">Discord webhook</span>
            <input className="input mono" style={{ fontSize: 12 }} value={discordWebhook} onChange={(e) => setDiscord(e.target.value)} placeholder="https://discord.com/api/webhooks/…" aria-labelledby="lbl-discord" />
            <span className="hint">Deployment and lifecycle notifications</span>
          </div>
          <div className="field">
            <span className="label" id="lbl-cf">Cloudflare token</span>
            <input className="input mono" style={{ fontSize: 12 }} value={cloudflareToken} onChange={(e) => setToken(e.target.value)} placeholder="API token" aria-labelledby="lbl-cf" />
            <span className="hint">Used to create DNS records when publishing domains</span>
          </div>
          <div className="field">
            <span className="label" id="lbl-ip">Public IP</span>
            <input className="input mono" style={{ fontSize: 12 }} value={publicIP} onChange={(e) => setIP(e.target.value)} placeholder="203.0.113.10" aria-labelledby="lbl-ip" />
            <span className="hint">Used for Cloudflare A records</span>
          </div>
          <div className="field">
            <span className="label" id="lbl-acme">ACME email</span>
            <input className="input" value={acmeEmail} onChange={(e) => setEmail(e.target.value)} placeholder="certificates@example.com" aria-labelledby="lbl-acme" />
            <span className="hint">Contact address for TLS certificate issuance</span>
          </div>
        </div>
        {error && <Notice kind="err">{error}</Notice>}
        {saved && <Notice kind="ok">Settings saved.</Notice>}
        <div className="row" style={{ justifyContent: "flex-end", marginTop: 12 }}>
          <button className="btn btn-primary" disabled={save.isPending}>
            {save.isPending && <Spinner />}
            Save settings
          </button>
        </div>
      </form>

      <h2 className="section-title" style={{ marginTop: 26 }}>
        <span className="row" style={{ gap: 7 }}>
          <Users size={15} className="ico" />
          Users
        </span>
      </h2>

      {users.isLoading ? (
        <SkeletonRows cols={[200, 110]} rows={2} />
      ) : (users.data ?? []).length === 0 ? (
        <div className="panel">
          <Empty icon={<Sliders size={28} />} title="No users" hint="Panel users can be granted access to stacks." />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Username</th>
                <th style={{ width: 130 }}>Role</th>
              </tr>
            </thead>
            <tbody>
              {(users.data ?? []).map((user) => (
                <tr key={user.id}>
                  <td>{user.username}</td>
                  <td>
                    <Pill tone={user.role === "admin" ? "info" : "off"}>{user.role}</Pill>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <form className="panel panel-pad" style={{ marginTop: 14 }} onSubmit={createUser}>
        <h2 className="section-title">Add user</h2>
        <div className="form-grid" style={{ alignItems: "end" }}>
          <div className="field">
            <span className="label" id="lbl-username">Username</span>
            <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} placeholder="username" aria-labelledby="lbl-username" required />
          </div>
          <div className="field">
            <span className="label" id="lbl-password">Password</span>
            <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Password" aria-labelledby="lbl-password" required />
          </div>
          <div className="field">
            <span className="label" id="lbl-role">Role</span>
            <select className="select" value={role} onChange={(e) => setRole(e.target.value)} aria-labelledby="lbl-role">
              <option value="user">user</option>
              <option value="admin">admin</option>
            </select>
          </div>
          <button className="btn" disabled={creatingUser}>
            {creatingUser ? <Spinner /> : <Plus />}
            Add user
          </button>
        </div>
        {userError && <Notice kind="err">{userError}</Notice>}
      </form>
    </div>
  );
}