import base64
import asyncio
import hashlib
import hmac
import json
import secrets
import uuid
import ipaddress
import platform
from datetime import datetime, timedelta, timezone
from io import BytesIO
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from typing import Optional

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded

from config import settings, _configured_worker_count
from logger import log
from utils import job_store
from orchestrator import solve_problem
from utils.ai_router import (
    get_usage_stats,
    get_ai_config_summary,
    reset_usage_stats,
    RateLimitHit,
    call_ai,
    AIProviderError,
    ai_request_scope,
    ai_progress_scope,
)
from agents.all_agents import AgentFailure
from memory.brain import (
    get_temporal_insights,
    _load_json,
    _save_json,
    EPISODIC_FILE,
    SEMANTIC_FILE,
    PROCEDURAL_FILE,
    TEMPORAL_FILE,
    DEFAULT_PROCEDURES,
    sanitize_user_id,
    _user_memory_file,
    CHROMA_AVAILABLE,
    _episodic_col,
    _semantic_col,
    reset_user_memory,
    get_procedures,
    reset_user_metadata,
)


SESSION_COOKIE = "solvex_guest"
CSRF_COOKIE = "solvex_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_redis_client = None
_solve_jobs: dict[str, dict] = {}
_WINDOW_INCR_SCRIPT = "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],ARGV[1]) end; return {n,redis.call('TTL',KEYS[1])}"
_DAILY_INCR_SCRIPT = "local n=redis.call('INCR',KEYS[1]); local ttl=redis.call('TTL',KEYS[1]); if n==1 or ttl<0 then redis.call('EXPIREAT',KEYS[1],ARGV[1]); ttl=redis.call('TTL',KEYS[1]); end; return {n,ttl}"


def _trusted_proxy_networks():
    return tuple(ipaddress.ip_network(item.strip(), strict=False) for item in settings.trusted_proxies.split(",") if item.strip())


def _is_trusted_ip(value: str, networks=None) -> bool:
    networks = _trusted_proxy_networks() if networks is None else networks
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return any(address.version == network.version and address in network for network in networks)


def get_client_ip(request: Request) -> str:
    peer = request.client.host if request.client else "unknown"
    networks = _trusted_proxy_networks()
    if not _is_trusted_ip(peer, networks):
        return peer
    for forwarded in reversed(request.headers.get("x-forwarded-for", "").split(",")):
        candidate = forwarded.strip()
        try:
            ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if not _is_trusted_ip(candidate, networks):
            return candidate
    return peer


def _get_redis():
    global _redis_client
    if _redis_client is None and settings.rate_limit_storage_uri != "memory://":
        import redis
        _redis_client = redis.Redis.from_url(settings.rate_limit_storage_uri, decode_responses=True)
    return _redis_client


def _redis_window_hit(key: str, seconds: int) -> tuple[int, int]:
    client = _get_redis()
    if client is None:
        raise RuntimeError("Redis rate-limit storage is not configured")
    count, ttl = client.eval(_WINDOW_INCR_SCRIPT, 1, key, seconds)
    return int(count), max(1, int(ttl))


def _new_guest_allowed(request: Request):
    if getattr(request.state, "rate_limit_allow", False):
        return
    try:
        count, ttl = _redis_window_hit(f"solvex:new-guest:{get_client_ip(request)}", 3600)
    except Exception as exc:
        if settings.app_env == "production":
            log.error("rate_limit_redis_unavailable", path=request.url.path, error=str(exc))
            raise HTTPException(503, "Rate limiting is temporarily unavailable.")
        log.warning("RATE LIMIT WARNING: Redis unavailable; allowing guest creation in development", error=str(exc))
        request.state.rate_limit_allow = True
        return
    if count > settings.new_guests_per_ip_per_hour:
        raise HTTPException(429, "Guest session limit reached for this IP.", headers={"Retry-After": str(ttl)})


