"""Ứng dụng FastAPI: API dưới /api, frontend tĩnh (Next.js export) cho mọi đường dẫn khác."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse

import os

import psycopg
from psycopg_pool import PoolTimeout

from . import api, smoke
from .agent import OpenAIAgentRunner
from .policy import load_policy
from .service import Ctx
from .config import load_settings
from .db import Database

logging.basicConfig(level=logging.INFO)

ALL_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    app.state.settings = settings
    app.state.db = Database(settings.database_url)
    await app.state.db.open()
    policy = load_policy()
    agent = None
    if settings.openai_model and os.environ.get("OPENAI_API_KEY"):
        agent = OpenAIAgentRunner(settings, policy)
    app.state.ctx = Ctx(db=app.state.db, policy=policy, settings=settings, agent=agent)
    try:
        yield
    finally:
        await app.state.db.close()


app = FastAPI(title="DSA Intelligence (demo)", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.api_route("/api/ping", methods=["GET", "HEAD"])
async def ping():
    return {"ok": True, "service": "dsa-intelligence", "synthetic_demo": True}


@app.api_route("/api/health/live", methods=["GET", "HEAD"])
async def health_live():
    # Không đụng DB, không đụng file: chỉ chứng minh tiến trình và event loop còn sống.
    return {"status": "live"}


@app.api_route("/api/health/ready", methods=["GET", "HEAD"])
async def health_ready(request: Request):
    settings = request.app.state.settings
    checks: dict[str, str] = {}
    index = settings.frontend_dir / "index.html"
    checks["frontend"] = "ok" if index.is_file() else "thiếu index.html (frontend chưa build)"
    try:
        await request.app.state.db.ping()
        checks["database"] = "ok"
    except Exception as exc:  # ghi loại lỗi, không lộ chuỗi kết nối
        checks["database"] = f"lỗi: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks},
                        status_code=200 if ok else 503)




@app.exception_handler(RuntimeError)
async def runtime_error_handler(request: Request, exc: RuntimeError):
    # DB chưa cấu hình/không mở được: lỗi kỹ thuật rõ ràng, không bao giờ là kết quả nghiệp vụ.
    logging.getLogger("dsa").warning("RuntimeError: %s", exc)
    return JSONResponse({"error": {"code": "SERVICE_UNAVAILABLE", "message": str(exc)[:300]}}, status_code=503)


@app.exception_handler(psycopg.Error)
async def db_error_handler(request: Request, exc: psycopg.Error):
    logging.getLogger("dsa").exception("DB error")
    return JSONResponse({"error": {"code": "DB_ERROR", "message": type(exc).__name__}}, status_code=503)


@app.exception_handler(PoolTimeout)
async def pool_timeout_handler(request: Request, exc: PoolTimeout):
    return JSONResponse({"error": {"code": "DB_UNAVAILABLE", "message": "PoolTimeout"}}, status_code=503)


app.include_router(smoke.router)
app.include_router(api.router)


@app.api_route("/api", methods=ALL_METHODS)
@app.api_route("/api/{rest:path}", methods=ALL_METHODS)
async def api_not_found(rest: str = ""):
    # Mọi /api/* không tồn tại: 404 JSON, KHÔNG bao giờ trả index.html.
    return JSONResponse({"error": "not_found"}, status_code=404)


def _resolve_static(frontend_dir: Path, path: str) -> Path | None:
    root = frontend_dir.resolve()
    for candidate in (path, f"{path}.html", f"{path}/index.html"):
        if not candidate or candidate.endswith("/"):
            continue
        target = (root / candidate).resolve()
        if root in target.parents and target.is_file():  # chặn path traversal
            return target
    return None


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def frontend(full_path: str, request: Request):
    frontend_dir = request.app.state.settings.frontend_dir
    found = _resolve_static(frontend_dir, full_path)
    if found is not None:
        return FileResponse(found)
    index = frontend_dir / "index.html"
    if index.is_file():
        return FileResponse(index)  # fallback SPA
    return JSONResponse({"error": "frontend_not_built"}, status_code=503)
