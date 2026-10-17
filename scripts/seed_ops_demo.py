#!/usr/bin/env python3
"""Tạo dữ liệu DEMO GIẢ LẬP có nhãn cho tab "Báo cáo vận hành" (ca có tuổi để thấy gần hạn / quá hạn).

- Chỉ THÊM dòng mới với source='DEMO_SEED'; không sửa hay xóa ca thật, không đổi thời điểm của ca thật.
- Mặc định báo cáo LOẠI dữ liệu này; chỉ thấy khi bật "Bao gồm dữ liệu demo giả lập".
- Email có tiền tố [DỮ LIỆU DEMO GIẢ LẬP]; mỗi ca có dòng audit DEMO_SEED_CREATED.

    python scripts/seed_ops_demo.py --confirm            # dùng DATABASE_URL trong môi trường
    python scripts/seed_ops_demo.py --confirm --batch b2 # tạo thêm một lô khác
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.db import Database  # noqa: E402
from app.policy import load_policy  # noqa: E402

LABEL = "[DỮ LIỆU DEMO GIẢ LẬP] "
SEEDS = [  # (tuổi tính theo ngày lịch, trạng thái, cờ, mã lỗi, có phản hồi?, nội dung)
    (6, "PENDING_HUMAN", ["PAUSED"], None, False,
     "Em gửi email khi hệ thống đang tạm dừng, hỏi về việc khai báo công cụ AI trong đề án."),
    (4, "ERROR", [], "LLM_TIMEOUT", False,
     "Em muốn hỏi khóa luận của em cần kiểm tra Turnitin trước khi nộp không ạ?"),
    (2, "PENDING_HUMAN", [], None, False,
     "Em xin ban xác nhận bài tập nhóm của em không vi phạm quy định dùng AI ạ."),
    (5, "HUMAN_REPLIED", [], None, True,
     "Em hỏi về cách ghi nguồn khi dịch tài liệu tiếng Anh ạ."),
]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="xác nhận ghi dữ liệu demo vào DATABASE_URL")
    ap.add_argument("--batch", default="b1")
    a = ap.parse_args()
    url = os.environ.get("DATABASE_URL")
    if not a.confirm or not url:
        print("Cần --confirm và biến DATABASE_URL. Không ghi gì.")
        return 2
    policy = load_policy()
    db = Database(url)
    await db.open()
    await db.ensure_schema()
    now = datetime.now(timezone.utc)
    created = 0
    async with db.connection() as conn:
        for i, (age, status, flags, err, replied, text) in enumerate(SEEDS):
            key = f"demo-seed:{a.batch}:{i}"
            body = LABEL + text
            at = now - timedelta(days=age)
            cid = uuid.uuid4()
            async with conn.transaction():
                cur = await conn.execute(
                    """INSERT INTO cases (id, submission_key, content_hash, email_body, source, status, flags, error_code,
                                          created_at, updated_at, policy_version, decision, package)
                       VALUES (%s,%s,%s,%s,'DEMO_SEED',%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (submission_key) DO NOTHING RETURNING id""",
                    (cid, key, hashlib.sha256(body.encode()).hexdigest(), body, status, flags, err, at, at,
                     policy.version, "ESCALATE" if status == "PENDING_HUMAN" else None,
                     json.dumps({"suggested_route_label": "nhân viên DSA tự xử lý", "demo_seed": True})))
                if await cur.fetchone() is None:
                    continue
                await conn.execute(
                    """INSERT INTO audit_log (case_id, actor, action, input_ref, reason, status_after, idempotency_key,
                                              policy_version, details, at)
                       VALUES (%s,'system','DEMO_SEED_CREATED',%s,%s,%s,%s,%s,%s,%s)""",
                    (cid, f"case:{cid}", "Dữ liệu demo giả lập để minh họa báo cáo vận hành", "RECEIVED", key,
                     policy.version, json.dumps({"demo_seed": True, "batch": a.batch}), at))
                # dòng audit chuyển trạng thái giống service thật, để báo cáo dựng lại được trạng thái tại từng thời điểm
                mid = at + timedelta(minutes=1)
                if err:
                    trans = ("TECHNICAL_ERROR", "ERROR", f"{err}: dữ liệu demo giả lập")
                elif "PAUSED" in flags:
                    trans = ("QUEUED_WHILE_PAUSED", "PENDING_HUMAN", "Công tắc tạm dừng đang bật (demo giả lập)")
                else:
                    trans = ("DECIDED_ESCALATE", "PENDING_HUMAN", "Chuyển nhân viên DSA (demo giả lập)")
                await conn.execute(
                    """INSERT INTO audit_log (case_id, actor, action, input_ref, reason, status_before, status_after,
                                              idempotency_key, policy_version, details, at)
                       VALUES (%s,'system',%s,%s,%s,'PROCESSING',%s,%s,%s,%s,%s)""",
                    (cid, trans[0], f"case:{cid}", trans[2], trans[1], key, policy.version,
                     json.dumps({"demo_seed": True}), mid))
                if replied:
                    rat = at + timedelta(days=age - 1)
                    await conn.execute(
                        """INSERT INTO outbox (id, case_id, kind, version, body, status, idempotency_key, created_at)
                           VALUES (%s,%s,'HUMAN_REPLY',1,%s,'SENT',%s,%s)""",
                        (uuid.uuid4(), cid, LABEL + "Phản hồi giả lập của nhân viên.", f"{key}:reply", rat))
                    await conn.execute(
                        """INSERT INTO audit_log (case_id, actor, actor_name, action, input_ref, reason, status_before,
                                                  status_after, idempotency_key, policy_version, at)
                           VALUES (%s,'staff','demo','STAFF_REPLIED',%s,%s,'PENDING_HUMAN','HUMAN_REPLIED',%s,%s,%s)""",
                        (cid, f"case:{cid}", "Dữ liệu demo giả lập", f"{key}:reply", policy.version, rat))
            created += 1
    await db.close()
    print(f"Đã tạo {created} ca DEMO_SEED (lô {a.batch}); bỏ qua {len(SEEDS) - created} ca đã tồn tại.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
