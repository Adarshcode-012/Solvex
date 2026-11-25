import asyncio
from types import SimpleNamespace

import utils.ai_router as ai_router


def test_completion_receives_configured_timeout(monkeypatch):
    captured = {}

    async def fake_completion(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )

    monkeypatch.setattr(ai_router, "get_agent_model", lambda *_args: ("openai", "openai/test"))
    monkeypatch.setattr(ai_router, "acompletion", fake_completion)

    asyncio.run(ai_router.call_ai("coder", [{"role": "user", "content": "test"}]))

    assert captured["timeout"] == ai_router.settings.ai_request_timeout_seconds == 120
