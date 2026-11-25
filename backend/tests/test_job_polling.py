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

def test_lost_job_has_restart_message_after_store_is_empty(monkeypatch):
    _setup(monkeypatch)

    async def quick_solve(**_kwargs):
        return {"status": "unverified", "final_solution": "print(1)"}

    monkeypatch.setattr(main, "solve_problem", quick_solve)
    with TestClient(app) as client:
        started = client.post("/solve/jobs", json={"problem": "one", "language": "python"})
        job_id = started.json()["job_id"]
        assert _poll_until_terminal(client, job_id).json()["status"] == "complete"
        main._solve_jobs.clear()
        with main.job_store._connect() as connection:
            connection.execute('DELETE FROM jobs WHERE id = ?', (job_id,))
        lost = client.get(f"/solve/jobs/{job_id}")

    assert lost.status_code == 404
    assert lost.json()["detail"] == {
        "code": "job_not_found",
        "message": "The server restarted while solving. Please run it again.",
    }

def test_changed_guest_gets_structured_not_found_for_job(monkeypatch):
    _setup(monkeypatch)

    async def quick_solve(**_kwargs):
        return {"status": "unverified", "final_solution": "print(1)"}

    monkeypatch.setattr(main, "solve_problem", quick_solve)
    with TestClient(app) as owner:
        started = owner.post("/solve/jobs", json={"problem": "one", "language": "python"})
        job_id = started.json()["job_id"]
        assert _poll_until_terminal(owner, job_id).json()["status"] == "complete"
        owner.cookies.clear()
        owner.cookies.set(main.SESSION_COOKIE, main._sign_guest_id('guest_changed_cookie'))
        changed = owner.get(f"/solve/jobs/{job_id}")
        assert changed.status_code == 404
        assert changed.json()['detail']['code'] == 'job_not_found'

    with TestClient(app) as different_guest:
        lost = different_guest.get(f"/solve/jobs/{job_id}")

    assert lost.status_code == 404
    assert lost.json()["detail"] == {
        "code": "job_not_found",
        "message": "The server restarted while solving. Please run it again.",
    }
