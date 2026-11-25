import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("OPENAI_API_KEY", "fake-key-for-tests-0123456789")

from fastapi.testclient import TestClient

import main
from redis_fakes import FakeRedis


def test_explain_cache_is_isolated_between_guests(monkeypatch):
    monkeypatch.setattr(main, "_redis_client", FakeRedis())
    main.limiter._storage.reset()
    guest_a = TestClient(main.app)
    guest_b = TestClient(main.app)
    payload = {
        "problem": "Find the sum of two numbers.",
        "final_code": "print(sum(map(int, input().split())))",
        "chosen_approach": "Direct addition",
        "reasoning_chain": "Read two integers and add them.",
        "language": "python",
    }

    with patch("main.call_ai", new_callable=AsyncMock) as call_ai:
        call_ai.return_value = ("A guest-only explanation", "test-provider")
        first = guest_a.post("/explain", json=payload)
        second = guest_b.post("/explain", json=payload)

    assert first.status_code == second.status_code == 200
    assert first.json() == {
        "explanation": "A guest-only explanation",
        "cached": False,
    }
    assert second.json() == {
        "explanation": "A guest-only explanation",
        "cached": False,
    }
    assert call_ai.await_count == 2
