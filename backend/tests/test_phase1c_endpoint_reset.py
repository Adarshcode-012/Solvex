import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "fake-key-for-tests-0123456789")

from fastapi.testclient import TestClient

import main
from memory import brain, metadata


def csrf(client):
    return {"X-CSRF-Token": client.cookies.get("solvex_csrf")}


@pytest.mark.asyncio
async def test_solve_stats_and_reset_are_isolated_between_guests(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr(brain, "CHROMA_AVAILABLE", False)
    monkeypatch.setattr(metadata, "DB_PATH", str(tmp_path / "metadata.sqlite3"))

    async def mocked_solve(problem, language, user_id, **kwargs):
        await main.call_ai(role="coder", messages=[{"role": "user", "content": "placeholder"}])
        brain.store_episodic(problem, "mock approach", language, 1, True, "print(1)", user_id)
        brain.update_procedure("coder", f"PRIVATE_{user_id}", user_id)
        brain.record_temporal_event("solve_complete", {"passed": True, "iterations": 1}, user_id)
        return {"status": "passed", "final_solution": "print(1)"}

    guest_a = TestClient(main.app)
    guest_b = TestClient(main.app)
    guest_a.get("/brain/stats")
    guest_b.get("/brain/stats")
    user_b = main._verify_guest_cookie(guest_b.cookies.get(main.SESSION_COOKIE))
    payload = {"problem": "Print one", "language": "python"}

    with patch("main.solve_problem", new_callable=AsyncMock, side_effect=mocked_solve) as solve_problem, patch(
        "main.call_ai", new_callable=AsyncMock, return_value=("mocked", "test-provider")
    ) as call_ai:
        a_solve = guest_a.post("/solve", json=payload, headers=csrf(guest_a))
        assert a_solve.status_code == 200
        assert guest_b.get("/brain/stats").json()["total_attempts"] == 0

        b_solve = guest_b.post("/solve", json=payload, headers=csrf(guest_b))
        assert b_solve.status_code == 200
        assert guest_b.get("/brain/stats").json()["total_attempts"] == 1

        reset = guest_a.post("/brain/reset", headers=csrf(guest_a))

    assert reset.status_code == 200
    assert solve_problem.await_count == 2
    assert call_ai.await_count == 2
    assert guest_a.get("/brain/stats").json()["total_attempts"] == 0
    assert guest_b.get("/brain/stats").json()["total_attempts"] == 1
    assert f"PRIVATE_{user_b}" in brain.get_procedure("coder", user_b)
    assert guest_b.get("/brain/temporal").json()["total_solves"] == 1
