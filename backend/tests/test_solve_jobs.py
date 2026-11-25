from fastapi.testclient import TestClient

import main
from main import app
from utils.ai_router import publish_progress
from agents.all_agents import AgentFailure


def _configure_job_test(monkeypatch):
    monkeypatch.setattr(main.settings, "app_env", "development")
    monkeypatch.setattr(main.settings, "gemini_api_key", "fake-key-for-tests-0123456789")
    monkeypatch.setattr(main, "_consume_global_solve_cap", lambda *_: None)
    main._solve_jobs.clear()


def test_solve_job_progress_is_emitted_in_agent_order(monkeypatch):
    _configure_job_test(monkeypatch)

    async def fake_solve(**_kwargs):
        for agent in ("analyzer", "strategist", "coder", "reviewer", "judge"):
            publish_progress(agent, "started")
            publish_progress(agent, "done")
        return {"status": "unverified", "final_solution": "print(1)"}

    monkeypatch.setattr(main, "solve_problem", fake_solve)
    client = TestClient(app)
    started = client.post("/solve/jobs", json={"problem": "one", "language": "python"})
    assert started.status_code == 202
    job_id = started.json()["job_id"]
    snapshot = client.get(f"/solve/jobs/{job_id}").json()

    assert snapshot["status"] == "complete"
    assert [event["agent"] for event in snapshot["events"]] == [
        role for role in ("analyzer", "strategist", "coder", "reviewer", "judge") for _ in range(2)
    ]


def test_solve_job_isolation_returns_404_to_another_guest(monkeypatch):
    _configure_job_test(monkeypatch)

    async def slow_solve(**_kwargs):
        return {"status": "unverified", "final_solution": "print(1)"}

    monkeypatch.setattr(main, "solve_problem", slow_solve)
    owner = TestClient(app)
    started = owner.post("/solve/jobs", json={"problem": "one", "language": "python"})
    job_id = started.json()["job_id"]

    other_guest = TestClient(app)
    response = other_guest.get(f"/solve/jobs/{job_id}")
    assert response.status_code == 404


def test_failed_agent_is_reported_by_job_poll(monkeypatch):
    _configure_job_test(monkeypatch)

    async def failed_solve(**_kwargs):
        raise AgentFailure("coder", "mocked failure", code="mock_failure")

    monkeypatch.setattr(main, "solve_problem", failed_solve)
    client = TestClient(app)
    started = client.post("/solve/jobs", json={"problem": "one", "language": "python"})
    snapshot = client.get(f"/solve/jobs/{started.json()['job_id']}").json()

    assert snapshot["status"] == "failed"
    assert snapshot["error"]["code"] == "mock_failure"
    assert snapshot["error"]["message"] == "mocked failure"
    assert snapshot["error"]["request_id"] == started.headers["x-request-id"]