def _consume_global_solve_cap(request: Request):
    if getattr(request.state, "rate_limit_allow", False):
        return
    try:
        client = _get_redis()
        if client is None:
            raise RuntimeError("Redis rate-limit storage is not configured")
        now = datetime.now(timezone.utc)
        tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        day = now.strftime("%Y-%m-%d")
        count, ttl = client.eval(_DAILY_INCR_SCRIPT, 1, f"solvex:global-solves:{day}", int(tomorrow.timestamp()))
    except Exception as exc:
        if settings.app_env == "production":
            log.error("rate_limit_redis_unavailable", path=request.url.path, error=str(exc))
            raise HTTPException(503, "Rate limiting is temporarily unavailable.")
        log.warning("RATE LIMIT WARNING: Redis unavailable; allowing solve in development", error=str(exc))
        request.state.rate_limit_allow = True
        return
    if int(count) > settings.global_daily_solve_cap:
        raise HTTPException(429, {"error": "rate_limit", "message": "The global daily solve limit has been reached."}, headers={"Retry-After": str(max(1, int(ttl)))})


def _session_secret() -> bytes:
    secret = settings.guest_session_secret or settings.app_secret_key
    if not secret:
        secret = "development-only-guest-session-secret"
    return secret.encode("utf-8")


def _sign_guest_id(guest_id: str) -> str:
    signature = hmac.new(_session_secret(), guest_id.encode(), hashlib.sha256).hexdigest()
    return f"{guest_id}.{signature}"


def _verify_guest_cookie(value: Optional[str]) -> Optional[str]:
    if not value or "." not in value:
        return None
    guest_id, signature = value.rsplit(".", 1)
    if not guest_id.startswith("guest_"):
        return None
    expected = hmac.new(_session_secret(), guest_id.encode(), hashlib.sha256).hexdigest()
    return guest_id if hmac.compare_digest(signature, expected) else None


async def get_current_user(request: Request, response: Response) -> str:
    guest_id = _verify_guest_cookie(request.cookies.get(SESSION_COOKIE))
    new_session = guest_id is None
    if new_session:
        _new_guest_allowed(request)
        guest_id = f"guest_{secrets.token_urlsafe(24)}"
        csrf_token = secrets.token_urlsafe(32)
        response.set_cookie(SESSION_COOKIE, _sign_guest_id(guest_id), httponly=True, samesite="lax", secure=settings.app_env == "production")
        response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, samesite="lax", secure=settings.app_env == "production")
    elif request.method not in SAFE_METHODS:
        csrf_cookie = request.cookies.get(CSRF_COOKIE)
        if not csrf_cookie or not hmac.compare_digest(csrf_cookie, request.headers.get("X-CSRF-Token", "")):
            raise HTTPException(status_code=403, detail="CSRF token missing or invalid.")
    return guest_id


verify_api_key = get_current_user


def get_rate_limit_key(request: Request) -> str:
    return "" if getattr(request.state, "rate_limit_allow", False) else get_client_ip(request)


def get_guest_rate_limit_key(request: Request) -> str:
    return "" if getattr(request.state, "rate_limit_allow", False) else (_verify_guest_cookie(request.cookies.get(SESSION_COOKIE)) or "")


