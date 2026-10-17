"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, FLAG_VI, fmtTime, Json, newKey, REASON_VI, STATUS_VI } from "../lib/api";

export function DecisionBadge({ c }: { c: Json }) {
  const kind = c.status === "ERROR" ? "ERROR" : c.decision === "AUTO" ? "AUTO" : c.decision === "ESCALATE" ? "ESCALATE" : "OTHER";
  const label = c.status === "ERROR" ? "LỖI KỸ THUẬT" : c.decision === "AUTO" ? "TỰ ĐỘNG TRẢ LỜI" : c.decision === "ESCALATE" ? "CHUYỂN NHÂN VIÊN DSA" : STATUS_VI[c.status] || c.status;
  return <span className={`badge b-${kind}`}>{label}</span>;
}

/** Kết quả xử lý + gói quyết định. Tách rõ "Sinh viên nói (chưa xác minh)" và "Căn cứ quy chế". */
export function CaseSummary({ c, outbox }: { c: Json; outbox?: Json[] }) {
  const p: Json = c.package || {};
  const sent = (outbox || []).filter((o) => o.status === "SENT");
  return (
    <div>
      <div className="row">
        <DecisionBadge c={c} />
        <span className="muted">Trạng thái: {STATUS_VI[c.status] || c.status}</span>
        {(c.flags || []).map((f: string) => (
          <span key={f} className="badge flag">{FLAG_VI[f] || f}</span>
        ))}
      </div>

      {c.status === "ERROR" && (
        <p className="error-box">
          Lỗi kỹ thuật <b>{c.error_code}</b>: {c.error_detail}. Không có phản hồi nào được gửi. Có thể thử lại với cùng khóa.
        </p>
      )}

      {c.reasons?.length > 0 && (
        <>
          <div className="section-label">Lý do chuyển tiếp</div>
          <ul>
            {c.reasons.map((r: string) => (
              <li key={r}>
                {r === c.reason_primary ? <b>{REASON_VI[r] || r} (lý do chính)</b> : REASON_VI[r] || r}
              </li>
            ))}
          </ul>
        </>
      )}

      {(p.gate_explanation || p.plain_explanation) && (
        <>
          <div className="section-label">Giải thích cho người không chuyên</div>
          {p.gate_explanation && <p>{p.gate_explanation}</p>}
          {p.plain_explanation && <p className="muted">Trợ lý AI: {p.plain_explanation}</p>}
        </>
      )}

      {p.handoff_question && (
        <>
          <div className="section-label">Câu hỏi cho nhân viên DSA {p.question_source === "gate" ? "(do bộ quy tắc soạn)" : ""}</div>
          <div className="question">{p.handoff_question}</div>
          {p.suggested_route_label && <p className="muted">Tuyến chuyển tiếp gợi ý: {p.suggested_route_label}</p>}
        </>
      )}

      {sent.length > 0 && (
        <>
          <div className="section-label">Phản hồi đã ghi vào outbox (không gửi email thật)</div>
          {sent.map((o) => (
            <div key={o.id} className="reply">{o.body}</div>
          ))}
        </>
      )}
      {!sent.length && p.suggested_reply && c.decision === "ESCALATE" && (
        <>
          <div className="section-label">Bản nháp gợi ý cho nhân viên (chưa gửi)</div>
          <div className="reply">{p.suggested_reply}</div>
        </>
      )}
      {p.suggested_reply_blocked && <p className="muted">Bản nháp bị chặn vì email bị gắn cờ nghi vấn.</p>}

      {p.student_said_unverified?.length > 0 && (
        <>
          <div className="section-label">Sinh viên nói (chưa xác minh)</div>
          <div className="unverified">
            <ul style={{ margin: 0 }}>
              {p.student_said_unverified.map((s: string, i: number) => <li key={i}>{s}</li>)}
            </ul>
          </div>
        </>
      )}
      {p.unknown_facts?.length > 0 && (
        <>
          <div className="section-label">Dữ kiện chưa biết</div>
          <ul>{p.unknown_facts.map((s: string, i: number) => <li key={i}>{s}</li>)}</ul>
        </>
      )}
      {p.verified_from_policy?.length > 0 && (
        <>
          <div className="section-label">Căn cứ quy chế (trích nguyên văn bằng code theo mã điều khoản)</div>
          {p.verified_from_policy.map((x: Json) => (
            <div key={x.id} className={`policy ${x.is_gap ? "gap" : ""}`}>
              <b>{x.id}</b> — {x.locator}
              {x.is_gap && <div><b>Khoảng trống:</b> {x.gap_description}</div>}
              <div>{x.is_gap ? "Văn bản nhắc tới: " : ""}“{x.text}”</div>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

export function AuditTable({ rows }: { rows: Json[] }) {
  return (
    <div className="tablewrap">
      <table>
        <thead>
          <tr><th>Thời điểm</th><th>Tác nhân</th><th>Hành động</th><th>Trạng thái</th><th>Lý do</th><th>Căn cứ</th><th>Đầu vào / khóa / model / chính sách</th></tr>
        </thead>
        <tbody>
          {rows.map((a) => (
            <tr key={a.id}>
              <td>{fmtTime(a.at)}</td>
              <td>{a.actor}{a.actor_name ? ` (${a.actor_name})` : ""}</td>
              <td>{a.action}</td>
              <td>{a.status_before || "—"} → {a.status_after || "—"}</td>
              <td>{a.reason || "—"}</td>
              <td>{(a.clause_ids || []).join(", ") || "—"}</td>
              <td className="muted">
                {a.input_ref || "—"}<br />key: {a.idempotency_key || "—"}<br />model: {a.model_id || "—"}<br />
                policy: {(a.policy_version || "").slice(0, 12)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Chi tiết ca + thao tác của nhân viên (Trả lời / Override / Hủy / Thử lại) + audit đầy đủ. */
export function CaseDetail({ caseId, onChanged }: { caseId: string; onChanged?: () => void }) {
  const [data, setData] = useState<Json | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [name, setName] = useState("");

  const load = useCallback(async () => {
    try {
      setData(await api(`/api/cases/${caseId}`));
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, [caseId]);
  useEffect(() => {
    setData(null);
    void load();
  }, [load]);

  async function act(path: string, withBody: boolean, withKey: boolean) {
    setBusy(true);
    setErr(null);
    try {
      await api(`/api/cases/${caseId}/${path}`, {
        method: "POST",
        body: { reason, actor_name: name || null, body: withBody ? text : null },
        key: withKey ? newKey() : undefined,
      });
      setText("");
      setReason("");
      await load();
      onChanged?.();
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (!data) return <p>{err ? <span className="error-box">{err}</span> : "Đang tải…"}</p>;
  const c = data.case;
  const canReply = ["PENDING_HUMAN", "ERROR"].includes(c.status);
  const canOverride = ["AUTO_REPLIED", "SUPERSEDED"].includes(c.status);
  const canCancel = ["RECEIVED", "PROCESSING", "PENDING_HUMAN"].includes(c.status);
  return (
    <div>
      <p className="muted">Mã ca {c.id} · tạo {fmtTime(c.created_at)} · {c.source === "VERIFY" ? "dữ liệu Verify" : "email công khai"}</p>
      <div className="section-label">Email gốc (bất biến)</div>
      <div className="reply">{c.email_body}</div>
      <CaseSummary c={c} outbox={data.outbox} />

      {(canReply || canOverride || canCancel) && (
        <div className="card" style={{ marginTop: 12 }}>
          <h3>Thao tác của nhân viên DSA</h3>
          {(canReply || canOverride) && (
            <>
              <label>{canOverride ? "Nội dung đính chính (thay phản hồi tự động)" : "Nội dung trả lời sinh viên"}</label>
              <textarea value={text} onChange={(e) => setText(e.target.value)} />
            </>
          )}
          <label>Lý do (bắt buộc)</label>
          <input type="text" value={reason} onChange={(e) => setReason(e.target.value)} />
          <label>Tên nhân viên (tùy chọn)</label>
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} />
          <div className="row" style={{ marginTop: 8 }}>
            {canReply && <button disabled={busy} onClick={() => act("reply", true, true)}>Trả lời (ghi outbox)</button>}
            {canOverride && <button disabled={busy} onClick={() => act("override", true, true)}>Override: gửi đính chính</button>}
            {c.status === "ERROR" && <button className="secondary" disabled={busy} onClick={() => act("retry", false, false)}>Thử lại (cùng khóa)</button>}
            {canCancel && <button className="danger" disabled={busy} onClick={() => act("cancel", false, false)}>Hủy ca</button>}
          </div>
          {err && <p className="error-box">{err}</p>}
        </div>
      )}

      {data.outbox.length > 0 && (
        <>
          <div className="section-label">Outbox của ca</div>
          <OutboxTable rows={data.outbox} />
        </>
      )}
      <div className="section-label">Nhật ký kiểm toán (chỉ thêm, không sửa/xóa)</div>
      <AuditTable rows={data.audit} />
    </div>
  );
}

export function OutboxTable({ rows, onOpen }: { rows: Json[]; onOpen?: (id: string) => void }) {
  return (
    <div className="tablewrap">
      <table>
        <thead><tr><th>Thời điểm</th><th>Ca</th><th>Loại</th><th>Trạng thái</th><th>Nội dung</th></tr></thead>
        <tbody>
          {rows.map((o) => (
            <tr key={o.id}>
              <td>{fmtTime(o.created_at)}</td>
              <td>{onOpen ? <button className="linklike" onClick={() => onOpen(o.case_id)}>{String(o.case_id).slice(0, 8)}</button> : String(o.case_id).slice(0, 8)}</td>
              <td>{o.kind} v{o.version}</td>
              <td className={o.status === "SENT" ? "pass" : "muted"}>{o.status}</td>
              <td style={{ whiteSpace: "pre-wrap", maxWidth: 520 }}>{o.body}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
