import asyncio
from types import SimpleNamespace

import pytest
from litellm.exceptions import RateLimitError

import utils.ai_router as ai_router


def _response(text="ok"):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
    )


def test_call_timing_is_collected_with_role_and_seconds(monkeypatch):
    captured = {}

    async def completion(**kwargs):
        captured.update(kwargs)
        return _response()

    monkeypatch.setattr(ai_router, "get_agent_model", lambda *_: ("gemini", "gemini/test-model"))
    monkeypatch.setattr(ai_router, "acompletion", completion)

    async def run():
        with ai_router.ai_request_scope() as timings:
            await ai_router.call_ai("analyzer", [{"role": "user", "content": "test"}])
        return timings

    timings = asyncio.run(run())
    assert timings[0]["role"] == "analyzer"
    assert timings[0]["seconds"] >= 0
    assert captured["max_tokens"] == 4096


def test_provider_rate_limit_is_not_retried_and_reports_model(monkeypatch):
    calls = 0

    async def completion(**_kwargs):
        nonlocal calls
        calls += 1
        raise RateLimitError(
            "quota exceeded per minute",
            llm_provider="gemini",
            model="gemini/gemini-test",
        )

    monkeypatch.setattr(ai_router, "get_agent_model", lambda *_: ("gemini", "gemini/gemini-test"))
    monkeypatch.setattr(ai_router, "acompletion", completion)

    with pytest.raises(ai_router.RateLimitHit) as caught:
        asyncio.run(ai_router.call_ai("analyzer", [{"role": "user", "content": "test"}]))

    assert calls == 1
    assert caught.value.ai_label == "Gemini (gemini/gemini-test)"
    assert caught.value.quota_type == "per-minute"


def test_solve_call_budget_stops_before_extra_completion(monkeypatch):
    calls = 0

    async def completion(**_kwargs):
        nonlocal calls
        calls += 1
        return _response()

    monkeypatch.setattr(ai_router.settings, "ai_max_calls_per_solve", 1)
    monkeypatch.setattr(ai_router, "get_agent_model", lambda *_: ("gemini", "gemini/test-model"))
    monkeypatch.setattr(ai_router, "acompletion", completion)

    async def run():
        with ai_router.ai_request_scope():
            await ai_router.call_ai("analyzer", [{"role": "user", "content": "test"}])
            await ai_router.call_ai("strategist", [{"role": "user", "content": "test"}])

    with pytest.raises(ai_router.AIProviderError, match="call limit"):
        asyncio.run(run())
    assert calls == 1


def test_model_fast_routes_only_analyzer_and_reviewer(monkeypatch):
    models = []

    async def completion(**kwargs):
        models.append(kwargs["model"])
        return _response()

    monkeypatch.setattr(ai_router.settings, "model_fast", "gemini-fast-test")
    monkeypatch.setattr(ai_router, "get_agent_model", lambda *_: ("gemini", "gemini/gemini-main-test"))
    monkeypatch.setattr(ai_router, "acompletion", completion)

    async def run():
        await ai_router.call_ai("analyzer", [{"role": "user", "content": "test"}])
        await ai_router.call_ai("coder", [{"role": "user", "content": "test"}])

    asyncio.run(run())
    assert models == ["gemini/gemini-fast-test", "gemini/gemini-main-test"]


def test_quota_text_never_invents_limit_type_or_retry_time():
    error = ai_router.RateLimitHit(
        "gemini", "Gemini (gemini/gemini-test)", "provider error", retry_after_seconds=None,
    )
    assert "Gemini quota exceeded (limit type not reported)" in str(error)
    assert error.retry_after_seconds is None
    assert ai_router._rate_limit_type("quota exceeded per day") == "daily"
    assert ai_router._rate_limit_type("quota exceeded per minute") == "per-minute"
    assert ai_router._rate_limit_type("GenerateContentRequestsPerMinutePerProject") == "per-minute"
