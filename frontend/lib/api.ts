// Gọi API cùng origin (FastAPI phục vụ cả frontend tĩnh). Không có secret nào ở phía trình duyệt.
export type Json = Record<string, any>;

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

export function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "k-" + Date.now() + "-" + Math.random().toString(16).slice(2);
}

export async function api<T = Json>(path: string, opts: { method?: string; body?: unknown; key?: string } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.key) headers["Idempotency-Key"] = opts.key;
  const res = await fetch(path, {
    method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  let data: any = null;
  try {
    data = await res.json();
  } catch {
    /* body không phải JSON */
  }
  if (!res.ok) {
    const e = data?.error || {};
    throw new ApiError(res.status, e.code || String(res.status), e.message || `HTTP ${res.status}`);
  }
  return data as T;
}

export const STATUS_VI: Record<string, string> = {
  RECEIVED: "Đã nhận",
  PROCESSING: "Đang xử lý",
  AUTO_REPLIED: "Đã trả lời tự động",
  PENDING_HUMAN: "Chờ nhân viên DSA",
  ERROR: "Lỗi kỹ thuật",
  HUMAN_REPLIED: "Nhân viên đã trả lời",
  CANCELLED: "Đã hủy",
  SUPERSEDED: "Đã đính chính",
};

export const REASON_VI: Record<string, string> = {
  OUT_OF_POLICY: "Ngoài phạm vi quy chế",
  UNKNOWN_FACT: "Chưa xác định được dữ kiện",
  REQUIRES_HUMAN_AUTHORITY: "Vượt thẩm quyền — cần người quyết định",
};

export const FLAG_VI: Record<string, string> = {
  SUSPECT_INPUT: "Nghi vấn chỉ dẫn nhắm vào hệ thống",
  PAUSED: "Nhận khi hệ thống tạm dừng",
  NGHI_TRUNG: "Nghi trùng nội dung",
  FORBIDDEN_PHRASE: "Bản nháp có cụm cấm",
  HANDOFF_QUESTION_INVALID: "Câu hỏi do bộ quy tắc soạn",
};

export function fmtTime(s?: string | null): string {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d.getTime()) ? s : d.toLocaleString("vi-VN");
}
