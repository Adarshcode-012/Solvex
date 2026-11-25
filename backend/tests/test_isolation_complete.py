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
async def test_all_guest_memory_paths_are_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr(brain, "CHROMA_AVAILABLE", False)
    monkeypatch.setattr(metadata, "DB_PATH", str(tmp_path / "metadata.sqlite3"))

    guest_a = TestClient(main.app)
    guest_b = TestClient(main.app)
    guest_a.get("/brain/stats")
    guest_b.get("/brain/stats")
    user_a = main._verify_guest_cookie(guest_a.cookies.get(main.SESSION_COOKIE))
    user_b = main._verify_guest_cookie(guest_b.cookies.get(main.SESSION_COOKIE))

    brain.store_episodic("A problem", "A approach", "python", 1, True, "A code", user_a)
    brain.store_semantic("A pattern", "A insight", "A category", user_a)
    brain.update_procedure("coder", "A private rule", user_a)
    brain.record_temporal_event("solve_complete", {"passed": True, "iterations": 1}, user_a)

    assert brain.recall_similar_problems("A problem", user_a)
    assert brain.recall_similar_problems("A problem", user_b) == []
    assert brain.recall_semantic_insights("A pattern", user_a)
    assert brain.recall_semantic_insights("A pattern", user_b) == []
    assert "A private rule" in brain.get_procedure("coder", user_a)
    assert "A private rule" not in brain.get_procedure("coder", user_b)
    assert brain.get_temporal_insights(user_a)["total_solves"] == 1
    assert brain.get_temporal_insights(user_b)["total_solves"] == 0

    async def fake_call_ai(**kwargs):
        return "print(1)", "test-provider"

    prompt_state = lambda user_id: {
        "judge_iteration": 0,
        "language": "python",
        "user_id": user_id,
        "pipeline_events": [],
        "constraints": {},
        "extracted_problem": "Print one",
        "chosen_approach": "Print one",
        "sample_inputs": [],
        "sample_outputs": [],
        "generated_code": "",
        "manual_ai_overrides": {},
        "agents_ai_used": {},
    }
    with patch("agents.all_agents.call_ai", new_callable=AsyncMock, side_effect=fake_call_ai) as call_ai:
        from agents.all_agents import run_coder
        await run_coder(prompt_state(user_a))
        await run_coder(prompt_state(user_b))
    prompt_a = call_ai.await_args_list[0].kwargs["messages"][0]["content"]
    prompt_b = call_ai.await_args_list[1].kwargs["messages"][0]["content"]
    assert "A private rule" in prompt_a
    assert "A private rule" not in prompt_b

    stats_a = guest_a.get("/brain/stats")
    stats_b = guest_b.get("/brain/stats")
    assert stats_a.json()["total_attempts"] == 1
    assert stats_b.json()["total_attempts"] == 0

    brain.store_episodic("B problem", "B approach", "python", 1, True, "B code", user_b)
    brain.store_semantic("B pattern", "B insight", "B category", user_b)
    brain.update_procedure("coder", "B private rule", user_b)
    brain.record_temporal_event("solve_complete", {"passed": True, "iterations": 1}, user_b)
    reset_a = guest_a.post("/brain/reset", headers=csrf(guest_a))
    assert reset_a.status_code == 200
    assert guest_a.get("/brain/stats").json()["total_attempts"] == 0
    assert guest_b.get("/brain/stats").json()["total_attempts"] == 1
    assert "A problem" not in str(guest_b.get("/brain/stats").json())
    assert "B private rule" in brain.get_procedure("coder", user_b)
    assert brain.get_temporal_insights(user_b)["total_solves"] == 1


def test_chroma_episodic_recall_filters_by_guest(monkeypatch):
    class FakeCollection:
        records = [
            {"user_id": "guest_A", "problem": "A problem"},
            {"user_id": "guest_B", "problem": "B problem"},
        ]

        def count(self):
            return len(self.records)

        def query(self, *, query_texts, n_results, where=None):
            records = self.records
            if where:
                records = [record for record in records if record["user_id"] == where["user_id"]]
            return {"metadatas": [records[:n_results]]}

    monkeypatch.setattr(brain, "CHROMA_AVAILABLE", True)
    monkeypatch.setattr(brain, "_episodic_col", FakeCollection())

    assert [row["user_id"] for row in brain.recall_similar_problems("A problem", "guest_A")] == ["guest_A"]
    assert [row["user_id"] for row in brain.recall_similar_problems("A problem", "guest_B")] == ["guest_B"]
