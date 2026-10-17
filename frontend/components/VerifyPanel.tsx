"use client";

import { useEffect, useState } from "react";
import { api, ApiError, fmtTime, Json, REASON_VI } from "../lib/api";
import { ProcessForm } from "./ProcessForm";

function Mark({ ok }: { ok: boolean }) {
  return <span className={ok ? "pass" : "fail"}>{ok ? "ĐẠT" : "KHÔNG ĐẠT"}</span>;
}

function RunHeader({ run }: { run: Json }) {
  return (
    <p className="muted">
      Lần chạy {run.run_id} · bắt đầu {fmtTime(run.started_at)} · kết thúc {fmtTime(run.finished_at)} ·{" "}
      {Math.round(run.duration_ms / 100) / 10}s · <b>{run.passed}/{run.total} đạt</b> · token {run.usage?.total_tokens ?? 0}
      {run.usage?.estimated_cost_usd != null ? ` · ước tính $${run.usage.estimated_cost_usd}` : ""}
      {run.error && <span className="error-box"> Lỗi: {run.error}</span>}
    </p>
  );
}

function CaseRuns({ run, escalationView }: { run: Json; escalationView: boolean }) {
  return (
    <>
      <RunHeader run={run} />
      <div className="tablewrap">
        <table>
          <thead>
            <tr><th>Ca</th><th>Email (rút gọn)</th><th>Kỳ vọng</th><th>Kết quả thực</th><th>{escalationView ? "Câu hỏi cụ thể / phản hồi" : "Câu hỏi hoặc phản hồi"}</th><th>Kiểm tra xác định</th><th>Đạt?</th></tr>
          </thead>
          <tbody>
            {run.results.map((r: Json) => (
              <tr key={r.case_id}>
                <td><b>{r.case_id}</b><br /><span className="muted">{fmtTime(r.finished_at)}</span></td>
                <td style={{ maxWidth: 220 }}>{r.email_short}</td>
                <td>{r.expected.decision}{r.expected.reason_primary ? <><br />{REASON_VI[r.expected.reason_primary]}</> : null}{r.expected.flags?.length ? <><br />{r.expected.flags.join(", ")}</> : null}</td>
                <td>
                  <b className={r.actual.decision === "AUTO" ? "pass" : ""}>{r.actual.decision === "ESCALATE" ? "CHUYỂN TIẾP" : r.actual.decision === "AUTO" ? "TỰ ĐỘNG" : r.actual.status}</b>
                  {r.actual.reason_primary && <><br />{REASON_VI[r.actual.reason_primary]}</>}
                  {r.actual.reasons?.length > 1 && <><br /><span className="muted">tất cả: {r.actual.reasons.join(", ")}</span></>}
                  {r.actual.flags?.length > 0 && <><br /><span className="fail">{r.actual.flags.join(", ")}</span></>}
                  {r.actual.error_code && <><br /><span className="fail">{r.actual.error_code}</span></>}
                  <br /><span className="muted">trích dẫn: {(r.actual.cites || []).join(", ") || "—"}</span>
                </td>
                <td style={{ maxWidth: 340, whiteSpace: "pre-wrap" }}>
                  {r.actual.decision === "ESCALATE" ? <b>{r.question}</b> : r.reply}
                  {r.manual_checklist?.length > 0 && (
                    <details><summary className="muted">Checklist duyệt tay (không tự chấm)</summary>
                      <ul>{r.manual_checklist.map((x: string, i: number) => <li key={i}>{x}</li>)}</ul>
                    </details>
                  )}
                </td>
                <td>
                  <ul style={{ margin: 0, paddingLeft: 16 }}>
                    {r.checks.map((c: Json) => (
                      <li key={c.check} className={c.ok ? "" : "fail"} title={c.detail}>{c.ok ? "✓" : "✗"} {c.check}<br /><span className="muted">{c.detail}</span></li>
                    ))}
                  </ul>
                </td>
                <td><Mark ok={r.passed} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Controls({ run }: { run: Json }) {
  return (
    <>
      <RunHeader run={run} />
      <div className="tablewrap">
        <table>
          <thead><tr><th>#</th><th>Kiểm tra</th><th>Bằng chứng (đếm dòng trong DB)</th><th>Mode</th><th>Đạt?</th></tr></thead>
          <tbody>
            {run.results.map((r: Json) => (
              <tr key={r.no}><td>{r.no}</td><td>{r.check}</td><td>{r.evidence}</td><td className="muted">{r.mode}</td><td><Mark ok={r.passed} /></td></tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

const KIND_TITLE: Record<string, string> = {
  general: "Bảng chính — 4 ca nghiệp vụ",
  escalation: "Escalation Verify — 5 ca",
  controls: "Bảng kiểm tra điều khiển (không tính vào 4 ca)",
};
const KIND_RUNNING: Record<string, string> = {
  general: "Đang chạy 4 ca qua AI thật…",
  escalation: "Đang chạy 5 ca qua AI thật…",
  controls: "Đang chạy 8 kiểm tra điều khiển…",
};

function RunBody({ kind, run }: { kind: string; run: Json }) {
  if (kind === "controls") return <Controls run={run} />;
  return (
    <>
      {kind === "escalation" && (
        <p>Chuyển tiếp: <b>{run.results.filter((r: Json) => r.actual.decision === "ESCALATE").map((r: Json) => r.case_id).join(", ") || "không có"}</b> · Tự động: <b>{run.results.filter((r: Json) => r.actual.decision === "AUTO").map((r: Json) => r.case_id).join(", ") || "không có"}</b></p>
      )}
      <CaseRuns run={run} escalationView={kind === "escalation"} />
    </>
  );
}

/** Bảng kết quả bật lên ở đáy màn hình ngay khi bấm Verify; đóng bằng nút hoặc phím Esc. */
function ResultSheet({ kind, run, busy, err, onClose }: { kind: string; run?: Json; busy: boolean; err: string | null; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && !busy) onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [busy, onClose]);
  return (
    <div className="sheet-backdrop" onClick={() => { if (!busy) onClose(); }}>
      <div className="sheet" role="dialog" aria-modal="true" aria-label={KIND_TITLE[kind]} onClick={(e) => e.stopPropagation()}>
        <div className="sheet-head">
          <h3 style={{ margin: 0 }}>{KIND_TITLE[kind]}</h3>
          {run && !busy && <span className={run.passed === run.total ? "pass" : "fail"}>{run.passed}/{run.total} đạt</span>}
          <button className="secondary" disabled={busy} onClick={onClose}>Đóng</button>
        </div>
        <div className="sheet-body">
          {busy && <p>{KIND_RUNNING[kind]} Vui lòng chờ, kết quả sẽ hiện ở đây.</p>}
          {!busy && err && <p className="error-box">{err}</p>}
          {!busy && run && <RunBody kind={kind} run={run} />}
        </div>
      </div>
    </div>
  );
}

export function VerifyPanel({ onOpen }: { onOpen?: (id: string) => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [runs, setRuns] = useState<Record<string, Json>>({});
  const [err, setErr] = useState<string | null>(null);
  const [sheet, setSheet] = useState<string | null>(null);

  async function run(kind: string) {
    setBusy(kind);
    setErr(null);
    setSheet(kind);
    try {
      const r = await api<Json>(`/api/verify/${kind}`, { method: "POST" });
      setRuns((x) => ({ ...x, [kind]: r }));
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <div className="card">
        <h2>Verify — một lần bấm</h2>
        <p className="muted">Chạy đúng đường nghiệp vụ thật (cùng dịch vụ, cùng AI, cùng bộ quy tắc, cùng cơ sở dữ liệu). Không có kết quả dựng sẵn. Mỗi ca mất vài giây vì gọi AI thật. Kết quả bật lên ở cuối màn hình.</p>
        <div className="row">
          <button disabled={!!busy} onClick={() => run("general")}>{busy === "general" ? "Đang chạy 4 ca…" : "Chạy Verify (4 ca)"}</button>
          <button disabled={!!busy} onClick={() => run("escalation")}>{busy === "escalation" ? "Đang chạy 5 ca…" : "Escalation Verify (5 ca)"}</button>
          <button className="secondary" disabled={!!busy} onClick={() => run("controls")}>{busy === "controls" ? "Đang chạy…" : "Kiểm tra điều khiển"}</button>
        </div>
        {Object.keys(runs).length > 0 && (
          <div style={{ marginTop: 10 }}>
            <div className="section-label">Kết quả gần nhất (bấm để xem lại)</div>
            <div className="row">
              {(["general", "escalation", "controls"] as const).filter((k) => runs[k]).map((k) => (
                <button key={k} className="linklike" onClick={() => { setErr(null); setSheet(k); }}>
                  {KIND_TITLE[k]}: {runs[k].passed}/{runs[k].total} đạt · {fmtTime(runs[k].finished_at)}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <ProcessForm onOpen={onOpen} />
      {sheet && <ResultSheet kind={sheet} run={runs[sheet]} busy={busy === sheet} err={busy ? null : err} onClose={() => setSheet(null)} />}
    </>
  );
}
