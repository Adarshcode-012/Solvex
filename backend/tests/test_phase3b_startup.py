import os

os.environ.setdefault("OPENAI_API_KEY", "fake-key-for-tests-0123456789")

import pytest
from fastapi.testclient import TestClient

import main


def test_development_startup_emits_rate_limit_warning(monkeypatch, capsys):
    warning = "Development mode: rate limits fail open if Redis is down; CORS may be permissive."
    monkeypatch.setattr(main.settings, "app_env", "development")
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
    output = capsys.readouterr().out
    assert output.count(warning) == 1


@pytest.mark.redis
@pytest.mark.skipif(not os.getenv("REDIS_TEST_URL"), reason="set REDIS_TEST_URL to run Redis integration checks")
def test_real_redis_global_cap_and_new_guest_counters(monkeypatch):
    import uuid
    from datetime import datetime, timezone
    from fastapi import HTTPException
    from redis import Redis
    from starlette.requests import Request

    redis_url = os.environ["REDIS_TEST_URL"]
    client = Redis.from_url(redis_url, decode_responses=True)
    client.ping()
    monkeypatch.setattr(main, "_redis_client", client)
    monkeypatch.setattr(main.settings, "rate_limit_storage_uri", redis_url)
    monkeypatch.setattr(main.settings, "global_daily_solve_cap", 1)
    monkeypatch.setattr(main.settings, "new_guests_per_ip_per_hour", 1)

    request = Request({
        "type": "http", "method": "POST", "path": "/solve", "headers": [],
        "client": ("198.51.100.47", 1234), "server": ("localhost", 80),
        "scheme": "http", "query_string": b"", "root_path": "", "state": {},
    })
    day_key = f"solvex:global-solves:{datetime.now(timezone.utc):%Y-%m-%d}"
    guest_ip = f"198.51.100.{uuid.uuid4().int % 254 + 1}"
    guest_key = f"solvex:new-guest:{guest_ip}"
    try:
        client.delete(day_key, guest_key)
        main._consume_global_solve_cap(request)
        with pytest.raises(HTTPException) as global_limit:
            main._consume_global_solve_cap(request)
        assert global_limit.value.status_code == 429
        assert "Retry-After" in global_limit.value.headers

        guest_request = Request({
            "type": "http", "method": "GET", "path": "/brain/stats", "headers": [],
            "client": (guest_ip, 1234), "server": ("localhost", 80),
            "scheme": "http", "query_string": b"", "root_path": "", "state": {},
        })
        main._new_guest_allowed(guest_request)
        with pytest.raises(HTTPException) as guest_limit:
            main._new_guest_allowed(guest_request)
        assert guest_limit.value.status_code == 429
        assert "Retry-After" in guest_limit.value.headers
    finally:
        client.delete(day_key, guest_key)
        client.close()
