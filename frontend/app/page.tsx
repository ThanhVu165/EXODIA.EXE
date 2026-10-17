"use client";

import { useCallback, useEffect, useState } from "react";
import { AuditTable, CaseDetail, DecisionBadge, OutboxTable } from "../components/CaseView";
import { ProcessForm } from "../components/ProcessForm";
import { SatisfactionPanel } from "../components/SatisfactionPanel";
import { VerifyPanel } from "../components/VerifyPanel";
import { api, ApiError, fmtTime, Json, REASON_VI, STATUS_VI } from "../lib/api";

const TABS = [
  ["xu-ly", "Xử lý email"],
  ["hang-cho", "Hàng chờ nhân viên DSA"],
  ["outbox", "Outbox"],
  ["verify", "Verify"],
  ["danh-gia", "Đánh giá phản hồi (dự đoán)"],
  ["audit", "Nhật ký kiểm toán"],
] as const;

function useHashTab(): [string, (t: string) => void] {
  const [tab, setTab] = useState("xu-ly");
  useEffect(() => {
    const read = () => setTab((location.hash.replace("#", "").split("/")[0]) || "xu-ly");
    read();
    window.addEventListener("hashchange", read);
    return () => window.removeEventListener("hashchange", read);
  }, []);
  return [tab, (t: string) => { location.hash = t; }];
}

function PauseSwitch() {
  const [sys, setSys] = useState<Json | null>(null);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    try { setSys(await api("/api/system")); } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { void load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  async function toggle() {
    setBusy(true); setErr(null);
    try {
      const r = await api<Json>("/api/system/pause", { body: { on: !sys?.paused, reason } });
      setReason("");
      if (r.cancelled?.length) setErr(`Đã hủy ${r.cancelled.length} ca đang chạy dở.`);
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally { setBusy(false); }
  }
  if (!sys) return <span className="muted">{err || "…"}</span>;
  return (
    <div className="row">
      <span className={`badge ${sys.paused ? "b-ERROR" : "b-AUTO"}`}>{sys.paused ? "ĐANG TẠM DỪNG" : "Đang chạy tự động"}</span>
      <input type="text" style={{ width: 200 }} placeholder="Lý do (bắt buộc)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <button className={sys.paused ? "" : "danger"} disabled={busy} onClick={toggle}>{sys.paused ? "Mở lại" : "Dừng hệ thống (Stop)"}</button>
      <span className="muted">AI hôm nay: {sys.budget.public_used}/{sys.budget.public_cap} · Verify {sys.budget.verify_used}/{sys.budget.verify_cap} · Chấm {sys.budget.eval_used}/{sys.budget.eval_cap}</span>
      {err && <span className="muted">{err}</span>}
    </div>
  );
}

function CaseList({ view, onOpen }: { view: string; onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<Json[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = useCallback(async () => {
    try { setRows((await api<Json>(`/api/cases?view=${view}`)).cases); } catch (e) { setErr((e as Error).message); }
  }, [view]);
  useEffect(() => { void load(); }, [load]);
  if (err) return <p className="error-box">{err}</p>;
  if (!rows) return <p>Đang tải…</p>;
  if (!rows.length) return <p className="muted">Không có ca nào.</p>;
  return (
    <div className="tablewrap">
      <table>
        <thead><tr><th>Thời điểm</th><th>Quyết định</th><th>Lý do chính / lỗi</th><th>Email</th><th></th></tr></thead>
        <tbody>
          {rows.map((c) => (
            <tr key={c.id}>
              <td>{fmtTime(c.created_at)}</td>
              <td><DecisionBadge c={c} /><br /><span className="muted">{STATUS_VI[c.status]}</span></td>
              <td>{c.error_code || REASON_VI[c.reason_primary] || "—"}{c.flags?.length ? <><br /><span className="fail">{c.flags.join(", ")}</span></> : null}</td>
              <td style={{ maxWidth: 380 }}>{String(c.email_body).slice(0, 160)}</td>
              <td><button className="secondary" onClick={() => onOpen(c.id)}>Mở</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      <button className="secondary" onClick={load} style={{ marginTop: 8 }}>Tải lại</button>
    </div>
  );
}

function OutboxTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<Json[] | null>(null);
  useEffect(() => { api<Json>("/api/outbox").then((d) => setRows(d.outbox)).catch(() => setRows([])); }, []);
  if (!rows) return <p>Đang tải…</p>;
  return <OutboxTable rows={rows} onOpen={onOpen} />;
}

function AuditTab({ onOpen }: { onOpen: (id: string) => void }) {
  const [rows, setRows] = useState<Json[] | null>(null);
  useEffect(() => { api<Json>("/api/audit").then((d) => setRows(d.audit)).catch(() => setRows([])); }, []);
  if (!rows) return <p>Đang tải…</p>;
  const caseIds = Array.from(new Set(rows.filter((r) => r.case_id).map((r) => r.case_id))).slice(0, 20);
  return (
    <>
      <p>Chọn một ca để xem đầy đủ chuỗi hành động:{" "}
        {caseIds.map((id) => <button key={id} className="linklike" style={{ marginRight: 8 }} onClick={() => onOpen(id)}>{String(id).slice(0, 8)}</button>)}
      </p>
      <AuditTable rows={rows} />
    </>
  );
}

export default function Home() {
  const [tab, setTab] = useHashTab();
  const [openId, setOpenId] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const open = (id: string) => setOpenId(id);

  return (
    <>
      <div className="banner" role="note">
        Bản demo/sandbox, dữ liệu giả lập, không phải hệ thống chính thức của UEH. Không gửi email thật: “gửi” = ghi vào Outbox.
      </div>
      <header className="top">
        <h1>DSA Intelligence</h1>
        <PauseSwitch />
      </header>
      <div className="hint">
        Dán một email của sinh viên vào ô bên dưới rồi bấm <b>Xử lý</b> — hoặc bấm <a href="#verify"><b>Verify</b></a> để chạy bộ kiểm thử.
      </div>
      <nav className="tabs">
        {TABS.map(([id, label]) => (
          <a key={id} href={`#${id}`} className={tab === id ? "active" : ""} onClick={() => setOpenId(null)}>{label}</a>
        ))}
      </nav>
      <main>
        {openId && (
          <div className="card">
            <div className="row" style={{ justifyContent: "space-between" }}>
              <h2 style={{ margin: 0 }}>Chi tiết ca</h2>
              <button className="secondary" onClick={() => setOpenId(null)}>Đóng</button>
            </div>
            <CaseDetail key={openId + refresh} caseId={openId} onChanged={() => setRefresh((x) => x + 1)} />
          </div>
        )}
        {tab === "xu-ly" && <ProcessForm onOpen={open} />}
        {tab === "hang-cho" && <div className="card"><h2>Hàng chờ nhân viên DSA</h2><p className="muted">Ca chờ người quyết định và ca lỗi kỹ thuật. Dữ liệu Verify không hiển thị ở đây.</p><CaseList key={refresh} view="queue" onOpen={open} /></div>}
        {tab === "outbox" && <div className="card"><h2>Outbox</h2><OutboxTab onOpen={open} /></div>}
        {tab === "verify" && <VerifyPanel onOpen={open} />}
        {tab === "danh-gia" && <SatisfactionPanel onOpen={open} />}
        {tab === "audit" && <div className="card"><h2>Nhật ký kiểm toán</h2><AuditTab onOpen={open} /></div>}
      </main>
    </>
  );
}