limiter = Limiter(
    key_func=get_rate_limit_key,
    storage_uri=settings.rate_limit_storage_uri,
    headers_enabled=True,
    in_memory_fallback=["1000000000/minute"] if settings.app_env != "production" else [],
    in_memory_fallback_enabled=settings.app_env != "production",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("solvex_startup", env=settings.app_env, log_level=settings.log_level)
    if settings.app_env != "production":
        log.warning("Development mode: rate limits fail open if Redis is down; CORS may be permissive.")
    key_statuses = settings.provider_key_statuses
    for provider, status in key_statuses.items():
        log.info("ai_provider_key_status", provider=provider, status=status)
    configured = [provider for provider, status in key_statuses.items() if status == "configured"]
    log.info("ai_keys_loaded", configured=configured)
    if not configured:
        log.error(
            "no_ai_provider_key_configured",
            msg="No valid AI provider key is configured. Health checks remain available; solve requests will return 503.",
        )
    if settings.app_env == "production" and settings.redis_url:
        import redis
        redis.Redis.from_url(settings.redis_url).ping()
    yield
    log.info("solvex_shutdown")


app = FastAPI(
    title="SolveX v2",
    description="5-Agent Agentic DSA Solver — Multi-AI + 4-Layer Brain",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
@app.exception_handler(RateLimitExceeded)
async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
    response = JSONResponse(status_code=429, content={"detail": {"error": "rate_limit", "message": "Rate limit exceeded."}})
    limiter._inject_headers(response, getattr(request.state, "view_rate_limit", None))
    if "Retry-After" not in response.headers:
        response.headers["Retry-After"] = "60"
    return response


@app.middleware("http")
async def require_redis_for_protected_endpoints(request: Request, call_next):
    if request.url.path in {"/health/detailed", "/usage/reset"}:
        if not settings.admin_token:
            return await call_next(request)
        try:
            count, ttl = _redis_window_hit(
                f"solvex:admin:{get_client_ip(request)}", 60
            )
        except Exception as exc:
            if settings.app_env == "production":
                log.error("admin_rate_limit_redis_unavailable", path=request.url.path, error=str(exc))
                return JSONResponse(status_code=503, content={"detail": "Admin rate limiting is temporarily unavailable."})
            log.warning("ADMIN RATE LIMIT WARNING: Redis unavailable; allowing request in development", path=request.url.path, error=str(exc))
        else:
            if count > 10:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Admin request limit exceeded."},
                    headers={"Retry-After": str(ttl)},
                )
    if request.url.path not in {"/solve", "/solve-image", "/explain"}:
        return await call_next(request)
    try:
        client = _get_redis()
        if client is None:
            raise RuntimeError("Redis rate-limit storage is not configured")
        client.ping()
    except Exception as exc:
        if request.url.path == "/explain":
            if settings.app_env == "production":
                log.error("explain_cache_redis_unavailable", error=str(exc))
            else:
                log.warning("explain_cache_redis_unavailable", error=str(exc))
            request.state.rate_limit_allow = True
        elif settings.app_env == "production":
            log.error("rate_limit_redis_unavailable", path=request.url.path, error=str(exc))
            return JSONResponse(status_code=503, content={"detail": "Rate limiting is temporarily unavailable."})
        else:
            log.warning("RATE LIMIT WARNING: Redis unavailable; allowing protected endpoint in development", path=request.url.path, error=str(exc))
            request.state.rate_limit_allow = True
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials="*" not in settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    log.error("unhandled_exception", path=request.url.path, request_id=request_id, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id}
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if (
        isinstance(exc.detail, dict)
        and exc.detail.get("code") in {"ai_key_missing", "ai_auth_failed", "ai_provider_timeout"}
    ):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )
    if exc.status_code < 500:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    log.error("internal_http_exception", path=request.url.path, request_id=request_id, error=str(exc.detail))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers=exc.headers,
    )


