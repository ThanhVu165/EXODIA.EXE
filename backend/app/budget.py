"""Bộ đếm sử dụng lưu trong Postgres (không lưu trong bộ nhớ tiến trình).

consume() tăng bộ đếm một cách nguyên tử CHỈ KHI còn dưới trần; trả False khi đã chạm trần.
"""
from __future__ import annotations

import hashlib

BUCKET_LLM_PUBLIC = "llm:public"
BUCKET_LLM_VERIFY = "llm:verify"
BUCKET_LLM_EVAL = "llm:eval"
BUCKET_LLM_OPS = "llm:ops"


def ip_bucket(ip: str | None) -> str:
    return "ip:" + hashlib.sha256((ip or "unknown").encode()).hexdigest()[:16]


async def consume(conn, bucket: str, window: str, limit: int) -> bool:
    if limit <= 0:
        return False
    cur = await conn.execute(
        """
        INSERT INTO usage_counters (bucket, window_start, count)
        VALUES (%s, date_trunc(%s, now()), 1)
        ON CONFLICT (bucket, window_start) DO UPDATE
            SET count = usage_counters.count + 1
            WHERE usage_counters.count < %s
        RETURNING count
        """,
        (bucket, window, limit),
    )
    return (await cur.fetchone()) is not None


async def current(conn, bucket: str, window: str) -> int:
    cur = await conn.execute(
        "SELECT count FROM usage_counters WHERE bucket=%s AND window_start=date_trunc(%s, now())",
        (bucket, window))
    row = await cur.fetchone()
    return row["count"] if row else 0
