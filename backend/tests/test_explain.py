import os
from unittest.mock import AsyncMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")

from fastapi.testclient import TestClient

import main


def test_explain_uses_one_cached_strategist_call_without_orchestrator():
    main._EXPLANATION_CACHE.clear()
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