class SolveRequest(BaseModel):
    problem:             str
    language:            str = "python"
    manual_ai_overrides: Optional[dict] = None

    @field_validator("problem")
    @classmethod
    def validate_problem(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("problem must not be empty")
        return v

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        allowed = {"python", "cpp", "java"}
        if v not in allowed:
            raise ValueError(f"language must be one of: {allowed}")
        return v


class ExplainRequest(BaseModel):
    problem: str
    final_code: str
    chosen_approach: str = ""
    reasoning_chain: str = ""
    language: str = "python"

    @field_validator("language")
    @classmethod
    def validate_explain_language(cls, v: str) -> str:
        if v not in {"python", "cpp", "java"}:
            raise ValueError("language must be python, cpp, or java")
        return v

    @field_validator("problem", "final_code", "chosen_approach", "reasoning_chain")
    @classmethod
    def validate_explain_text(cls, v: str) -> str:
        if not isinstance(v, str):
            raise ValueError("explanation fields must be strings")
        return v


def _explanation_cache_key(user_id: str, req: ExplainRequest) -> str:
    material = f"{req.final_code}\0{req.language}\0{req.problem}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return f"explain:{user_id}:{digest}"


def _get_cached_explanation(key: str) -> Optional[str]:
    try:
        client = _get_redis()
        return client.get(key) if client is not None else None
    except Exception as exc:
        log.warning("explain_cache_read_failed", error=str(exc))
        return None


def _cache_explanation(key: str, explanation: str) -> None:
    try:
        client = _get_redis()
        if client is not None:
            client.setex(key, settings.explain_cache_ttl_seconds, explanation)
    except Exception as exc:
        log.warning("explain_cache_write_failed", error=str(exc))

    @field_validator("problem")
    @classmethod
    def validate_problem(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("problem cannot be empty")
        if len(v) > 50_000:
            raise ValueError("problem too long (max 50,000 chars)")
        return v


def _handle_rate_limit(e: RateLimitHit):
    headers = (
        {"Retry-After": str(e.retry_after_seconds)}
        if e.retry_after_seconds is not None
        else None
    )
    error = HTTPException(
        status_code=429,
        detail={
            "error":    "rate_limit",
            "ai":       e.ai_key,
            "ai_label": e.ai_label,
            "message":  str(e),
        }
    )
    error.headers = headers
    raise error


async def _execute_solve_job(job_id: str, problem: str, language: str, overrides: Optional[dict], user_id: str) -> None:
    job = _solve_jobs.get(job_id)
    if job is None:
        return

    def record_event(event: dict) -> None:
        job["events"].append(event)
        job_store.save(job_id, job)

    try:
        with ai_request_scope() as timings, ai_progress_scope(record_event):
            result = await asyncio.wait_for(solve_problem(
                problem=problem,
                language=language,
                manual_ai_overrides=overrides,
                user_id=user_id,
            ), timeout=settings.job_max_seconds)
        result["timings"] = timings
        job["result"] = result
        job["status"] = "complete"
    except asyncio.TimeoutError:
        job["error"] = {"code": "job_timeout", "message": "Solving timed out. Please run it again."}
        job["status"] = "failed"
    except RateLimitHit as exc:
        job["error"] = {
            "type": "rate_limit", "ai": exc.ai_key, "ai_label": exc.ai_label,
            "message": str(exc), "retry_after": exc.retry_after_seconds,
        }
        job["status"] = "failed"
    except AgentFailure as exc:
        job["error"] = {"code": exc.code or "agent_failed", "message": exc.reason}
        job["status"] = "failed"
    except Exception:
        log.exception("solve_job_failed", job_id=job_id, request_id=job["request_id"])
        job["error"] = {"code": "solve_failed", "message": "Solve failed. Check the backend log."}
        job["status"] = "failed"

    if job["error"] is not None:
        job["error"]["request_id"] = job["request_id"]
    job_store.save(job_id, job)


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}



@app.get("/health")
async def health():
    return {"status": "ok"}


async def require_admin_token(request: Request) -> None:
    token = settings.admin_token
    if token is None:
        raise HTTPException(status_code=404, detail="Not found.")
    supplied = request.headers.get("X-Admin-Token", "")
    if not secrets.compare_digest(supplied, token):
        raise HTTPException(status_code=403, detail="Admin access required.")


@app.get("/health/detailed")
async def health_detailed(_admin: None = Depends(require_admin_token)):
    redis_reachable = False
    try:
        client = _get_redis()
        if client is not None:
            client.ping()
            redis_reachable = True
    except Exception:
        redis_reachable = False
    return {
        "memory_backend": settings.memory_backend,
        "redis_reachable": redis_reachable,
        "judge0_configured": bool(settings.judge0_api_key),
        "python_version": platform.python_version(),
        "app_version": app.version,
        "worker_count": _configured_worker_count(),
    }


@app.post("/solve")
@limiter.limit(settings.guest_solve_rate_limit, key_func=get_guest_rate_limit_key)
@limiter.limit(settings.ip_solve_daily_rate_limit, key_func=get_rate_limit_key)
@limiter.limit(settings.ip_solve_rate_limit, key_func=get_rate_limit_key)
async def solve_text(request: Request, response: Response, req: SolveRequest, user_id: str = Depends(get_current_user)):
    if not any(settings.available_keys.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ai_key_missing",
                "message": "No AI provider key is configured. Add one to backend/.env and restart.",
            },
        )

    log.info("solve_request", language=req.language,
             problem_len=len(req.problem), mode="text")
    _consume_global_solve_cap(request)
    try:
        with ai_request_scope() as timings:
            result = await solve_problem(
                problem=req.problem,
                language=req.language,
                image_base64=None,
                manual_ai_overrides=req.manual_ai_overrides,
                user_id=user_id,
            )
        result["timings"] = timings
        return result
    except RateLimitHit as e:
        _handle_rate_limit(e)
    except AgentFailure as e:
        log.error("solve_agent_failure", agent=e.agent, reason=e.reason)
        if e.code == "ai_auth_failed":
            raise HTTPException(
                status_code=502,
                detail={"code": e.code, "message": e.reason},
            )
        if e.code == "ai_provider_timeout":
            raise HTTPException(
                status_code=504,
                detail={"code": e.code, "message": e.reason},
            )
        raise HTTPException(status_code=502, detail="AI provider failure.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("solve_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/solve/jobs", status_code=202)
@limiter.limit(settings.guest_solve_rate_limit, key_func=get_guest_rate_limit_key)
@limiter.limit(settings.ip_solve_daily_rate_limit, key_func=get_rate_limit_key)
@limiter.limit(settings.ip_solve_rate_limit, key_func=get_rate_limit_key)
async def start_solve_job(request: Request, req: SolveRequest, user_id: str = Depends(get_current_user)):
    if not settings.solvex_mock_ai and not any(settings.available_keys.values()):
        raise HTTPException(status_code=503, detail={"code": "ai_key_missing", "message": "No AI provider key is configured."})
    _consume_global_solve_cap(request)
    job_id = uuid.uuid4().hex
    if len(_solve_jobs) >= 100:
        for old_id in list(_solve_jobs):
            if _solve_jobs[old_id]["status"] != "running":
                del _solve_jobs[old_id]
                if len(_solve_jobs) < 90:
                    break
    if len(_solve_jobs) >= 100:
        raise HTTPException(status_code=503, detail="The local solve queue is full. Try again shortly.")
    _solve_jobs[job_id] = {
        "request_id": request.state.request_id,
        "user_id": user_id,
        "status": "running",
        "events": [],
        "result": None,
        "error": None,
    }
    job_store.save(job_id, _solve_jobs[job_id])
    asyncio.create_task(_execute_solve_job(
        job_id, req.problem, req.language, req.manual_ai_overrides, user_id,
    ))
    return {"job_id": job_id, "status": "running", "max_seconds": settings.job_max_seconds}


@app.get("/solve/jobs/{job_id}")
async def get_solve_job(job_id: str, user_id: str = Depends(get_current_user)):
    job = _solve_jobs.get(job_id) or job_store.load(job_id)
    if job is None or job["user_id"] != user_id:
        raise HTTPException(status_code=404, detail={
            "code": "job_not_found",
            "message": "The server restarted while solving. Please run it again.",
        })
    return {
        "status": job["status"],
        "events": list(job["events"]),
        "result": job["result"],
        "error": job["error"],
    }


@app.post("/explain")
@limiter.limit(settings.guest_solve_rate_limit, key_func=get_guest_rate_limit_key)
@limiter.limit(settings.ip_solve_daily_rate_limit, key_func=get_rate_limit_key)
@limiter.limit(settings.ip_solve_rate_limit, key_func=get_rate_limit_key)
async def explain_solution(
    request: Request,
    response: Response,
    req: ExplainRequest,
    user_id: str = Depends(get_current_user),
):
    if not any(settings.available_keys.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ai_key_missing",
                "message": "No AI provider key is configured. Add one to backend/.env and restart.",
            },
        )
    total_chars = sum(len(value) for value in (
        req.problem, req.final_code, req.chosen_approach, req.reasoning_chain,
    ))
    if total_chars > 50_000:
        raise HTTPException(status_code=422, detail="Explanation input too long (max 50,000 chars).")

    cache_key = _explanation_cache_key(user_id, req)
    cached_explanation = _get_cached_explanation(cache_key)
    if cached_explanation is not None:
        return {"explanation": cached_explanation, "cached": True}

    try:
        with ai_request_scope():
            explanation, _ = await call_ai(
                role="strategist",
                messages=[
                {
                    "role": "system",
                    "content": (
                        "Explain the supplied competitive-programming solution plainly. "
                        "Use the chosen approach and reasoning as context, but do not rewrite code. "
                        "Return only a clear plain-text explanation with algorithm steps, correctness intuition, "
                        "complexity, and a short walkthrough."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Language: {req.language}\nProblem:\n{req.problem}\n\n"
                        f"Chosen approach:\n{req.chosen_approach}\n\n"
                        f"Reasoning chain:\n{req.reasoning_chain}\n\n"
                        f"Final code:\n{req.final_code}"
                    ),
                },
                ],
            )
    except RateLimitHit as e:
        _handle_rate_limit(e)
    except (AIProviderError, ValueError) as e:
        log.error("explain_ai_error", error=str(e))
        if isinstance(e, AIProviderError) and e.code == "ai_auth_failed":
            raise HTTPException(status_code=502, detail={"code": e.code, "message": str(e)})
        if isinstance(e, AIProviderError) and e.code == "ai_provider_timeout":
            raise HTTPException(status_code=504, detail={"code": e.code, "message": str(e)})
        raise HTTPException(status_code=502, detail="AI provider failure.")
    except Exception as e:
        log.error("explain_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")

    if not explanation or not explanation.strip():
        raise HTTPException(status_code=502, detail="AI provider returned an empty explanation.")
    explanation = explanation.strip()
    _cache_explanation(cache_key, explanation)
    return {"explanation": explanation, "cached": False}


