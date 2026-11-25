import json
import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("OPENAI_API_KEY", "fake-key-for-tests-0123456789")

from agents.all_agents import run_coder, run_strategist
from memory import brain, metadata


@pytest.mark.asyncio
async def test_real_coder_and_strategist_prompts_are_guest_isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(brain, "MEMORY_DIR", str(tmp_path / "memory"))
    monkeypatch.setattr(brain, "CHROMA_AVAILABLE", False)
    monkeypatch.setattr(metadata, "DB_PATH", str(tmp_path / "metadata.sqlite3"))
    rule = "PRIVATE_RULE_FROM_GUEST_A_93f6"
    brain.update_procedure("coder", rule, "guest_A")
    brain.update_procedure("strategist", rule, "guest_A")

    async def mock_call_ai(**kwargs):
        if kwargs["role"] == "strategist":
            return json.dumps({
                "reasoning_chain": "mock reasoning",
                "chosen_approach": "mock approach",
                "approach_description": "mock steps",
                "time_complexity": "O(1)",
                "space_complexity": "O(1)",
                "key_insight": "mock insight",
                "alternate_approaches": [],
                "implementation_hints": [],
                "new_semantic_pattern": "",
            }), "test-provider"
        return "print(1)", "test-provider"

    def make_state(user_id):
        state = brain.create_session_state("Print one", "python", user_id=user_id)
        state["extracted_problem"] = "Print one"
        state["constraints"] = {"n_max": "1"}
        state["dsa_category"] = "Math"
        return state

    with patch("agents.all_agents.call_ai", new_callable=AsyncMock, side_effect=mock_call_ai) as call_ai:
        for user_id in ("guest_A", "guest_B"):
            await run_strategist(make_state(user_id))
        for user_id in ("guest_A", "guest_B"):
            await run_coder(make_state(user_id))

    strategist_prompts = [
        call.kwargs["messages"][0]["content"]
        for call in call_ai.await_args_list
        if call.kwargs["role"] == "strategist"
    ]
    coder_prompts = [
        call.kwargs["messages"][0]["content"]
        for call in call_ai.await_args_list
        if call.kwargs["role"] == "coder"
    ]
    assert rule in strategist_prompts[0]
    assert rule not in strategist_prompts[1]
    assert rule in coder_prompts[0]
    assert rule not in coder_prompts[1]
