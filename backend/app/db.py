"""Kết nối Postgres (Supabase Session Pooler) bằng psycopg async — không chặn event loop."""
from __future__ import annotations

import logging

from psycopg_pool import AsyncConnectionPool

from .config import database_url_problem

log = logging.getLogger("dsa.db")


class Database:
    def __init__(self, url: str | None) -> None:
        self.url = url
        self.problem = database_url_problem(url)
        self.pool: AsyncConnectionPool | None = None

    async def open(self) -> None:
        """Mở pool ở chế độ không chờ: app vẫn khởi động (và /api/health/live vẫn 200) khi DB lỗi."""
        if self.problem:
            log.warning("DB không khởi tạo: %s", self.problem)
            return
        kwargs: dict = {}
        if "sslmode=" not in (self.url or ""):
            kwargs["sslmode"] = "require"  # Supabase: bắt buộc SSL khi URL không nói gì
        self.pool = AsyncConnectionPool(
            self.url, min_size=1, max_size=5, timeout=5, kwargs=kwargs, open=False
        )
        await self.pool.open(wait=False)

    async def close(self) -> None:
        if self.pool is not None:
            await self.pool.close()

    async def ping(self, timeout: float = 3.0) -> None:
        """Ném lỗi nếu không kết nối/không truy vấn được."""
        if self.pool is None:
            raise RuntimeError(self.problem or "DB pool chưa mở")
        async with self.pool.connection(timeout=timeout) as conn:
            await conn.execute("SELECT 1")
