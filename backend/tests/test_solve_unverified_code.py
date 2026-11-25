import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import main
import agents.all_agents as all_agents
import utils.ai_router as ai_router
from main import app


GENERATED_CODE = "def solve():\n    return [0, 1]"


def _completion_for_role(role):
    if role == "analyzer":
        return json.dumps({
            "clean_problem": "Return two indices.",
            "constraints": {"n_max": "10"},
            "dsa_category": "Arrays",
            "dsa_subcategory": "Two Sum",
            "sample_inputs": ["nums = [2, 7], target = 9"],
            "sample_outputs": ["[0, 1]"],
            "edge_cases": [],
            "difficulty": "Easy",
        })
    if role == "strategist":
        return json.dumps({
            "reasoning_chain": "Use a map.",
            "chosen_approach": "Hash map",
            "approach_description": "Find the complement.",
            "time_complexity": "O(n)",
            "space_complexity": "O(n)",
            "alternate_approaches": [],
            "implementation_hints": [],
            "new_semantic_pattern": "",
        })
    if role == "coder":
        return GENERATED_CODE
    if role == "reviewer":
        return json.dumps({
            "verdict": "APPROVE",
            "issues": [],
            "fix_instructions": "",
            "confidence": "HIGH",
        })
    raise AssertionError(f"Unexpected mocked AI role: {role}")


@pytest.mark.parametrize(
    ("judge_mode", "expected_status"),
    [
        ("disabled", "unverified"),
        ("compiled_only", "compiled_only"),
        ("unavailable", "judge_unavailable"),
        ("max_retries", "max_retries"),
    ],
)
def test_solve_returns_generated_code_for_all_judge_outcomes(
    monkeypatch, judge_mode, expected_status
):
    monkeypatch.setattr(main.settings, "app_env", "development")
    monkeypatch.setattr(main.settings, "gemini_api_key", "fake-key-for-tests-0123456789")
    monkeypatch.setattr(all_agents.settings, "gemini_api_key", "fake-key-for-tests-0123456789")
    observed_limits = []

    async def fake_completion(**kwargs):
        system_text = kwargs["messages"][0]["content"]
        role = next(
            role for role in ("analyzer", "strategist", "coder", "reviewer")
            if f"{role.title()} Agent" in system_text
        )
        observed_limits.append((role, kwargs["max_tokens"]))
        content = _completion_for_role(role)
        if judge_mode == "compiled_only" and role == "analyzer":
            data = json.loads(content)
            data["sample_inputs"] = []
            data["sample_outputs"] = []
            content = json.dumps(data)
        return SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=9, completion_tokens=4),
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        )

    monkeypatch.setattr(ai_router, "acompletion", fake_completion)

    if judge_mode == "disabled":
        monkeypatch.setattr(all_agents.settings, "judge0_api_key", None)
    else:
        monkeypatch.setattr(all_agents.settings, "judge0_api_key", "fake-judge-key")

    async def fake_judge(code, language, stdin):
        if judge_mode == "unavailable":
            raise all_agents.JudgeUnavailable("mocked Judge0 outage")
        if judge_mode == "max_retries":
            return {
                "status": {"id": 3, "description": "Accepted"},
                "stdout": "wrong",
                "stderr": "",
                "compile_output": "",
            }
        return {
            "status": {"id": 3, "description": "Accepted"},
            "stdout": "",
            "stderr": "",
            "compile_output": "",
        }

    if judge_mode != "disabled":
        monkeypatch.setattr(all_agents, "_run_judge0_with_retries", fake_judge)
    with TestClient(app) as client:
        response = client.post(
            "/solve",
            json={"problem": "Return indices for a two sum problem.", "language": "python"},
        )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] == expected_status
    assert result["final_solution"] == GENERATED_CODE
    assert isinstance(result["timings"], list)
    timing_roles = [item["role"] for item in result["timings"]]
    if expected_status == "max_retries":
        assert timing_roles == ["analyzer", "strategist"] + ["coder", "reviewer"] * 5
    else:
        assert timing_roles == ["analyzer", "strategist", "coder", "reviewer"]
    assert all(set(item) == {"role", "seconds"} for item in result["timings"])
    expected_token_limits = {
        "analyzer": main.settings.analyzer_max_tokens,
        "strategist": main.settings.strategist_max_tokens,
        "coder": main.settings.coder_max_tokens,
        "reviewer": main.settings.reviewer_max_tokens,
    }
    assert observed_limits == [(role, expected_token_limits[role]) for role in timing_roles]
