import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from agents import all_agents
from config import Settings


def make_state():
    return {
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
        "user_id": "guest_A",
    }


class TransportClient:
    def __init__(self, handler, client_type):
        self.client = client_type(transport=httpx.MockTransport(handler))

    async def __aenter__(self):
        return await self.client.__aenter__()

    async def __aexit__(self, *args):
        return await self.client.__aexit__(*args)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["http_500", "timeout", "no_token", "polling_timeout", "status_zero"])
async def test_judge0_transport_failures_are_unavailable_and_retried_three_times(monkeypatch, failure):
    calls = []
    real_async_client = httpx.AsyncClient

    async def no_wait(_):
        return None

    async def handler(request):
        calls.append(request)
        if failure == "http_500":
            return httpx.Response(500, request=request)
        if failure == "timeout":
            raise httpx.ReadTimeout("placeholder timeout", request=request)
        if request.method == "POST":
            if failure == "no_token":
                return httpx.Response(200, json={}, request=request)
            return httpx.Response(200, json={"token": "token"}, request=request)
        if failure == "polling_timeout":
            return httpx.Response(200, json={"status": {"id": 2}}, request=request)
        return httpx.Response(200, json={"status": {"id": 0}}, request=request)

    monkeypatch.setattr(all_agents.settings, "judge0_api_key", "fake-key-for-tests-0123456789")
    monkeypatch.setattr(all_agents.settings, "judge0_base_url", "https://judge0.test")
    monkeypatch.setattr(
        all_agents.httpx,
        "AsyncClient",
        lambda **kwargs: TransportClient(handler, real_async_client),
    )
    monkeypatch.setattr(all_agents.asyncio, "sleep", no_wait)

    result = await all_agents.run_judge(make_state())

    assert result["status"] == "judge_unavailable"
    assert result["status"] != "passed"
    assert result["judge_passed"] is False
    assert result["judge_iteration"] == 0
    assert len([call for call in calls if call.method == "POST"]) == 3
    if failure in {"polling_timeout", "status_zero"}:
        assert len(calls) == 39
    else:
        assert len(calls) == 3


@pytest.mark.asyncio
async def test_missing_judge_key_is_unverified_without_output_comparison(monkeypatch):
    monkeypatch.setattr(all_agents.settings, "judge0_api_key", None)
    state = make_state()
    state["sample_outputs"] = ["a deliberately mismatching expected output"]

    def comparison_must_not_run(_):
        pytest.fail("output comparison ran while Judge0 was disabled")

    monkeypatch.setattr(all_agents, "_normalize", comparison_must_not_run)

    result = await all_agents.run_judge(state)

    assert result["status"] == "unverified"
    assert result["judge_iteration"] == 0
    assert result["judge_passed"] is False
    assert result["judge_wrong_output"] == ""
    assert result["compile_error"] == ""


@pytest.mark.asyncio
async def test_judge_polling_count_and_interval_are_environment_configurable(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-tests-0123456789")
    monkeypatch.setenv("JUDGE0_API_KEY", "fake-key-for-tests-0123456789")
    monkeypatch.setenv("JUDGE0_BASE_URL", "https://judge0.test")
    monkeypatch.delenv("JUDGE0_POLL_COUNT", raising=False)
    monkeypatch.delenv("JUDGE0_POLL_INTERVAL_SECONDS", raising=False)
    default_settings = Settings(_env_file=None)
    assert default_settings.judge0_poll_count == 12
    assert default_settings.judge0_poll_interval_seconds == 1.5

    monkeypatch.setenv("JUDGE0_POLL_COUNT", "2")
    monkeypatch.setenv("JUDGE0_POLL_INTERVAL_SECONDS", "0.01")
    configured_settings = Settings(_env_file=None)
    monkeypatch.setattr(all_agents, "settings", configured_settings)

    calls = []
    sleeps = []
    real_async_client = httpx.AsyncClient

    async def handler(request):
        calls.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"token": "token"}, request=request)
        return httpx.Response(200, json={"status": {"id": 2}}, request=request)

    async def no_wait(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(
        all_agents.httpx,
        "AsyncClient",
        lambda **kwargs: TransportClient(handler, real_async_client),
    )
    monkeypatch.setattr(all_agents.asyncio, "sleep", no_wait)

    with pytest.raises(all_agents.JudgeUnavailable):
        await all_agents._run_judge0("print(1)", "python", "")

    assert len([request for request in calls if request.method == "GET"]) == 2
    assert len(calls) == 3
    assert sleeps == [0.01, 0.01]


@pytest.mark.asyncio
async def test_judge_unavailable_ends_graph_without_coder_retry(monkeypatch):
    import orchestrator

    coder_calls = 0
    requests = []
    real_async_client = httpx.AsyncClient

    async def no_wait(_):
        return None

    async def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"token": "token"}, request=request)
        return httpx.Response(200, json={"status": {"id": 2}}, request=request)

    class TransportClient:
        def __init__(self, **kwargs):
            self.client = real_async_client(transport=httpx.MockTransport(handler))

        async def __aenter__(self):
            return await self.client.__aenter__()

        async def __aexit__(self, *args):
            return await self.client.__aexit__(*args)

    async def analyzer(state):
        state["extracted_problem"] = state["problem"]
        state["constraints"] = {}
        state["sample_inputs"] = [""]
        state["sample_outputs"] = ["1"]
        return state

    async def strategist(state):
        state["chosen_approach"] = "Print one"
        return state

    async def coder(state):
        nonlocal coder_calls
        coder_calls += 1
        state["generated_code"] = "print(1)"
        return state

    async def reviewer(state):
        return state

    monkeypatch.setattr(orchestrator, "run_analyzer", analyzer)
    monkeypatch.setattr(orchestrator, "run_strategist", strategist)
    monkeypatch.setattr(orchestrator, "run_coder", coder)
    monkeypatch.setattr(orchestrator, "run_reviewer", reviewer)
    monkeypatch.setattr(orchestrator, "run_judge", all_agents.run_judge)
    monkeypatch.setattr(orchestrator, "store_episodic", lambda **kwargs: None)
    monkeypatch.setattr(all_agents.settings, "judge0_api_key", "fake-key-for-tests-0123456789")
    monkeypatch.setattr(all_agents.settings, "judge0_base_url", "https://judge0.test")
    monkeypatch.setattr(all_agents.httpx, "AsyncClient", TransportClient)
    monkeypatch.setattr(all_agents.asyncio, "sleep", no_wait)

    result = await orchestrator.solve_problem(
        problem="Print one",
        language="python",
        user_id="guest_A",
    )

    assert coder_calls == 1
    assert result["status"] == "judge_unavailable"
    assert result["status"] != "pending"
    assert result["verified"] is False
    assert len([request for request in requests if request.method == "POST"]) == 3
