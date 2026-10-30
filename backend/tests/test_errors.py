import os
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "test-placeholder")

from main import app


def test_internal_error_is_generic_and_has_request_id():
    client = TestClient(app, raise_server_exceptions=False)
    with patch("main.solve_problem", new_callable=AsyncMock) as solve:
        solve.side_effect = RuntimeError("provider secret should not leak")
        response = client.post(
            "/solve",
            json={"problem": "test", "language": "python"},
        )

    assert response.status_code == 500
    body = response.json()
    assert body["detail"] == "Internal server error"
    assert body["request_id"]
    assert "provider secret" not in response.text