@app.post("/solve-image")
@limiter.limit(settings.guest_solve_rate_limit, key_func=get_guest_rate_limit_key)
@limiter.limit(settings.ip_solve_daily_rate_limit, key_func=get_rate_limit_key)
@limiter.limit(settings.ip_solve_rate_limit, key_func=get_rate_limit_key)
async def solve_image(
    request:             Request,
    response:            Response,
    image:               UploadFile = File(...),
    language:            str        = Form(default="python"),
    extra_text:          str        = Form(default=""),
    manual_ai_overrides: str        = Form(default="{}"),
    user_id: str                    = Depends(get_current_user),
):
    if language not in {"python", "cpp", "java"}:
        raise HTTPException(400, "language must be python, cpp, or java")

    if not any(settings.available_keys.values()):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "ai_key_missing",
                "message": "No AI provider key is configured. Add one to backend/.env and restart.",
            },
        )

    image_bytes = await image.read()
    if len(image_bytes) > 10 * 1024 * 1024:
        raise HTTPException(413, "Image too large. Max 10MB.")

    try:
        from PIL import Image
        with Image.open(BytesIO(image_bytes)) as decoded:
            detected_type = {
                "PNG": "image/png",
                "JPEG": "image/jpeg",
                "WEBP": "image/webp",
            }.get(decoded.format)
            decoded.verify()
    except Exception as e:
        log.warning("invalid_image_upload", error=str(e))
        raise HTTPException(415, "Unsupported or invalid image. Allowed formats: PNG, JPEG, WebP.")

    if detected_type is None:
        raise HTTPException(415, "Unsupported image format. Allowed formats: PNG, JPEG, WebP.")

    image_base64 = base64.b64encode(image_bytes).decode("utf-8")

    try:
        overrides = json.loads(manual_ai_overrides)
    except json.JSONDecodeError:
        overrides = {}

    log.info("solve_request", language=language, mode="image",
             image_size=len(image_bytes))
    _consume_global_solve_cap(request)
    try:
        with ai_request_scope() as timings:
            result = await solve_problem(
                problem=extra_text or "Solve the competitive programming problem in this image.",
                language=language,
                image_base64=image_base64,
                manual_ai_overrides=overrides,
                user_id=user_id,
                image_mime_type=detected_type,
            )
        result["timings"] = timings
        return result
    except RateLimitHit as e:
        _handle_rate_limit(e)
    except AgentFailure as e:
        log.error("solve_image_agent_failure", agent=e.agent, reason=e.reason)
        if e.code == "ai_auth_failed":
            raise HTTPException(
                status_code=502,
                detail={"code": e.code, "message": e.reason},
            )
        if e.code == "ai_provider_timeout":
            raise HTTPException(
                status_code=504,
                detail={"code": e.code, "message": e.reason},
            )
        raise HTTPException(status_code=502, detail="AI provider failure.")
    except Exception as e:
        log.error("solve_image_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/ai-config")
