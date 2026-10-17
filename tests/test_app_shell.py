"""Test xác định cho bộ khung Giai đoạn 1 (không cần DB thật, không gọi LLM)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    out = tmp_path / "out"
    (out / "_next").mkdir(parents=True)
    (out / "index.html").write_text("<html>INDEX</html>", encoding="utf-8")
    (out / "_next" / "a.js").write_text("console.log(1)", encoding="utf-8")
    monkeypatch.setenv("FRONTEND_DIR", str(out))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("SMOKE_TOKEN", raising=False)
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_root_serves_index(client):
    r = client.get("/")
    assert r.status_code == 200 and "INDEX" in r.text


def test_static_asset(client):
    r = client.get("/_next/a.js")
    assert r.status_code == 200 and "console.log" in r.text


def test_spa_fallback(client):
    r = client.get("/hang-cho/ca-123")
    assert r.status_code == 200 and "INDEX" in r.text


def test_path_traversal_falls_back(client):
    r = client.get("/..%2F..%2Fetc%2Fpasswd")
    assert "root:" not in r.text


def test_ping_and_live(client):
    assert client.get("/api/ping").json()["ok"] is True
    assert client.get("/api/health/live").status_code == 200


@pytest.mark.parametrize("method,path", [("GET", "/api/khong-ton-tai"), ("POST", "/api/x/y"), ("GET", "/api")])
def test_unknown_api_is_json_404(client, method, path):
    r = client.request(method, path)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert "INDEX" not in r.text


def test_ready_503_without_db(client):
    r = client.get("/api/health/ready")
    assert r.status_code == 503
    assert r.json()["checks"]["frontend"] == "ok"


def test_smoke_endpoints_hidden_without_token(client):
    assert client.post("/api/smoke/llm").status_code == 404
    assert client.post("/api/smoke/db").status_code == 404


def test_forbidden_transaction_pooler_port():
    from app.config import database_url_problem
    assert "6543" in database_url_problem("postgresql://u:p@h.pooler.supabase.com:6543/postgres")
    assert database_url_problem("postgresql://u:p@h.pooler.supabase.com:5432/postgres") is None


def test_agent_output_schema_is_strict_compatible():
    # Kiểm tra cục bộ: Agents SDK chấp nhận schema ở chế độ strict (chưa chứng minh model chấp nhận — đó là S4).
    from agents.agent_output import AgentOutputSchema
    from app.agent_contract import AgentOutput
    schema = AgentOutputSchema(AgentOutput).json_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(AgentOutput.model_fields)


@pytest.mark.parametrize("path,code", [("/api/health/live", 200), ("/", 200), ("/api/ping", 200)])
def test_head_supported(client, path, code):
    assert client.head(path).status_code == code
