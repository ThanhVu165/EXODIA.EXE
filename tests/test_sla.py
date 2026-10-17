"""SLA quy ước demo: 17:00 ngày làm việc thứ 3 sau ngày nhận (giờ VN), bỏ T7/CN/ngày nghỉ cấu hình."""
from datetime import date, datetime, time, timedelta

import pytest

from app.sla import TZ, SlaConfig, deadline, on_time

CFG = SlaConfig()


def vn(y, m, d, hh=10, mm=0, ss=0):
    return datetime(y, m, d, hh, mm, ss, tzinfo=TZ)


# 2026-10-19 là thứ Hai
@pytest.mark.parametrize("received,due", [
    (vn(2026, 10, 19, 10), vn(2026, 10, 22, 17)),        # T2 -> T5
    (vn(2026, 10, 19, 23, 59), vn(2026, 10, 22, 17)),    # cuối ngày vẫn là D0
    (vn(2026, 10, 23, 18), vn(2026, 10, 28, 17)),        # T6 tối -> T2,T3,T4 -> T4
    (vn(2026, 10, 24, 9), vn(2026, 10, 28, 17)),         # T7: D0 = T7 -> T2,T3,T4
    (vn(2026, 10, 25, 9), vn(2026, 10, 28, 17)),         # CN -> T4
])
def test_business_days(received, due):
    assert deadline(received, CFG) == due


def test_holiday_skipped():
    cfg = SlaConfig(holidays=frozenset({date(2026, 10, 20)}))   # nghỉ thứ Ba
    assert deadline(vn(2026, 10, 19, 10), cfg) == vn(2026, 10, 23, 17)   # T4,T5,T6


def test_timezone_conversion_from_utc():
    # 2026-10-19 18:30 UTC = 2026-10-20 01:30 giờ VN => D0 là thứ Ba
    from datetime import timezone
    assert deadline(datetime(2026, 10, 19, 18, 30, tzinfo=timezone.utc), CFG) == vn(2026, 10, 23, 17)


def test_exact_cutoff_is_on_time():
    due = vn(2026, 10, 22, 17)
    assert on_time(due, due)
    assert not on_time(due + timedelta(seconds=1), due)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        deadline(datetime(2026, 10, 19, 10), CFG)


def test_env_config(monkeypatch):
    monkeypatch.setenv("SLA_HOLIDAYS", "2026-10-20, 2026-10-21")
    monkeypatch.setenv("SLA_CUTOFF", "16:30")
    cfg = SlaConfig.from_env()
    assert cfg.cutoff == time(16, 30) and len(cfg.holidays) == 2
