import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from litellm.exceptions import Timeout as LiteLLMTimeout

import main
import utils.ai_router as ai_router
from agents.all_agents import AgentFailure
from main import app
from utils.ai_router import AIProviderError


def test_litellm_timeout_becomes_safe_provider_timeout(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "get_agent_model",
        lambda *_args: ("gemini", "gemini/gemini-4-hydrogen"),
    )
    monkeypatch.setattr(
        ai_router,
        "acompletion",
        AsyncMock(
            side_effect=LiteLLMTimeout(
                "Connection timed out",
                model="gemini/gemini-4-hydrogen",
                llm_provider="gemini",
            )
        ),
    )

    with pytest.raises(AIProviderError) as caught:
        asyncio.run(ai_router.call_ai("analyzer", [{"role": "user", "content": "test"}]))

    assert caught.value.code == "ai_provider_timeout"
    assert str(caught.value) == (
        "Gemini request timed out after 120 seconds. "
        "Check backend connectivity and try again."
    )


def test_solve_returns_structured_504_for_provider_timeout(monkeypatch):
    monkeypatch.setattr(main.settings, "gemini_api_key", "fake-key-for-tests-0123456789")
    message = (
        "Gemini request timed out after 120 seconds. "
        "Check backend connectivity and try again."
    )

    with TestClient(app) as client, patch("main.solve_problem", new_callable=AsyncMock) as solve:
        solve.side_effect = AgentFailure("analyzer", message, code="ai_provider_timeout")
        response = client.post(
            "/solve",
            json={"problem": "Print one", "language": "python"},
        )

    assert response.status_code == 504
    assert response.json() == {
        "detail": {"code": "ai_provider_timeout", "message": message}
    }
