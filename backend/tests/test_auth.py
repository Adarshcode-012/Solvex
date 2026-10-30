import os

os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")

from fastapi.testclient import TestClient

from main import app


def test_guest_session_is_issued_and_csrf_protects_followup_post():
    client = TestClient(app)
    first = client.get("/brain/stats")

    assert first.status_code == 200
    assert "solvex_guest" in first.cookies
    assert "solvex_csrf" in first.cookies

    blocked = client.post("/brain/reset")
    assert blocked.status_code == 403

    csrf = client.cookies.get("solvex_csrf")
    allowed = client.post("/brain/reset", headers={"X-CSRF-Token": csrf})
    assert allowed.status_code == 200


def test_health_is_public_but_detailed_health_is_not_admin_access():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health/detailed").status_code == 403