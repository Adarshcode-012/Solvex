import os
from pathlib import Path
import subprocess
import sys

from fastapi.testclient import TestClient
import main
from redis_fakes import FakeRedis


ADMIN_TEST_TOKEN = "test-admin-token-for-phase-five-tests-only"
EXPECTED_HEALTH_KEYS = {
    "memory_backend",
    "redis_reachable",
    "judge0_configured",
    "python_version",
    "app_version",
    "worker_count",
}


def _reset_admin_limiter(monkeypatch):
    monkeypatch.setattr(main, "_redis_client", FakeRedis())


def test_detailed_health_requires_configured_admin_token(monkeypatch):
    _reset_admin_limiter(monkeypatch)
    client = TestClient(main.app)

    monkeypatch.setattr(main.settings, "admin_token", None)
    assert client.get("/health/detailed").status_code == 404

    monkeypatch.setattr(main.settings, "admin_token", ADMIN_TEST_TOKEN)
    assert client.get("/health/detailed").status_code == 403
    assert client.get("/health/detailed", headers={"X-Admin-Token": "wrong-token"}).status_code == 403


def test_detailed_health_returns_only_safe_fields_with_admin_token(monkeypatch):
    _reset_admin_limiter(monkeypatch)
    monkeypatch.setattr(main.settings, "admin_token", ADMIN_TEST_TOKEN)
    monkeypatch.setattr(main, "_redis_client", None)
    response = TestClient(main.app).get(
        "/health/detailed", headers={"X-Admin-Token": ADMIN_TEST_TOKEN}
    )
    assert response.status_code == 200
    assert set(response.json()) == EXPECTED_HEALTH_KEYS


def test_usage_reset_uses_the_same_admin_gate(monkeypatch):
    _reset_admin_limiter(monkeypatch)
    client = TestClient(main.app)
    monkeypatch.setattr(main.settings, "admin_token", None)
    assert client.post("/usage/reset").status_code == 404

    monkeypatch.setattr(main.settings, "admin_token", ADMIN_TEST_TOKEN)
    assert client.post("/usage/reset").status_code == 403
    response = client.post("/usage/reset", headers={"X-Admin-Token": ADMIN_TEST_TOKEN})
    assert response.status_code == 200
    assert response.json() == {"status": "reset"}


def test_admin_routes_are_limited_per_ip(monkeypatch):
    _reset_admin_limiter(monkeypatch)
    monkeypatch.setattr(main.settings, "admin_token", ADMIN_TEST_TOKEN)
    client = TestClient(main.app)
    statuses = [
        client.get("/health/detailed", headers={"X-Admin-Token": "wrong-token"}).status_code
        for _ in range(11)
    ]
    assert statuses == [403] * 10 + [429]
    assert client.get("/health/detailed").headers.get("Retry-After") is not None


def test_short_admin_token_is_rejected_at_startup():
    backend_dir = Path(__file__).resolve().parents[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TEMP": os.environ.get("TEMP", ""),
        "TMP": os.environ.get("TMP", ""),
        "OPENAI_API_KEY": "fake-key-for-tests-0123456789",
        "ADMIN_TOKEN": "short-token",
    }
    result = subprocess.run(
        [sys.executable, "-c", "from config import settings"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "ADMIN_TOKEN must be at least 32 characters" in result.stderr


def test_admin_token_name_and_test_token_are_absent_from_frontend():
    repo_root = Path(__file__).resolve().parents[2]
    frontend_artifacts = [repo_root / "frontend" / "src", repo_root / "frontend" / "dist"]
    token_name = "ADMIN_" + "TOKEN"
    for artifact_dir in frontend_artifacts:
        if not artifact_dir.exists():
            continue
        for path in artifact_dir.rglob("*"):
            if path.is_file():
                contents = path.read_text(encoding="utf-8", errors="ignore")
                assert token_name not in contents, f"admin token env name leaked into {path}"
                assert ADMIN_TEST_TOKEN not in contents, f"test token leaked into {path}"


def test_public_nginx_blocks_admin_routes_and_does_not_publish_api_port():
    repo_root = Path(__file__).resolve().parents[2]
    nginx_conf = (repo_root / "frontend" / "nginx.conf").read_text(encoding="utf-8")
    assert "location = /health/detailed {\n        return 404;" in nginx_conf
    assert "location = /usage/reset {\n        return 404;" in nginx_conf
    assert "location = /api/health/detailed {\n        return 404;" in nginx_conf
    assert "location = /api/usage/reset {\n        return 404;" in nginx_conf
    compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
    assert '"127.0.0.1:${API_HOST_PORT:-8000}:8000"' in compose
    assert '"8000:8000"' not in compose
