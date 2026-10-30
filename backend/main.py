import base64
import hashlib
import hmac
import json
import secrets
import uuid
from io import BytesIO
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from typing import Optional

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Config is imported first — fails fast if no AI keys configured
from config import settings
from logger import log
from orchestrator import solve_problem
from utils.ai_router import (
    get_usage_stats,
    get_ai_config_summary,
    reset_usage_stats,
    RateLimitHit,
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
)


# ── Login-free guest identity ─────────────────────────────────────────────────
SESSION_COOKIE = "solvex_guest"
CSRF_COOKIE = "solvex_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


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


# ── Rate limiter (protects the expensive /solve* endpoints from abuse) ────────
def get_rate_limit_key(request: Request) -> str:
    return _verify_guest_cookie(request.cookies.get(SESSION_COOKIE)) or get_remote_address(request)


limiter = Limiter(key_func=get_rate_limit_key)


# ── Lifespan (startup/shutdown logging) ───────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("solvex_startup", env=settings.app_env, log_level=settings.log_level)
    available = settings.available_keys
    configured = [k for k, v in available.items() if v]
    log.info("ai_keys_loaded", configured=configured)
    if not settings.app_secret_key:
        log.warning(
            "app_secret_key_unset",
            msg="APP_SECRET_KEY not set — endpoints are UNPROTECTED. Fine for local dev only."
        )
    yield
    log.info("solvex_shutdown")


app = FastAPI(
    title="SolveX v2",
    description="5-Agent Agentic DSA Solver — Multi-AI + 4-Layer Brain",
    version="2.0.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ──────────────────────────────────────────────────────────────────────
# allow_credentials is False because the app uses header-based auth (X-API-Key),
# not cookies — enabling credentials with a broad origin list serves no purpose
# and only weakens the CORS policy.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials="*" not in settings.cors_origins_list,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security headers ───────────────────────────────────────────────────────────
# Belt-and-suspenders: most deployments will also get these from a reverse
# proxy / platform edge (Railway, Render, nginx, etc), but setting them here
# means the API is self-protecting even served directly.
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


# ── Global exception handler ──────────────────────────────────────────────────
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
    if exc.status_code < 500:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers)
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    log.error("internal_http_exception", path=request.url.path, request_id=request_id, error=str(exc.detail))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "request_id": request_id},
        headers=exc.headers,
    )


