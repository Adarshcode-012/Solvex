import asyncio

import json

import time

from fastapi.testclient import TestClient

import agents.all_agents as all_agents

import main

from main import app

def _mock_ai_response(role):
    if role == "analyzer":
        return json.dumps({
            "clean_problem": "Return the two indices.",
            "constraints": {},
            "dsa_category": "Arrays",
            "dsa_subcategory": "Two Sum",
            "sample_inputs": [],
            "sample_outputs": [],
            "edge_cases": [],
            "difficulty": "Easy",
        })
    if role == "strategist":
        return json.dumps({
            "reasoning_chain": "Use a hash map.",
            "chosen_approach": "Hash map",
            "approach_description": "Track complements.",
            "time_complexity": "O(n)",
            "space_complexity": "O(n)",
            "alternate_approaches": [],
            "implementation_hints": [],
            "new_semantic_pattern": "",
        })
    if role == "coder":
        return "def solve():\n    return [0, 1]"
    if role == "reviewer":
        return json.dumps({"verdict": "APPROVE", "issues": [], "confidence": "HIGH"})
    raise AssertionError(role)

def _setup(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "development")
    monkeypatch.setattr(main.settings, "gemini_api_key", "fake-key-for-tests-0123456789")
    monkeypatch.setattr(all_agents.settings, "gemini_api_key", "fake-key-for-tests-0123456789")
    monkeypatch.setattr(all_agents.settings, "judge0_api_key", None)
    monkeypatch.setattr(main, "_consume_global_solve_cap", lambda *_args: None)
    monkeypatch.setattr(all_agents, 'recall_similar_problems', lambda *_: [])
    monkeypatch.setattr(all_agents, 'recall_semantic_insights', lambda *_: [])
    main._solve_jobs.clear()

def _poll_until_terminal(client, job_id, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/solve/jobs/{job_id}")
        if response.status_code != 200:
            return response
        snapshot = response.json()
        if snapshot["status"] != "running":
            return response
        time.sleep(0.02)
    raise AssertionError("solve job did not reach a terminal status")

def test_mocked_ai_job_completes_and_returns_generated_code(monkeypatch):
    _setup(monkeypatch)
    roles = []

    async def fake_call_ai(role, **_kwargs):
        roles.append(role)
        await asyncio.sleep(0.02)
        return _mock_ai_response(role), "gemini"

    monkeypatch.setattr(all_agents, "call_ai", fake_call_ai)
    with TestClient(app) as client:
        started = client.post("/solve/jobs", json={"problem": "Return two indices", "language": "python"})
        assert started.status_code == 202
        snapshot = _poll_until_terminal(client, started.json()["job_id"]).json()

    assert snapshot["status"] == "complete"
    assert snapshot["result"]["final_solution"] == "def solve():\n    return [0, 1]"
    assert roles == ["analyzer", "strategist", "coder", "reviewer"]

def test_job_exception_is_persisted_with_request_id(monkeypatch):
    _setup(monkeypatch)

    async def explode(**_kwargs):
        await asyncio.sleep(0.01)
        raise RuntimeError("simulated background crash")

    monkeypatch.setattr(main, "solve_problem", explode)
    with TestClient(app) as client:
        started = client.post("/solve/jobs", json={"problem": "one", "language": "python"})
        request_id = started.headers["x-request-id"]
        snapshot = _poll_until_terminal(client, started.json()["job_id"]).json()

    assert snapshot["status"] == "failed"
    assert snapshot["error"]["code"] == "solve_failed"
    assert snapshot["error"]["request_id"] == request_id
