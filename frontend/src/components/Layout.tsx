import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Layers, LogOut, Mail, PanelLeft, Pulse, Server, FileCode, Sliders } from "./icons";

const STORE_KEY = "sm.sidebar.collapsed";

function NavItem({
  to,
  icon,
  label,
  end,
  collapsed,
}: {
  to: string;
  icon: React.ReactNode;
  label: string;
  end?: boolean;
  collapsed: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
      data-tip={collapsed ? label : undefined}
    >
      <span className="nav-ico">{icon}</span>
      <span className="nav-txt">{label}</span>
    </NavLink>
  );
}

export function Layout() {
  const me = useQuery({ queryKey: ["me"], queryFn: api.me });
  const nav = useNavigate();
  const [collapsed, setCollapsed] = useState(() => {
    const stored = localStorage.getItem(STORE_KEY);
    if (stored !== null) return stored === "1";
    return window.innerWidth < 1000;
  });

  useEffect(() => {
    localStorage.setItem(STORE_KEY, collapsed ? "1" : "0");
  }, [collapsed]);

  const toggle = () => setCollapsed((v) => !v);
  const logout = () => api.logout().finally(() => nav("/login"));

  const initials = (me.data?.username ?? "?").slice(0, 2).toUpperCase();

  return (
    <div className={`app${collapsed ? " collapsed" : ""}`}>
      <aside className="side" aria-label="Primary navigation">
        <div className="side-head">
          <span className="nav-ico" style={{ color: "var(--accent)" }}>
            <Server size={19} />
          </span>
          <span className="brand-name">Server Manager</span>
          <button
            type="button"
            className="icon-btn collapse-btn"
            onClick={toggle}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            data-tip={collapsed ? "Expand sidebar" : undefined}
          >
            <PanelLeft size={15} />
          </button>
        </div>

        <div className="nav-label">Operate</div>
        <NavItem to="/" end icon={<Layers size={16} />} label="Stacks" collapsed={collapsed} />
        <NavItem to="/activity" icon={<Pulse size={16} />} label="Activity" collapsed={collapsed} />

        <div className="nav-label">Configure</div>
        <NavItem to="/templates" icon={<FileCode size={16} />} label="Templates" collapsed={collapsed} />
        <NavItem to="/mail" icon={<Mail size={16} />} label="Mail" collapsed={collapsed} />
        {me.data?.role === "admin" && (
          <NavItem to="/settings" icon={<Sliders size={16} />} label="Settings" collapsed={collapsed} />
        )}

        <div className="side-foot">
          <div className="user-chip" data-tip={collapsed ? me.data?.username : undefined}>
            <span className="avatar" aria-hidden="true">
              {initials}
            </span>
            <span className="who">
              <span className="name">{me.data?.username ?? "—"}</span>
              <span className="role">{me.data?.role ?? ""}</span>
            </span>
          </div>
          <button
            type="button"
            className={`icon-btn icon-btn-sm`}
            onClick={logout}
            aria-label="Log out"
            data-tip={collapsed ? "Log out" : undefined}
          >
            <LogOut size={15} />
          </button>
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
    </div>
  );
}