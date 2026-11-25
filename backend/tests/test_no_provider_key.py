from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from main import app


def test_development_without_valid_key_keeps_health_and_rejects_solve(capsys, monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "development")
    monkeypatch.setattr(main.settings, "anthropic_api_key", None)
    monkeypatch.setattr(main.settings, "openai_api_key", "test-placeholder")
    monkeypatch.setattr(main.settings, "gemini_api_key", None)

    with (
        TestClient(app) as client,
        patch("main.solve_problem", new_callable=AsyncMock) as solve,
    ):
        assert client.get("/health").json() == {"status": "ok"}
        response = client.post("/solve", json={"problem": "Print one", "language": "python"})

    assert response.status_code == 503
    assert response.json() == {
        "detail": {
            "code": "ai_key_missing",
            "message": "No AI provider key is configured. Add one to backend/.env and restart.",
        }
    }
    solve.assert_not_awaited()
    startup_log = capsys.readouterr().out
    assert "no_ai_provider_key_configured" in startup_log
    assert "provider" in startup_log and "anthropic" in startup_log and "not configured" in startup_log
    assert "provider" in startup_log and "openai" in startup_log and "placeholder-ignored" in startup_log
    assert "provider" in startup_log and "gemini" in startup_log and "not configured" in startup_log


