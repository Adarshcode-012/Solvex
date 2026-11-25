from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

import main
from agents.all_agents import AgentFailure
from main import app
from utils.ai_router import provider_auth_error_message


def test_provider_auth_failure_returns_safe_structured_error_without_key_value(monkeypatch):
    monkeypatch.setattr(main.settings, "openai_api_key", "fake-key-for-tests-0123456789")
    message = provider_auth_error_message("gpt4o")
    assert message == "OpenAI rejected the API key. Check the key for OpenAI and restart the backend."

    with TestClient(app) as client, patch("main.solve_problem", new_callable=AsyncMock) as solve:
        solve.side_effect = AgentFailure("analyzer", message, code="ai_auth_failed")
        response = client.post(
            "/solve",
            json={"problem": "Print one", "language": "python"},
        )

    assert response.status_code == 502
    assert response.json() == {"detail": {"code": "ai_auth_failed", "message": message}}
    assert "fake-key-for-tests-0123456789" not in response.text