async def ai_config(user_id: str = Depends(get_current_user)):
    return get_ai_config_summary()


@app.get("/usage")
async def usage(user_id: str = Depends(get_current_user)):
    return {**get_usage_stats(), "scope": "server"}


@app.post("/usage/reset")
async def usage_reset(_admin: None = Depends(require_admin_token)):
    reset_usage_stats()
    return {"status": "reset"}


@app.get("/brain/stats")
async def brain_stats(user_id: str = Depends(get_current_user)):
    episodic = _load_json(_user_memory_file(user_id, "episodic.json"))
    semantic = _load_json(_user_memory_file(user_id, "semantic.json"))
    procedures = get_procedures(user_id)

    entries  = episodic.get("entries", [])
    patterns = semantic.get("patterns", [])
    passed   = sum(1 for e in entries if e.get("passed"))
    total    = len(entries)

    langs: dict[str, int] = {}
    for e in entries:
        l = e.get("language", "unknown")
        langs[l] = langs.get(l, 0) + 1

    return {
        "total_attempts":   total,
        "total_passed":     passed,
        "pass_rate":        round((passed / max(total, 1)) * 100, 1),
        "patterns_learned": len(patterns),
        "languages_used":   langs,
        "procedures_count": len(procedures),
        "recent_solves": [
            {
                "problem":    e.get("problem", "")[:80],
                "approach":   e.get("approach", ""),
                "language":   e.get("language", ""),
                "iterations": e.get("iterations", 1),
                "passed":     e.get("passed", False),
                "timestamp":  e.get("timestamp", ""),
            }
            for e in reversed(entries[-5:])
        ],
    }


