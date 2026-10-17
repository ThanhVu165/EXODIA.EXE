"""Đọc cấu hình từ biến môi trường. Không có giá trị bí mật mặc định nào trong code."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

# Gốc dự án: backend/app/config.py -> parents[2]. Docker đặt APP_ROOT=/app.
PROJECT_ROOT = Path(os.environ.get("APP_ROOT") or Path(__file__).resolve().parents[2])

FORBIDDEN_DB_PORT = 6543  # Supabase transaction pooler — bị cấm (Mục 2.5)


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    openai_model: str | None
    frontend_dir: Path
    smoke_token: str | None
    llm_timeout_s: float
    llm_max_output_tokens: int
    max_email_chars: int
    llm_daily_cap: int          # trần toàn cục lượt gọi LLM/ngày cho email công khai (hàng rào thật)
    verify_daily_cap: int       # hạn mức riêng cho Verify
    rate_per_ip_per_min: int    # giới hạn theo IP (IP có thể bị giả mạo -> chỉ là lớp phụ)
    lease_seconds: int          # thời hạn giữ ca ở PROCESSING trước khi cho phép tiếp quản
    price_input_per_1m: float | None   # đơn giá USD/1M token (để ước tính chi phí; không đặt => không ước tính)
    price_output_per_1m: float | None


def _float_or_none(v: str | None) -> float | None:
    return float(v) if v not in (None, "") else None


def load_settings() -> Settings:
    frontend = os.environ.get("FRONTEND_DIR") or str(PROJECT_ROOT / "frontend" / "out")
    return Settings(
        database_url=os.environ.get("DATABASE_URL") or None,
        openai_model=os.environ.get("OPENAI_MODEL") or None,
        frontend_dir=Path(frontend),
        smoke_token=os.environ.get("SMOKE_TOKEN") or None,
        llm_timeout_s=float(os.environ.get("LLM_TIMEOUT_S", "60")),
        llm_max_output_tokens=int(os.environ.get("LLM_MAX_OUTPUT_TOKENS", "6000")),
        max_email_chars=int(os.environ.get("MAX_EMAIL_CHARS", "4000")),
        llm_daily_cap=int(os.environ.get("LLM_DAILY_CAP", "300")),
        verify_daily_cap=int(os.environ.get("VERIFY_DAILY_CAP", "60")),
        rate_per_ip_per_min=int(os.environ.get("RATE_PER_IP_PER_MIN", "6")),
        lease_seconds=int(os.environ.get("LEASE_SECONDS", "180")),
        price_input_per_1m=_float_or_none(os.environ.get("PRICE_INPUT_PER_1M")),
        price_output_per_1m=_float_or_none(os.environ.get("PRICE_OUTPUT_PER_1M")),
    )


def database_url_problem(url: str | None) -> str | None:
    """Trả về mô tả vấn đề nếu DATABASE_URL vi phạm quyết định hạ tầng, None nếu ổn."""
    if not url:
        return "DATABASE_URL chưa đặt"
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:  # URL hỏng
        return f"DATABASE_URL không hợp lệ: {type(exc).__name__}"
    if port == FORBIDDEN_DB_PORT:
        return "DATABASE_URL dùng cổng 6543 (transaction pooler) — bị cấm; dùng Session Pooler cổng 5432"
    return None


def describe_database_url(url: str | None) -> dict:
    """Mô tả an toàn (không có mật khẩu) để hiển thị trong smoke test."""
    if not url:
        return {"configured": False}
    parts = urlsplit(url)
    query = dict(p.split("=", 1) for p in parts.query.split("&") if "=" in p)
    return {
        "configured": True,
        "host": parts.hostname,
        "port": parts.port,
        "sslmode_in_url": query.get("sslmode"),
    }
