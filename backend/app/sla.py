"""Thời hạn xử lý (SLA) — QUY ƯỚC DEMO, không phải quy định chính thức của UEH.

Quy ước: ngày nhận email (giờ Asia/Ho_Chi_Minh) là D0, kể cả khi D0 là cuối tuần/ngày nghỉ.
Hạn = 17:00 của ngày làm việc thứ N (mặc định 3) TIẾP THEO sau D0; bỏ thứ Bảy, Chủ nhật và các ngày nghỉ cấu hình
trong SLA_HOLIDAYS (YYYY-MM-DD, phân tách bằng dấu phẩy). Đúng mốc hạn vẫn tính là đúng hạn (<=).
Tính hoàn toàn bằng code; không giao cho LLM.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
SLA_NOTE = ("Quy ước demo: hạn = 17:00 ngày làm việc thứ 3 sau ngày nhận (giờ Việt Nam), bỏ thứ Bảy, Chủ nhật và "
            "ngày nghỉ cấu hình. Không phải quy định chính thức của UEH.")


@dataclass(frozen=True)
class SlaConfig:
    business_days: int = 3
    cutoff: time = time(17, 0)
    holidays: frozenset[date] = frozenset()

    @staticmethod
    def from_env() -> "SlaConfig":
        raw = os.environ.get("SLA_HOLIDAYS", "")
        hol = frozenset(date.fromisoformat(x.strip()) for x in raw.split(",") if x.strip())
        hh, mm = (int(x) for x in os.environ.get("SLA_CUTOFF", "17:00").split(":"))
        return SlaConfig(int(os.environ.get("SLA_BUSINESS_DAYS", "3")), time(hh, mm), hol)


def is_business_day(d: date, cfg: SlaConfig) -> bool:
    return d.weekday() < 5 and d not in cfg.holidays


def deadline(received_at: datetime, cfg: SlaConfig) -> datetime:
    if received_at.tzinfo is None:
        raise ValueError("received_at phải có múi giờ")
    d = received_at.astimezone(TZ).date()
    counted = 0
    while counted < cfg.business_days:
        d += timedelta(days=1)
        if is_business_day(d, cfg):
            counted += 1
    return datetime.combine(d, cfg.cutoff, tzinfo=TZ)


def on_time(done_at: datetime, due: datetime) -> bool:
    return done_at <= due