@app.get("/brain/temporal")
async def brain_temporal(user_id: str = Depends(get_current_user)):
    return get_temporal_insights(user_id)


@app.get("/brain/procedures")
async def brain_procedures(user_id: str = Depends(get_current_user)):
    procedures = get_procedures(user_id)
    return {
        "procedures":   procedures,
        "last_updated": "SQLite WAL",
    }


@app.post("/brain/reset")
async def brain_reset(user_id: str = Depends(get_current_user)):
    deleted = reset_user_memory(user_id)
    deleted.update(reset_user_metadata(user_id))
    for path, key in [
        (_user_memory_file(user_id, "episodic.json"), "entries"),
        (_user_memory_file(user_id, "semantic.json"), "patterns"),
        (_user_memory_file(user_id, "temporal.json"), "events"),
    ]:
        data = _load_json(path)
        deleted[key] = len(data.get(key, []))
        _save_json(path, {})
    log.info("brain_reset")
    return {"message": "All memory cleared. Brain reset to defaults.", "deleted": deleted}


RELOAD_EXCLUDES = ["memory", "venv", "*.sqlite*", "*.db", "__pycache__"]
RELOAD_INCLUDES = ["*.py", ".env"]


if __name__ == "__main__":
    import uvicorn
    import os

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("BACKEND_PORT", "8000")),
        reload=settings.app_env == "development",
        reload_includes=RELOAD_INCLUDES,
        reload_excludes=RELOAD_EXCLUDES,
        log_level=settings.log_level.lower(),
    )
