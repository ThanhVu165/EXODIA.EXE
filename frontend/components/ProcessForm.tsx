"use client";

import { useState } from "react";
import { api, ApiError, Json, newKey } from "../lib/api";
import { CaseSummary } from "./CaseView";

/** Dán email mới → POST /api/emails với Idempotency-Key mới cho mỗi lần bấm. */
export function ProcessForm({ onOpen }: { onOpen?: (id: string) => void }) {
  const [body, setBody] = useState("");
  const [sender, setSender] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<Json | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setErr(null);
    setResult(null);
    try {
      const r = await api<Json>("/api/emails", { body: { body, sender: sender || null }, key: newKey() });
      const d = await api<Json>(`/api/cases/${r.case.id}`);
      setResult(d);
    } catch (e) {
      setErr(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card">
      <h2>Xử lý email mới của sinh viên</h2>
      <label>Nội dung email (tối đa 4.000 ký tự)</label>
      <textarea value={body} maxLength={4000} onChange={(e) => setBody(e.target.value)}
        placeholder="Dán email của sinh viên vào đây…" />
      <label>Người gửi (tùy chọn, dữ liệu giả lập)</label>
      <input type="text" value={sender} onChange={(e) => setSender(e.target.value)} />
      <div className="row" style={{ marginTop: 8 }}>
        <button disabled={busy || !body.trim()} onClick={submit}>{busy ? "Đang xử lý (gọi AI thật)…" : "Xử lý"}</button>
        <span className="muted">{body.length}/4000</span>
      </div>
      {err && <p className="error-box">{err}</p>}
      {result && (
        <div style={{ marginTop: 12 }}>
          <CaseSummary c={result.case} outbox={result.outbox} />
          {onOpen && (
            <p><button className="linklike" onClick={() => onOpen(result.case.id)}>Xem chi tiết ca, thao tác và nhật ký kiểm toán →</button></p>
          )}
        </div>
      )}
    </div>
  );
}
