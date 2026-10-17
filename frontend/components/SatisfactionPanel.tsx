"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, fmtTime, Json } from "../lib/api";

function vnToday(): string {
  const d = new Date(Date.now() + 7 * 3600 * 1000);
  return d.toISOString().slice(0, 10);
}

const STATUS_VI: Record<string, string> = {
  COMPLETED: "Đã chấm",
  EVALUATION_FAILED: "Lỗi chấm (không có điểm)",
  INSUFFICIENT_CONTEXT: "Không đủ dữ liệu để chấm",
  RUNNING: "Đang chấm",
};

function Review({ item, onDone }: { item: Json; onDone: () => void }) {
  const [comment, setComment] = useState("");
  const [name, setName] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (item.review_verdict) {
    return (
      <p className="muted">
        DSA {item.review_verdict === "AGREE" ? "đồng ý" : "không đồng ý"}
        {item.reviewer ? ` (${item.reviewer})` : ""} · {fmtTime(item.reviewed_at)}: {item.review_comment}
      </p>
    );
  }
  async function send(verdict: string) {
    setBusy(true); setErr(null);
    try {
      await api(`/api/evaluations/${item.evaluation_id}/review`, { body: { verdict, comment, actor_name: name || null } });
      onDone();
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally { setBusy(false); }
  }
  return (
    <div className="row" style={{ marginTop: 6 }}>
      <input type="text" style={{ flex: "1 1 240px" }} placeholder="Nhận xét của DSA (bắt buộc)" value={comment} onChange={(e) => setComment(e.target.value)} />
      <input type="text" style={{ width: 160 }} placeholder="Tên (tùy chọn)" value={name} onChange={(e) => setName(e.target.value)} />
      <button disabled={busy} onClick={() => send("AGREE")}>Đồng ý</button>
      <button className="secondary" disabled={busy} onClick={() => send("DISAGREE")}>Không đồng ý</button>
      {err && <span className="error-box">{err}</span>}
    </div>
  );
}

function Item({ it, onOpen, onDone }: { it: Json; onOpen?: (id: string) => void; onDone: () => void }) {
  return (
    <div className="card" style={{ marginBottom: 8 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <b>{it.score != null ? `${it.score}/100` : STATUS_VI[it.eval_status] || "Chưa chấm"}</b>
        <span className="muted">gửi {fmtTime(it.sent_at)}{it.outbox_status === "SUPERSEDED" ? " · đã được nhân viên đính chính" : ""}</span>
        {onOpen && <button className="linklike" onClick={() => onOpen(it.case_id)}>Mở ca</button>}
      </div>
      {it.reason && <p><span className="section-label">Giải thích của Agent 2: </span>{it.reason}</p>}
      {it.missing_points?.length > 0 && <p className="muted">Ý còn thiếu: {it.missing_points.join("; ")}</p>}
      {it.error_code && <p className="error-box">Lỗi: {it.error_code}</p>}
      <details>
        <summary className="muted">Câu hỏi gốc và phản hồi đã gửi</summary>
        <div className="section-label">Email sinh viên</div><div className="reply">{it.email_body}</div>
        <div className="section-label">Phản hồi đã gửi</div><div className="reply">{it.body}</div>
      </details>
      {it.eval_status === "COMPLETED" && <Review item={it} onDone={onDone} />}
    </div>
  );
}

export function SatisfactionPanel({ onOpen }: { onOpen?: (id: string) => void }) {
  const [day, setDay] = useState(vnToday());
  const [rep, setRep] = useState<Json | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const load = useCallback(async () => {
    try { setRep(await api(`/api/reports/daily?day=${day}`)); setErr(null); } catch (e) { setErr((e as Error).message); }
  }, [day]);
  useEffect(() => { void load(); }, [load]);

  async function backfill(retryFailed: boolean) {
    setBusy(true); setErr(null);
    try {
      await api(`/api/evaluations/backfill?retry_failed=${retryFailed}`, { method: "POST" });
      await load();
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally { setBusy(false); }
  }

  const maxCount = rep ? Math.max(1, ...rep.distribution.map((d: Json) => d.count)) : 1;
  return (
    <>
      <div className="card">
        <h2>Đánh giá phản hồi tự động — mức hài lòng dự đoán</h2>
        <p className="banner" style={{ borderRadius: 6 }}>
          Điểm dự đoán bởi AI (Agent 2) — <b>không phải khảo sát sinh viên</b>. Chỉ chấm phản hồi tự động đã ghi outbox;
          không chấm ca chuyển tiếp hay phản hồi do nhân viên viết. Agent 2 không sửa hay gửi thêm gì.
        </p>
        <div className="row">
          <label>Ngày (giờ Việt Nam) <input type="date" value={day} onChange={(e) => setDay(e.target.value)} /></label>
          <button className="secondary" onClick={load}>Tạo / làm mới báo cáo</button>
          <button className="secondary" disabled={busy} onClick={() => backfill(false)}>{busy ? "Đang chấm…" : "Chấm các phản hồi còn thiếu"}</button>
          <button className="secondary" disabled={busy} onClick={() => backfill(true)}>Chấm lại các lượt lỗi</button>
        </div>
        {err && <p className="error-box">{err}</p>}
      </div>

      {rep && (
        <>
          <div className="card">
            <div className="row" style={{ gap: 24 }}>
              <div><div className="section-label">Phản hồi tự động đã gửi</div><h2 style={{ margin: 0 }}>{rep.sent}</h2></div>
              <div><div className="section-label">Đã chấm</div><h2 style={{ margin: 0 }}>{rep.evaluated}</h2></div>
              <div><div className="section-label">Điểm trung bình (dự đoán)</div><h2 style={{ margin: 0 }}>{rep.average_score ?? "—"}</h2></div>
              <div><div className="section-label">Lỗi / thiếu dữ liệu / chưa chấm</div><h2 style={{ margin: 0 }}>{rep.failed} / {rep.insufficient_context} / {rep.not_evaluated + rep.running}</h2></div>
              <div><div className="section-label">Đã được nhân viên đính chính</div><h2 style={{ margin: 0 }}>{rep.corrected_by_staff}</h2></div>
            </div>
            <p className="muted">Điểm trung bình chỉ tính trên {rep.evaluated} lượt chấm thành công. DSA đã rà soát: đồng ý {rep.reviewed.agree}, không đồng ý {rep.reviewed.disagree}. Rubric {rep.rubric_version}.</p>
            <div className="section-label">Phân bố điểm</div>
            {rep.distribution.map((d: Json) => (
              <div key={d.range} className="row" style={{ flexWrap: "nowrap" }}>
                <span style={{ width: 70 }}>{d.range}</span>
                <div style={{ background: "var(--accent)", height: 14, width: `${(d.count / maxCount) * 60}%`, minWidth: d.count ? 4 : 0, borderRadius: 3 }} />
                <span>{d.count}</span>
              </div>
            ))}
          </div>

          <div className="card">
            <h3>Cần DSA đọc lại: điểm dưới {rep.review_threshold} ({rep.needs_review.length})</h3>
            <p className="muted">{rep.review_threshold_note}.</p>
            {rep.needs_review.length === 0 && <p className="muted">Không có phản hồi nào dưới ngưỡng.</p>}
            {rep.needs_review.map((it: Json) => <Item key={it.outbox_id} it={it} onOpen={onOpen} onDone={load} />)}
          </div>

          <div className="card">
            <button className="linklike" onClick={() => setShowAll((x) => !x)}>{showAll ? "Ẩn" : "Xem"} tất cả {rep.items.length} phản hồi trong ngày</button>
            {showAll && rep.items.map((it: Json) => <Item key={it.outbox_id} it={it} onOpen={onOpen} onDone={load} />)}
          </div>
        </>
      )}
    </>
  );
}
