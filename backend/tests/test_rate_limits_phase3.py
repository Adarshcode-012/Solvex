import asyncio
import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from starlette.requests import Request

import main
from redis_fakes import FakeRedis


def reset_rate_limits(monkeypatch, *, redis=None):
    main.limiter._storage.reset()
    monkeypatch.setattr(main, "_redis_client", redis or FakeRedis())
    monkeypatch.setattr(main.settings, "app_env", "development")


def solve_client():
    client = TestClient(main.app)
    client.get("/brain/stats")
    return client


def solve_post(client):
    headers = {}
    csrf = client.cookies.get("solvex_csrf")
    if csrf:
        headers["X-CSRF-Token"] = csrf
    return client.post("/solve", json={"problem": "print one", "language": "python"}, headers=headers)


@pytest.mark.asyncio
async def test_five_requests_pass_sixth_is_limited_per_guest(monkeypatch):
    fake_redis = FakeRedis()
    reset_rate_limits(monkeypatch, redis=fake_redis)
    calls = 0

    async def fake_solve_problem(**_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "passed"}

    monkeypatch.setattr(main, "solve_problem", fake_solve_problem)
    client = solve_client()
    statuses = [solve_post(client).status_code for _ in range(6)]
    assert statuses == [200, 200, 200, 200, 200, 429]
    assert calls == 5
    assert solve_post(client).headers.get("Retry-After") is not None


@pytest.mark.asyncio
async def test_clearing_guest_cookie_does_not_reset_ip_budget(monkeypatch):
    reset_rate_limits(monkeypatch)

    async def fake_solve_problem(**_kwargs):
        return {"status": "passed"}

    monkeypatch.setattr(main, "solve_problem", fake_solve_problem)
    client = solve_client()
    statuses = []
    for _ in range(11):
        client.cookies.clear()
        client.get("/brain/stats")
        statuses.append(solve_post(client).status_code)
    assert statuses[:10] == [200] * 10
    assert statuses[10] == 429


def _request(peer, forwarded=""):
    headers = [(b"x-forwarded-for", forwarded.encode())] if forwarded else []
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers,
                    "client": (peer, 1234), "server": ("localhost", 80), "scheme": "http",
                    "query_string": b"", "root_path": ""})


def test_untrusted_peer_cannot_spoof_forwarded_rate_limit_ip(monkeypatch):
    monkeypatch.setattr(main.settings, "trusted_proxies", "10.0.0.0/8")
    request = _request("198.51.100.8", "203.0.113.9")
    assert main.get_rate_limit_key(request) == "198.51.100.8"


def test_trusted_peer_uses_first_untrusted_forwarded_ip(monkeypatch):
    monkeypatch.setattr(main.settings, "trusted_proxies", "10.0.0.0/8")
    request = _request("10.0.0.4", "203.0.113.9, 10.0.0.3")
    assert main.get_rate_limit_key(request) == "203.0.113.9"


def test_new_guest_ip_limit_blocks_guest_21_without_cookie(monkeypatch):
    reset_rate_limits(monkeypatch)
    response = Response()
    for _ in range(20):
        asyncio.run(main.get_current_user(_request("198.51.100.20"), Response()))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.get_current_user(_request("198.51.100.20"), response))
    assert exc.value.status_code == 429
    assert "Retry-After" in exc.value.headers
    assert not response.headers.get("set-cookie")


@pytest.mark.asyncio
async def test_global_solve_cap_rejects_n_plus_one_with_retry_after(monkeypatch):
    reset_rate_limits(monkeypatch)
    monkeypatch.setattr(main.settings, "global_daily_solve_cap", 2)
    calls = 0

    async def fake_solve_problem(**_kwargs):
        nonlocal calls
        calls += 1
        return {"status": "passed"}

    monkeypatch.setattr(main, "solve_problem", fake_solve_problem)
    client = solve_client()
    responses = [solve_post(client) for _ in range(3)]
    assert [r.status_code for r in responses] == [200, 200, 429]
    assert responses[-1].headers.get("Retry-After")
    assert "global daily solve limit" in responses[-1].text.lower()
    assert calls == 2


@pytest.mark.asyncio
async def test_production_redis_outage_rejects_solve_with_503(monkeypatch):
    reset_rate_limits(monkeypatch, redis=FakeRedis(unavailable=True))
    monkeypatch.setattr(main.settings, "app_env", "production")
    called = False

    async def fake_solve_problem(**_kwargs):
        nonlocal called
        called = True
        return {"status": "passed"}

    monkeypatch.setattr(main, "solve_problem", fake_solve_problem)
    response = solve_post(TestClient(main.app))
    assert response.status_code == 503
    assert response.json() == {"detail": "Rate limiting is temporarily unavailable."}
    assert not called
