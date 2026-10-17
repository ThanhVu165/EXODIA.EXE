"""Ràng buộc DB (chạy trên Postgres thật qua TEST_DATABASE_URL)."""
import asyncio
import uuid

import psycopg
import pytest

from app.db import Database


def run(coro):
    return asyncio.run(coro)


async def _fresh(url):
    db = Database(url)
    await db.open()
    await db.ensure_schema()
    return db


def test_schema_idempotent_and_constraints(test_db_url):
    async def body():
        db = await _fresh(test_db_url)
        db.schema_ready = False
        await db.ensure_schema()  # chạy lại không lỗi
        cid = uuid.uuid4()
        key = f"k-{uuid.uuid4()}"
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO cases (id, submission_key, content_hash, email_body, status) "
                "VALUES (%s,%s,'h','x','RECEIVED')", (cid, key))
            with pytest.raises(psycopg.errors.UniqueViolation):
                await conn.execute(
                    "INSERT INTO cases (id, submission_key, content_hash, email_body, status) "
                    "VALUES (%s,%s,'h','x','RECEIVED')", (uuid.uuid4(), key))
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO outbox (id, case_id, kind, version, body, status, idempotency_key) "
                "VALUES (%s,%s,'AUTO_REPLY',1,'b','SENT',%s)", (uuid.uuid4(), cid, f"o-{cid}"))
            with pytest.raises(psycopg.errors.UniqueViolation):
                await conn.execute(
                    "INSERT INTO outbox (id, case_id, kind, version, body, status, idempotency_key) "
                    "VALUES (%s,%s,'AUTO_REPLY',1,'b','SENT',%s)", (uuid.uuid4(), cid, f"o2-{cid}"))
        async with db.connection() as conn:
            await conn.execute("INSERT INTO audit_log (case_id, actor, action) VALUES (%s,'system','T')", (cid,))
            with pytest.raises(psycopg.errors.RaiseException):
                await conn.execute("UPDATE audit_log SET action='X' WHERE case_id=%s", (cid,))
        async with db.connection() as conn:
            with pytest.raises(psycopg.errors.RaiseException):
                await conn.execute("DELETE FROM audit_log WHERE case_id=%s", (cid,))
        await db.close()
    run(body())


def test_conditional_transition_is_atomic(test_db_url):
    async def body():
        db = await _fresh(test_db_url)
        cid = uuid.uuid4()
        async with db.connection() as conn:
            await conn.execute(
                "INSERT INTO cases (id, submission_key, content_hash, email_body, status) "
                "VALUES (%s,%s,'h','x','RECEIVED')", (cid, f"k-{cid}"))

        async def claim():
            async with db.connection() as conn:
                cur = await conn.execute(
                    "UPDATE cases SET status='PROCESSING' WHERE id=%s AND status='RECEIVED' RETURNING id", (cid,))
                return await cur.fetchone()
        results = await asyncio.gather(*[claim() for _ in range(5)])
        assert sum(r is not None for r in results) == 1
        await db.close()
    run(body())
