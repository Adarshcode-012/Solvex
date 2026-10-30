import pytest

from agents import all_agents


def make_state(**overrides):
    state = {
        "judge_iteration": 0,
        "judge_max_iterations": 5,
        "language": "python",
        "generated_code": "print(1)",
        "sample_inputs": [""],
        "sample_outputs": ["1"],
        "judge_passed": False,
        "judge_error": "",
        "judge_wrong_output": "",
        "compile_error": "",
        "verified": True,
        "status": "pending",
        "error_message": "",
        "chosen_approach": "print",
        "dsa_category": "Math",
        "pipeline_events": [],
        "agents_ai_used": {},
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_judge_unavailable_does_not_consume_iteration(monkeypatch):
    async def unavailable(*args):
        raise all_agents.JudgeUnavailable("HTTP 500")

    monkeypatch.setattr(all_agents, "_run_judge0_with_retries", unavailable)
    result = await all_agents.run_judge(make_state())

    assert result["status"] == "judge_unavailable"
    assert result["judge_iteration"] == 0
    assert result["judge_passed"] is False


@pytest.mark.asyncio
async def test_missing_key_is_unverified_without_comparing_output(monkeypatch):
    async def disabled(*args):
        return {"result_state": all_agents.JUDGE_DISABLED, "verified": False}

    monkeypatch.setattr(all_agents, "_run_judge0_with_retries", disabled)
    result = await all_agents.run_judge(make_state(sample_outputs=["not what the empty output returns"]))

    assert result["status"] == "unverified"
    assert result["verified"] is False
    assert result["judge_iteration"] == 0


@pytest.mark.asyncio
async def test_wrong_answer_consumes_retry(monkeypatch):
    async def wrong(*args):
        return {
            "status": {"id": all_agents.STATUS_ACCEPTED, "description": "Accepted"},
            "stdout": "2",
            "stderr": "",
            "compile_output": "",
        }

    monkeypatch.setattr(all_agents, "_run_judge0_with_retries", wrong)
    result = await all_agents.run_judge(make_state())

    assert result["status"] != "passed"
    assert result["judge_iteration"] == 1
    assert result["judge_wrong_output"] == "2"


@pytest.mark.asyncio
async def test_all_samples_matching_passes(monkeypatch):
    async def accepted(*args):
        return {
            "status": {"id": all_agents.STATUS_ACCEPTED, "description": "Accepted"},
            "stdout": "1\n",
            "stderr": "",
            "compile_output": "",
        }

    monkeypatch.setattr(all_agents, "_run_judge0_with_retries", accepted)
    result = await all_agents.run_judge(make_state())

    assert result["status"] == "passed"
    assert result["judge_passed"] is True


@pytest.mark.asyncio
async def test_no_samples_is_compiled_only(monkeypatch):
    async def accepted(*args):
        return {
            "status": {"id": all_agents.STATUS_ACCEPTED, "description": "Accepted"},
            "stdout": "",
            "stderr": "",
            "compile_output": "",
        }

    monkeypatch.setattr(all_agents, "_run_judge0_with_retries", accepted)
    result = await all_agents.run_judge(make_state(sample_inputs=[], sample_outputs=[]))

    assert result["status"] == "compiled_only"
    assert result["judge_passed"] is False