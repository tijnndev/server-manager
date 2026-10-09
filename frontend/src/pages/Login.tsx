import { FormEvent, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Navigate } from "react-router-dom";
import { api } from "../api";
import { Notice } from "../components/ui";
import { Server, Spinner } from "../components/icons";

export function Login() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  const qc = useQueryClient();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const login = useMutation({
    mutationFn: () => api.login(username, password),
    onSuccess: (user) => {
      qc.setQueryData(["me"], user);
    },
    onError: (err: Error) => setError(err.message),
  });
  if (me.data) return <Navigate to="/" replace />;
  const submit = (e: FormEvent) => {
    e.preventDefault();
    setError("");
    login.mutate();
  };
  return (
    <div className="login">
      <form className="card" onSubmit={submit}>
        <div className="brand">
          <span className="nav-ico" style={{ color: "var(--accent)" }}>
            <Server size={26} />
          </span>
          <span className="name">Server Manager</span>
          <span className="sub">Sign in to manage your infrastructure</span>
        </div>
        <div className="field">
          <span className="label" id="lbl-user">Username</span>
          <input className="input" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" aria-labelledby="lbl-user" required />
        </div>
        <div className="field">
          <span className="label" id="lbl-pass">Password</span>
          <input className="input" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" aria-labelledby="lbl-pass" required />
        </div>
        {error && <Notice kind="err">{error}</Notice>}
        <button className="btn btn-primary" style={{ width: "100%", height: 36 }} disabled={login.isPending}>
          {login.isPending && <Spinner />}
          Log in
        </button>
      </form>
    </div>
  );
}

export function Guard({ children }: { children: React.ReactNode }) {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me, retry: false });
  if (me.isLoading) {
    return (
      <div className="login">
        <span className="muted row" style={{ gap: 8 }}>
          <Spinner size={16} />
          Loading
        </span>
      </div>
    );
  }
  if (me.isError) return <Navigate to="/login" replace />;
  return children;
}