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

def test_completed_snapshot_survives_process_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(main.job_store, 'DB_PATH', tmp_path / 'jobs.sqlite3')
    snapshot = {'user_id': 'guest_test', 'status': 'complete', 'events': [], 'result': {'final_solution': 'print(1)'}, 'error': None}
    main.job_store.save('completed', snapshot)
    monkeypatch.setattr(main.job_store, 'PROCESS_ID', 'new-process')
    assert main.job_store.load('completed')['result']['final_solution'] == 'print(1)'

def test_interrupted_snapshot_is_lost_after_process_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(main.job_store, 'DB_PATH', tmp_path / 'jobs.sqlite3')
    main.job_store.save('interrupted', {'status': 'running'})
    monkeypatch.setattr(main.job_store, 'PROCESS_ID', 'new-process')
    assert main.job_store.load('interrupted') is None
