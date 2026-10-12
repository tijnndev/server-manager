import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api";
import { Empty, Notice, Pill, SkeletonRows } from "../components/ui";
import { Pulse, Search } from "../components/icons";
import { fullTime, timeAgo } from "../lib/format";

export function Activity() {
  const rows = useQuery({ queryKey: ["activity"], queryFn: api.activity });
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const data = rows.data ?? [];
    const q = search.trim().toLowerCase();
    if (!q) return data;
    return data.filter(
      (r) =>
        r.username.toLowerCase().includes(q) ||
        r.stack.toLowerCase().includes(q) ||
        r.action.toLowerCase().includes(q) ||
        r.detail.toLowerCase().includes(q),
    );
  }, [rows.data, search]);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Activity</h1>
          <p className="desc">Actions taken on stacks, templates and the host</p>
        </div>
        <div className="row actions">
          <div className="search">
            <Search />
            <input
              className="input"
              style={{ width: 240 }}
              placeholder="Search activity…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              aria-label="Search activity"
            />
          </div>
        </div>
      </div>

      {rows.isError && <Notice kind="err">{(rows.error as Error).message}</Notice>}

      {rows.isLoading ? (
        <SkeletonRows cols={[130, 110, 110, 120, 320]} />
      ) : filtered.length === 0 ? (
        <div className="panel">
          <Empty icon={<Pulse size={28} />} title={search ? "No matching activity" : "No activity yet"} hint={search ? "Try a different search." : "Actions will appear here as they happen."} />
        </div>
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th style={{ width: 120 }}>When</th>
                <th style={{ width: 120 }}>User</th>
                <th style={{ width: 130 }}>Stack</th>
                <th style={{ width: 130 }}>Action</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => (
                <tr key={row.id}>
                  <td title={fullTime(row.createdAt)} className="dim" style={{ whiteSpace: "nowrap", fontSize: 12.5 }}>
                    {timeAgo(row.createdAt)}
                  </td>
                  <td>{row.username || "system"}</td>
                  <td className="mono" style={{ fontSize: 12.5 }}>{row.stack}</td>
                  <td>
                    <Pill tone="info">{row.action}</Pill>
                  </td>
                  <td className="muted" style={{ fontSize: 12.5 }}>{row.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}