# ── Request / Response models ─────────────────────────────────────────────────
class SolveRequest(BaseModel):
    problem:             str
    language:            str = "python"
    manual_ai_overrides: Optional[dict] = None

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        allowed = {"python", "cpp", "java"}
        if v not in allowed:
            raise ValueError(f"language must be one of: {allowed}")
        return v

    @field_validator("problem")
    @classmethod
    def validate_problem(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("problem cannot be empty")
        if len(v) > 50_000:
            raise ValueError("problem too long (max 50,000 chars)")
        return v


# ── Helpers ───────────────────────────────────────────────────────────────────
def _handle_rate_limit(e: RateLimitHit):
    error = HTTPException(
        status_code=429,
        detail={
            "error":    "rate_limit",
            "ai":       e.ai_key,
            "ai_label": e.ai_label,
            "message":  str(e),
        }
    )
    error.headers = {"Retry-After": "60"}
    raise error


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """
    Public liveness check — no auth required, no secrets returned.
    Load balancers / uptime monitors can hit this freely.
    """
    return {"status": "ok"}


@app.get("/health/detailed")
async def health_detailed(user_id: str = Depends(get_current_user)):
    """
    Returns server health + which AI keys are configured.
    Protected: which providers are wired up is not something to expose publicly.
    """
    raise HTTPException(status_code=403, detail="Admin access required.")


@app.post("/solve")
@limiter.limit(settings.solve_rate_limit)
async def solve_text(request: Request, req: SolveRequest, user_id: str = Depends(get_current_user)):
    """
    Main solve endpoint — text problem in, verified solution out.
    Takes 30-90 seconds (5 agent calls + up to 5 Judge iterations).
    Protected + rate-limited: each call can be 10-25 paid AI calls.
    """
    log.info("solve_request", language=req.language,
             problem_len=len(req.problem), mode="text")
    try:
        result = await solve_problem(
            problem=req.problem,
            language=req.language,
            image_base64=None,
            manual_ai_overrides=req.manual_ai_overrides,
            user_id=user_id,
        )
        return result
    except RateLimitHit as e:
        _handle_rate_limit(e)
    except AgentFailure as e:
        # An AI provider call failed (bad/expired key, empty response, etc) —
        # this used to be silently swallowed and reported as a fake "passed"
        # result. Now it's a real error: 502 because the failure is in an
        # upstream AI provider, not in SolveX itself.
        log.error("solve_agent_failure", agent=e.agent, reason=e.reason)
        raise HTTPException(status_code=502, detail="AI provider failure.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("solve_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@app.post("/solve-image")
@limiter.limit(settings.solve_rate_limit)
async def solve_image(
    request:             Request,
    image:               UploadFile = File(...),
    language:            str        = Form(default="python"),
    extra_text:          str        = Form(default=""),
    manual_ai_overrides: str        = Form(default="{}"),
    user_id: str                    = Depends(get_current_user),
):
    """
    Solve from a screenshot.
    Claude Vision reads the problem directly from the image.
    Protected + rate-limited, same reasoning as /solve.
    """
    if language not in {"python", "cpp", "java"}:
        raise HTTPException(400, "language must be python, cpp, or java")

    image_bytes = await image.read()
    if len(image_bytes) > 10 * 1024 * 1024:  # 10 MB limit
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
    try:
        result = await solve_problem(
            problem=extra_text or "Solve the competitive programming problem in this image.",
            language=language,
            image_base64=image_base64,
            manual_ai_overrides=overrides,
            user_id=user_id,
            image_mime_type=detected_type,
        )
        return result
    except RateLimitHit as e:
        _handle_rate_limit(e)
    except AgentFailure as e:
        log.error("solve_image_agent_failure", agent=e.agent, reason=e.reason)
        raise HTTPException(status_code=502, detail="AI provider failure.")
    except Exception as e:
        log.error("solve_image_error", error=str(e))
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/ai-config")
async def ai_config(user_id: str = Depends(get_current_user)):
    """
    Returns which AI is assigned to each agent.
    Frontend uses this to render the AI config panel.
    """
    return get_ai_config_summary()


@app.get("/usage")
async def usage(user_id: str = Depends(get_current_user)):
    """
    Returns per-AI usage percentage for the progress bars.
    Example: {"claude": {"percent": 82, "warning": true, "calls": 820}}
    """
    return {**get_usage_stats(), "scope": "server"}


@app.post("/usage/reset")
async def usage_reset(user_id: str = Depends(get_current_user)):
    """Resets all usage counters to zero."""
    raise HTTPException(status_code=403, detail="Admin access required.")


@app.get("/brain/stats")
async def brain_stats(user_id: str = Depends(get_current_user)):
    """
    Returns memory statistics for the Brain panel.
    Shows problems solved, pass rate, patterns learned, recent solves.
    """
    episodic = _load_json(_user_memory_file(user_id, "episodic.json"))
    semantic = _load_json(_user_memory_file(user_id, "semantic.json"))
    proc     = _load_json(_user_memory_file(user_id, "procedural.json"))

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
        "procedures_count": len(proc.get("procedures", {})),
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
    """Returns performance trends over time."""
    return get_temporal_insights(user_id)


@app.get("/brain/procedures")
async def brain_procedures(user_id: str = Depends(get_current_user)):
    """Returns current learned procedures for each agent (what they've learned)."""
    data = _load_json(_user_memory_file(user_id, "procedural.json"))
    return {
        "procedures":   data.get("procedures", DEFAULT_PROCEDURES),
        "last_updated": data.get("last_updated", "Never"),
    }


@app.post("/brain/reset")
async def brain_reset(user_id: str = Depends(get_current_user)):
    """
    Wipes all memory — fresh start.
    Use this if you want the brain to forget everything.
    """
    deleted = reset_user_memory(user_id)
    for path, key in [
        (_user_memory_file(user_id, "episodic.json"), "entries"),
        (_user_memory_file(user_id, "semantic.json"), "patterns"),
        (_user_memory_file(user_id, "temporal.json"), "events"),
    ]:
        data = _load_json(path)
        deleted[key] = len(data.get(key, []))
        _save_json(path, {})
    deleted["procedures"] = len(_load_json(_user_memory_file(user_id, "procedural.json")).get("procedures", {}))
    _save_json(_user_memory_file(user_id, "procedural.json"), {"procedures": DEFAULT_PROCEDURES})
    log.info("brain_reset")
    return {"message": "All memory cleared. Brain reset to defaults.", "deleted": deleted}


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.app_env == "development",
        log_level=settings.log_level.lower(),
    )
