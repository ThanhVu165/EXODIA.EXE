"""Endpoint smoke test hạ tầng (Giai đoạn 1).

Chỉ bật khi biến SMOKE_TOKEN được đặt; mọi request phải gửi header X-Smoke-Token khớp.
Không đặt SMOKE_TOKEN => các endpoint này trả 404 như không tồn tại (không tốn ngân sách LLM).
"""
from __future__ import annotations

import hmac
import uuid

from fastapi import APIRouter, Header, HTTPException, Request

from .config import describe_database_url
from .llm import run_smoke_call

router = APIRouter(prefix="/api/smoke")

SMOKE_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS smoke_check (
    id uuid PRIMARY KEY,
    note text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
)
"""


def _guard(request: Request, token: str | None) -> None:
    expected = request.app.state.settings.smoke_token
    if not expected or not token or not hmac.compare_digest(expected, token):
        raise HTTPException(status_code=404, detail="Not Found")


@router.post("/db")
async def smoke_db_write(request: Request, x_smoke_token: str | None = Header(default=None)):
    _guard(request, x_smoke_token)
    db = request.app.state.db
    if db.pool is None:
        raise HTTPException(status_code=503, detail=db.problem or "DB chưa sẵn sàng")
    row_id = uuid.uuid4()
    async with db.pool.connection(timeout=5) as conn:
        await conn.execute(SMOKE_TABLE_DDL)
        await conn.execute(
            "INSERT INTO smoke_check (id, note) VALUES (%s, %s)", (row_id, "smoke write")
        )
        cur = await conn.execute(
            "SELECT id, note, created_at FROM smoke_check WHERE id = %s", (row_id,)
        )
        read_back = await cur.fetchone()
        ssl_in_use = bool(conn.pgconn.ssl_in_use)
    return {
        "db": describe_database_url(db.url),
        "client_ssl_in_use": ssl_in_use,
        "written_id": str(row_id),
        "read_back": {"id": str(read_back[0]), "note": read_back[1], "created_at": read_back[2].isoformat()},
    }


@router.get("/db")
async def smoke_db_read(request: Request, x_smoke_token: str | None = Header(default=None)):
    """Dùng để kiểm tra dữ liệu còn sau redeploy (S8)."""
    _guard(request, x_smoke_token)
    db = request.app.state.db
    if db.pool is None:
        raise HTTPException(status_code=503, detail=db.problem or "DB chưa sẵn sàng")
    async with db.pool.connection(timeout=5) as conn:
        await conn.execute(SMOKE_TABLE_DDL)
        cur = await conn.execute(
            "SELECT count(*), min(created_at), max(created_at) FROM smoke_check"
        )
        count, oldest, newest = await cur.fetchone()
        cur = await conn.execute(
            "SELECT id FROM smoke_check ORDER BY created_at ASC LIMIT 1"
        )
        first = await cur.fetchone()
    return {
        "db": describe_database_url(db.url),
        "row_count": count,
        "oldest_id": str(first[0]) if first else None,
        "oldest_created_at": oldest.isoformat() if oldest else None,
        "newest_created_at": newest.isoformat() if newest else None,
    }


@router.post("/llm")
async def smoke_llm(request: Request, x_smoke_token: str | None = Header(default=None)):
    _guard(request, x_smoke_token)
    try:
        return await run_smoke_call(request.app.state.settings)
    except Exception as exc:  # báo lỗi nguyên văn cho S4, không nuốt
        raise HTTPException(
            status_code=502,
            detail={"error_type": type(exc).__name__, "message": str(exc)[:2000]},
        ) from exc
