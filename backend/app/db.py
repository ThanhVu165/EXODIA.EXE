"""Kết nối Postgres (Supabase Session Pooler) bằng psycopg async — không chặn event loop."""
from __future__ import annotations

import logging
from pathlib import Path

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .config import database_url_problem

log = logging.getLogger("dsa.db")
SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")
SCHEMA_LOCK_ID = 4002_2026  # advisory lock: tránh hai instance (redeploy chồng nhau) cùng chạy DDL


class Database:
    def __init__(self, url: str | None) -> None:
        self.url = url
        self.problem = database_url_problem(url)
        self.pool: AsyncConnectionPool | None = None
        self.schema_ready = False

    async def open(self) -> None:
        """Mở pool ở chế độ không chờ: app vẫn khởi động (và /api/health/live vẫn 200) khi DB lỗi."""
        if self.problem:
            log.warning("DB không khởi tạo: %s", self.problem)
            return
        # autocommit + `async with conn.transaction()` tường minh cho mọi thao tác nhiều câu lệnh
        kwargs: dict = {"row_factory": dict_row, "autocommit": True}
        if "sslmode=" not in (self.url or ""):
            kwargs["sslmode"] = "require"  # Supabase: bắt buộc SSL khi URL không nói gì
        self.pool = AsyncConnectionPool(
            self.url, min_size=1, max_size=8, timeout=10, kwargs=kwargs, open=False
        )
        await self.pool.open(wait=False)
        try:
            await self.ensure_schema()
        except Exception as exc:  # không chặn khởi động; ready sẽ báo lỗi và thử lại
            log.warning("Chưa áp schema lúc khởi động: %s", type(exc).__name__)

    async def ensure_schema(self) -> None:
        if self.schema_ready:
            return
        if self.pool is None:
            raise RuntimeError(self.problem or "DB pool chưa mở")
        async with self.pool.connection(timeout=10) as conn:
            async with conn.transaction():
                await conn.execute("SELECT pg_advisory_xact_lock(%s)", (SCHEMA_LOCK_ID,))
                await conn.execute(SCHEMA_SQL)
        self.schema_ready = True
        log.info("Schema đã áp dụng")

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    async def ping(self, timeout: float = 3.0) -> None:
        """Ném lỗi nếu không kết nối/không truy vấn được hoặc schema chưa áp."""
        if self.pool is None:
            raise RuntimeError(self.problem or "DB pool chưa mở")
        async with self.pool.connection(timeout=timeout) as conn:
            await conn.execute("SELECT 1")
        await self.ensure_schema()

    def connection(self, timeout: float = 10.0):
        if self.pool is None:
            raise RuntimeError(self.problem or "DB pool chưa mở")
        return self.pool.connection(timeout=timeout)
