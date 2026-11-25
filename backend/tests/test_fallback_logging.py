from unittest.mock import Mock
from types import SimpleNamespace

import utils.ai_router as ai_router


def test_only_first_provider_fallback_per_request_logs_warning(monkeypatch):
    monkeypatch.setattr(
        ai_router,
        "settings",
        SimpleNamespace(
            available_keys={"claude": False, "gpt4o": False, "gpt4o_mini": False, "gemini": True}
        ),
    )
    warning = Mock()
    info = Mock()
    monkeypatch.setattr(ai_router.log, "warning", warning)
    monkeypatch.setattr(ai_router.log, "info", info)

    with ai_router.ai_request_scope():
        for role in ("analyzer", "strategist", "coder", "reviewer", "judge"):
            assert ai_router.get_agent_model(role)[0] == "gemini"

    warning.assert_called_once()
    assert warning.call_args.kwargs["using"] == "gemini"
    info.assert_not_called()
