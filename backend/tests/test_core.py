import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")

from agents.all_agents import _extract_json
from config import Settings
from main import app, _handle_rate_limit
from memory.brain import _save_json
from orchestrator import _should_continue
from utils.ai_router import RateLimitHit, get_agent_model


@pytest.mark.parametrize("text, expected", [
    ('{"answer": 1}', {"answer": 1}),
    ('```json\n{"answer": 1}\n```', {"answer": 1}),
    ('Here is the result: {"answer": 1}.', {"answer": 1}),
    ("not json", {}),
])
def test_extract_json_variants(text, expected):
    assert _extract_json(text) == expected


def test_should_continue_states():
    base = {"judge_passed": False, "judge_iteration": 0, "judge_max_iterations": 3, "status": "pending"}
    assert _should_continue({**base, "judge_passed": True}) == "end"
    assert _should_continue({**base, "judge_iteration": 3}) == "end"
    assert _should_continue(base) == "fix_code"


def test_router_manual_override_and_fallback(monkeypatch):
    monkeypatch.setattr("utils.ai_router.settings.anthropic_api_key", None)
    monkeypatch.setattr("utils.ai_router.settings.openai_api_key", "test-placeholder")
    monkeypatch.setattr("utils.ai_router.settings.gemini_api_key", None)
    assert get_agent_model("strategist", {"gpt4o": "gpt4o"})[0] == "gpt4o"
    assert get_agent_model("strategist")[0] == "gpt4o"


def test_rate_limit_hit_maps_to_429():
    with pytest.raises(Exception) as raised:
        _handle_rate_limit(RateLimitHit("claude", "Claude", "placeholder"))
    assert raised.value.status_code == 429
    assert raised.value.headers["Retry-After"] == "60"


def test_atomic_json_write(tmp_path):
    path = Path(tmp_path) / "memory.json"
    _save_json(str(path), {"entries": [1]})
    assert path.read_text(encoding="utf-8") == '{\n  "entries": [\n    1\n  ]\n}'
    assert list(tmp_path.glob("*.tmp")) == []


def test_config_requires_one_ai_key(monkeypatch):
    for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)
    settings = Settings(_env_file=None, openai_api_key="test-placeholder")
    assert settings.available_keys["gpt4o"] is True


def test_solve_endpoint_uses_mocked_orchestrator():
    client = TestClient(app)
    result = {"status": "unverified", "final_solution": "print(1)"}
    with patch("main.solve_problem", new_callable=AsyncMock) as solve:
        solve.return_value = result
        response = client.post(
            "/solve",
            json={"problem": "Print one", "language": "python"},
            headers={"X-CSRF-Token": client.cookies.get("solvex_csrf", "")},
        )
    assert response.status_code == 200
    assert response.json() == result
    solve.assert_awaited_once()