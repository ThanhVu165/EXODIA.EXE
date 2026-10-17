"""Loop factory chỉ để chạy cục bộ trên Windows.

Nguyên nhân gốc: trên Windows, uvicorn (không reload/subprocess) dùng ProactorEventLoop, còn psycopg async
từ chối ProactorEventLoop (psycopg/connection_async.py). Trên Linux/Docker/Railway uvicorn đã dùng
SelectorEventLoop nên KHÔNG cần file này; CMD của Dockerfile không dùng nó.

Dùng:  uvicorn app.main:app --app-dir backend --loop app.event_loop:selector_loop_factory
"""
import asyncio


def selector_loop_factory(*_args, **_kwargs) -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop()
