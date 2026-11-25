import os
import importlib
from unittest.mock import AsyncMock, patch

os.environ.setdefault("OPENAI_API_KEY", "fake-key-for-tests-0123456789")

from fastapi.testclient import TestClient

import main
from redis_fakes import FakeRedis


def test_explain_uses_one_cached_strategist_call_without_orchestrator(monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(main, "_redis_client", fake_redis)
    main.limiter._storage.reset()
    client = TestClient(main.app)
    payload = {
        "problem": "Find the sum of two numbers.",
        "final_code": "print(sum(map(int, input().split())))",
        "chosen_approach": "Direct addition",
        "reasoning_chain": "Read two integers and add them.",
        "language": "python",
    }

    with patch("main.call_ai", new_callable=AsyncMock) as call_ai, patch(
        "main.solve_problem", new_callable=AsyncMock
    ) as solve_problem:
        call_ai.return_value = ("Add the two input values and print the result.", "claude")
        first = client.post("/explain", json=payload)
        second = client.post(
            "/explain",
            json=payload,
            headers={"X-CSRF-Token": client.cookies.get("solvex_csrf")},
        )

    assert first.status_code == 200
    assert first.json() == {
        "explanation": "Add the two input values and print the result.",
        "cached": False,
    }
    assert second.status_code == 200
    assert second.json() == {
        "explanation": "Add the two input values and print the result.",
        "cached": True,
    }
    call_ai.assert_awaited_once()
    assert call_ai.await_args.kwargs["role"] == "strategist"
    solve_problem.assert_not_awaited()
    guest_id = main._verify_guest_cookie(client.cookies.get(main.SESSION_COOKIE))
    key = main._explanation_cache_key(guest_id, main.ExplainRequest(**payload))
    assert key.startswith(f"explain:{guest_id}:")
    assert fake_redis.values[f"ttl:{key}"] == main.settings.explain_cache_ttl_seconds == 604800


def test_explain_cache_survives_reimporting_main(monkeypatch):
    fake_redis = FakeRedis()
    call_ai = AsyncMock(return_value=("Persistent explanation", "test-provider"))
    monkeypatch.setattr(main, "_redis_client", fake_redis)
    monkeypatch.setattr(main, "call_ai", call_ai)
    main.limiter._storage.reset()
    payload = {
        "problem": "Cache survives module reload.",
        "final_code": "print(42)",
        "language": "python",
    }
    client_a = TestClient(main.app)
    first = client_a.post("/explain", json=payload)
    assert first.status_code == 200
    assert first.json()["cached"] is False

    importlib.reload(main)
    monkeypatch.setattr(main, "_redis_client", fake_redis)
    monkeypatch.setattr(main, "call_ai", call_ai)
    client_b = TestClient(main.app)
    client_b.cookies.update(client_a.cookies)
    second = client_b.post(
        "/explain", json=payload,
        headers={"X-CSRF-Token": client_b.cookies.get("solvex_csrf")},
    )
    assert second.status_code == 200
    assert second.json() == {"explanation": "Persistent explanation", "cached": True}
    call_ai.assert_awaited_once()


def test_explain_redis_down_skips_cache_and_still_calls_ai(monkeypatch):
    monkeypatch.setattr(main, "_redis_client", FakeRedis(unavailable=True))
    monkeypatch.setattr(main.settings, "app_env", "development")
    main.limiter._storage.reset()
    client = TestClient(main.app)
    client.get("/brain/stats")
    monkeypatch.setattr(main.settings, "app_env", "production")
    payload = {
        "problem": "Explain while Redis is down.",
        "final_code": "print(7)",
        "language": "python",
    }
    with patch("main.call_ai", new_callable=AsyncMock) as call_ai:
        call_ai.side_effect = [
            ("First explanation", "test-provider"),
            ("Second explanation", "test-provider"),
        ]
        headers = {"X-CSRF-Token": client.cookies.get("solvex_csrf")}
        first = client.post("/explain", json=payload, headers=headers)
        second = client.post(
            "/explain", json=payload,
            headers=headers,
        )
    assert first.status_code == second.status_code == 200
    assert first.json() == {"explanation": "First explanation", "cached": False}
    assert second.json() == {"explanation": "Second explanation", "cached": False}
    assert call_ai.await_count == 2


def test_explain_rejects_oversized_input():
    client = TestClient(main.app)
    response = client.post(
        "/explain",
        json={
            "problem": "x" * 50_001,
            "final_code": "print(1)",
            "language": "python",
        },
    )
    assert response.status_code == 422
