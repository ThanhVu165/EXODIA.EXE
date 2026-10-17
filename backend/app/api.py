"""API nghiệp vụ (công khai, không tài khoản — bản demo dữ liệu giả lập)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import budget, service
from .service import Ctx, ServiceError, to_json

router = APIRouter(prefix="/api")


class EmailIn(BaseModel):
    body: str = Field(..., description="Nội dung email sinh viên")
    sender: str | None = Field(None, max_length=200)


class ActionIn(BaseModel):
    reason: str | None = None
    actor_name: str | None = Field(None, max_length=100)
    body: str | None = None


class PauseIn(BaseModel):
    on: bool
    reason: str | None = None
    actor_name: str | None = Field(None, max_length=100)


def ctx_of(request: Request) -> Ctx:
    return request.app.state.ctx


def err(e: ServiceError) -> JSONResponse:
    return JSONResponse({"error": {"code": e.code, "message": e.message}}, status_code=e.http_status)


def case_view(case: dict) -> dict:
    keep = ["id", "submission_key", "status", "decision", "reason_primary", "reasons", "flags", "package",
            "error_code", "error_detail", "model_id", "policy_version", "usage", "attempts", "sender",
            "email_body", "source", "verify_run_id", "created_at", "updated_at"]
    return to_json({k: case.get(k) for k in keep})


async def rate_limit(request: Request, ctx: Ctx, scope: str, per_min: int) -> None:
    ip = request.client.host if request.client else None
    async with ctx.db.connection() as conn:
        ok = await budget.consume(conn, f"{budget.ip_bucket(ip)}:{scope}", "minute", per_min)
    if not ok:
        raise ServiceError(429, "RATE_LIMITED", f"Quá {per_min} yêu cầu/phút từ địa chỉ này; thử lại sau")


@router.post("/emails")
async def submit_email(payload: EmailIn, request: Request,
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    ctx = ctx_of(request)
    try:
        await rate_limit(request, ctx, "emails", ctx.settings.rate_per_ip_per_min)
        case, created = await service.process_email(ctx, body=payload.body, sender=payload.sender,
                                                    key=idempotency_key or "")
    except ServiceError as e:
        return err(e)
    return JSONResponse({"created": created, "case": case_view(case)}, status_code=201 if created else 200)


@router.get("/cases")
async def list_cases(request: Request, view: str = "queue", limit: int = 50):
    ctx = ctx_of(request)
    limit = max(1, min(limit, 200))
    where = "source='PUBLIC'"
    if view == "queue":
        where += " AND status IN ('PENDING_HUMAN','ERROR')"
    async with ctx.db.connection() as conn:
        cur = await conn.execute(f"SELECT * FROM cases WHERE {where} ORDER BY created_at DESC LIMIT %s", (limit,))
        rows = await cur.fetchall()
    return {"cases": [case_view(r) for r in rows]}


@router.get("/cases/{case_id}")
async def get_case(case_id: uuid.UUID, request: Request):
    try:
        d = await service.case_detail(ctx_of(request), case_id)
    except ServiceError as e:
        return err(e)
    return {"case": case_view(d["case"]), "outbox": to_json(d["outbox"]), "audit": to_json(d["audit"])}


@router.post("/cases/{case_id}/retry")
async def retry_case(case_id: uuid.UUID, request: Request):
    """Thử lại ca ERROR bằng CÙNG khóa idempotency của lần gửi gốc."""
    ctx = ctx_of(request)
    try:
        await rate_limit(request, ctx, "emails", ctx.settings.rate_per_ip_per_min)
        async with ctx.db.connection() as conn:
            case = await service.get_case(conn, case_id)
        if case is None:
            raise ServiceError(404, "NOT_FOUND", "Không tìm thấy ca")
        if case["status"] != "ERROR":
            raise ServiceError(409, "NOT_RETRYABLE", f"Chỉ thử lại ca ERROR (hiện: {case['status']})")
        bucket = budget.BUCKET_LLM_VERIFY if case["source"] == "VERIFY" else budget.BUCKET_LLM_PUBLIC
        case, _ = await service.process_email(ctx, body=case["email_body"], sender=case["sender"],
                                              key=case["submission_key"], source=case["source"],
                                              verify_run_id=case["verify_run_id"], budget_bucket=bucket)
    except ServiceError as e:
        return err(e)
    return {"case": case_view(case)}


@router.post("/cases/{case_id}/cancel")
async def cancel(case_id: uuid.UUID, payload: ActionIn, request: Request):
    try:
        case = await service.cancel_case(ctx_of(request), case_id, payload.reason, payload.actor_name)
    except ServiceError as e:
        return err(e)
    return {"case": case_view(case)}


@router.post("/cases/{case_id}/reply")
async def reply(case_id: uuid.UUID, payload: ActionIn, request: Request,
                idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    try:
        if not idempotency_key:
            raise ServiceError(400, "BAD_IDEMPOTENCY_KEY", "Thiếu header Idempotency-Key")
        case = await service.staff_reply(ctx_of(request), case_id, payload.body or "", payload.reason,
                                         idempotency_key, payload.actor_name)
    except ServiceError as e:
        return err(e)
    return {"case": case_view(case)}


@router.post("/cases/{case_id}/override")
async def override(case_id: uuid.UUID, payload: ActionIn, request: Request,
                   idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    try:
        if not idempotency_key:
            raise ServiceError(400, "BAD_IDEMPOTENCY_KEY", "Thiếu header Idempotency-Key")
        case = await service.override_auto(ctx_of(request), case_id, payload.body or "", payload.reason,
                                           idempotency_key, payload.actor_name)
    except ServiceError as e:
        return err(e)
    return {"case": case_view(case)}


@router.get("/outbox")
async def outbox(request: Request, limit: int = 100):
    ctx = ctx_of(request)
    async with ctx.db.connection() as conn:
        cur = await conn.execute(
            """SELECT o.*, c.source FROM outbox o JOIN cases c ON c.id=o.case_id
               WHERE c.source='PUBLIC' ORDER BY o.created_at DESC LIMIT %s""", (max(1, min(limit, 300)),))
        rows = await cur.fetchall()
    return {"outbox": to_json(rows)}


@router.get("/audit")
async def audit_recent(request: Request, limit: int = 100):
    ctx = ctx_of(request)
    async with ctx.db.connection() as conn:
        cur = await conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT %s", (max(1, min(limit, 300)),))
        rows = await cur.fetchall()
    return {"audit": to_json(rows)}


@router.get("/system")
async def system(request: Request):
    ctx = ctx_of(request)
    async with ctx.db.connection() as conn:
        cur = await conn.execute("SELECT value, updated_at FROM system_flags WHERE key='paused'")
        row = await cur.fetchone()
        used_public = await budget.current(conn, budget.BUCKET_LLM_PUBLIC, "day")
        used_verify = await budget.current(conn, budget.BUCKET_LLM_VERIFY, "day")
    return to_json({
        "paused": bool(row and row["value"].get("on")),
        "paused_info": row,
        "policy_version": ctx.policy.version,
        "model_configured": ctx.settings.openai_model,
        "llm_ready": ctx.agent is not None,
        "budget": {"public_used": used_public, "public_cap": ctx.settings.llm_daily_cap,
                   "verify_used": used_verify, "verify_cap": ctx.settings.verify_daily_cap},
        "synthetic_demo": True,
    })


@router.post("/system/pause")
async def pause(payload: PauseIn, request: Request):
    try:
        res = await service.set_paused(ctx_of(request), payload.on, payload.reason, payload.actor_name)
    except ServiceError as e:
        return err(e)
    return res
