"use client";

import { useState } from "react";
import { api, ApiError, fmtTime, Json, REASON_VI, STATUS_VI } from "../lib/api";

function vnToday(): string {
  return new Date(Date.now() + 7 * 3600 * 1000).toISOString().slice(0, 10);
}

const SLA_VI: Record<string, string> = { OVERDUE: "Quá hạn", NEAR_DUE: "Gần hạn (≤ 24 giờ)", ON_TRACK: "Trong hạn" };

function Stat({ label, value, note }: { label: string; value: number | string; note?: string }) {
  return (
    <div style={{ minWidth: 140 }}>
      <div className="section-label">{label}</div>
      <h2 style={{ margin: 0 }}>{value}</h2>
      {note && <div className="muted">{note}</div>}
    </div>
  );
}

function CaseTable({ rows, onOpen }: { rows: Json[]; onOpen?: (id: string) => void }) {
  if (!rows.length) return <p className="muted">Không có ca nào.</p>;
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr><th>Mã ca</th><th>SLA</th><th>Nhận / Hạn</th><th>Trạng thái hiện tại</th><th>Hoạt động gần nhất</th><th>Tuyến tiếp quản</th><th>Nguyên nhân chậm (bằng chứng)</th></tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.case_id}>
              <td>
                {onOpen ? <button className="linklike" onClick={() => onOpen(r.case_id)}>{String(r.case_id).slice(0, 8)}</button> : String(r.case_id).slice(0, 8)}
                {r.source === "DEMO_SEED" && <><br /><span className="badge b-OTHER">demo giả lập</span></>}
                <br /><span className="muted">{r.email_short}</span>
              </td>
              <td className={r.sla_state === "OVERDUE" ? "fail" : r.sla_state === "NEAR_DUE" ? "" : "pass"}>
                {SLA_VI[r.sla_state]}<br /><span className="muted">{r.hours_remaining >= 0 ? `còn ${r.hours_remaining} giờ` : `quá ${-r.hours_remaining} giờ`}</span>
              </td>
              <td>{fmtTime(r.received_at)}<br /><b>{fmtTime(r.due_at)}</b></td>
              <td>{STATUS_VI[r.current_status] || r.current_status}{r.reason_primary ? <><br /><span className="muted">{REASON_VI[r.reason_primary]}</span></> : null}{r.flags?.length ? <><br /><span className="muted">{r.flags.join(", ")}</span></> : null}</td>
              <td>{r.last_activity?.action || "—"}<br /><span className="muted">{fmtTime(r.last_activity?.at)} · {r.last_activity?.actor}{r.last_activity?.actor_name ? ` (${r.last_activity.actor_name})` : ""}</span></td>
              <td>{r.handling_route}</td>
              <td>{r.delay.cause}{r.delay.evidence ? <><br /><span className="muted">{r.delay.evidence}</span></> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function OpsReportPanel({ onOpen }: { onOpen?: (id: string) => void }) {
  const [day, setDay] = useState(vnToday());
  const [includeDemo, setIncludeDemo] = useState(false);
  const [rep, setRep] = useState<Json | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const [ai, setAi] = useState<Json | null>(null);
  const [aiErr, setAiErr] = useState<string | null>(null);
  const [aiBusy, setAiBusy] = useState(false);

  async function generate() {
    setBusy(true); setErr(null); setAi(null); setAiErr(null);
    try { setRep(await api(`/api/reports/operations?day=${day}&include_demo=${includeDemo}`)); }
    catch (e) { setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)); }
    finally { setBusy(false); }
  }

  async function summarize() {
    setAiBusy(true); setAiErr(null);
    try { setAi(await api("/api/reports/operations/summary", { body: { day, include_demo: includeDemo } })); }
    catch (e) { setAiErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)); }
    finally { setAiBusy(false); }
  }

  const c = rep?.counts;
  return (
    <>
      <div className="card">
        <h2>Báo cáo vận hành</h2>
        <div className="row">
          <label>Ngày (giờ Việt Nam) <input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
          <label><input type="checkbox" checked={includeDemo} onChange={(e) => setIncludeDemo(e.target.checked)} /> Bao gồm dữ liệu demo giả lập (có nhãn)</label>
          <button disabled={busy} onClick={generate}>{busy ? "Đang tạo…" : "Tạo báo cáo"}</button>
        </div>
        {err && <p className="error-box">{err}</p>}
      </div>

      {rep && (
        <>
          <div className="card">
            <p className="banner" style={{ borderRadius: 6 }}>{rep.sla_note}</p>
            <div className="row" style={{ gap: 24 }}>
              <Stat label="Ca mới trong ngày" value={c.new} />
              <Stat label="Hoàn tất luồng phản hồi" value={c.completed_reply_flow} note={`đúng hạn ${c.completed_on_time} · trễ ${c.completed_late}`} />
              <Stat label="Còn mở (tại thời điểm tham chiếu)" value={c.open_at_reference} note={`quá hạn ${c.open_overdue} · gần hạn ${c.open_near_due} · lỗi kỹ thuật ${c.open_error}`} />
              <Stat label="Đã hủy (thống kê riêng)" value={c.cancelled} />
            </div>
            <p className="muted">{rep.completion_definition} {rep.excluded}. Thời điểm tham chiếu: {fmtTime(rep.reference_time)}. Tạo lúc {fmtTime(rep.generated_at)}. Số liệu do backend tính.</p>
          </div>

          <div className="card">
            <h3>Cần xử lý: gần hạn / quá hạn ({rep.attention.length})</h3>
            <CaseTable rows={rep.attention} onOpen={onOpen} />
            <p><button className="linklike" onClick={() => setShowAll((x) => !x)}>{showAll ? "Ẩn" : "Xem"} tất cả {rep.open_cases.length} ca còn mở</button></p>
            {showAll && <CaseTable rows={rep.open_cases} onOpen={onOpen} />}
          </div>

          <div className="card">
            <h3>Tóm tắt bằng AI (tùy chọn)</h3>
            <p className="muted">AI chỉ đọc số liệu và danh sách ở trên để tóm tắt và gợi ý thứ tự ưu tiên. AI không tính số, không thực hiện hành động. Nếu AI lỗi, bảng số liệu vẫn dùng bình thường.</p>
            <button className="secondary" disabled={aiBusy} onClick={summarize}>{aiBusy ? "Đang tóm tắt…" : "Tóm tắt bằng AI"}</button>
            {aiErr && <p className="error-box">AI không khả dụng: {aiErr}</p>}
            {ai && (
              <div style={{ marginTop: 8 }}>
                <p>{ai.summary}</p>
                {ai.priorities?.length > 0 && (
                  <ol>{ai.priorities.map((p: Json, i: number) => (
                    <li key={i}>{onOpen ? <button className="linklike" onClick={() => onOpen(p.case_id)}>{String(p.case_id).slice(0, 8)}</button> : p.case_id}: {p.why}</li>
                  ))}</ol>
                )}
                {ai.dropped_refs?.length > 0 && <p className="muted">Đã bỏ {ai.dropped_refs.length} gợi ý tham chiếu mã ca không có trong báo cáo.</p>}
                <p className="muted">Model {ai.model_id || "—"} · nội dung do AI tạo, đối chiếu với bảng số liệu.</p>
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
