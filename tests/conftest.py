import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


@pytest.fixture()
def test_db_url():
    """Postgres THẬT cho test DB (cục bộ hoặc Supabase). Không đặt TEST_DATABASE_URL => skip."""
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL chưa đặt")
    return url
