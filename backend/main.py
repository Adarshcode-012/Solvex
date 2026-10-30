"""
main.py — SolveX v2 FastAPI Server
────────────────────────────────────
All HTTP endpoints the React frontend talks to.

Auth: if APP_SECRET_KEY is set in .env, every endpoint below except /health
requires an `X-API-Key` header matching it (see verify_api_key()).
If APP_SECRET_KEY is left unset, auth is skipped — convenient for local dev,
but config.py refuses to start with APP_ENV=production in that case.

Endpoints:
  GET  /health              → Public liveness check (no secrets returned)
  GET  /health/detailed     → Server status + which keys are configured (protected)
  POST /solve                → Text problem → full solution                 (protected, rate-limited)
  POST /solve-image          → Screenshot → full solution                    (protected, rate-limited)
  GET  /ai-config            → Which AI assigned to which agent              (protected)
  GET  /usage                → Per-AI usage % for progress bars              (protected)
  POST /usage/reset          → Reset usage counters                          (protected)
  GET  /brain/stats          → Memory stats (problems solved, patterns)      (protected)
  GET  /brain/temporal       → Improvement trends over time                  (protected)
  GET  /brain/procedures     → Learned procedures per agent                  (protected)
  POST /brain/reset          → Wipe all memory (fresh start)                 (protected)
"""

import base64
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request, Depends, Header
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
    reset_chroma_collections,
)


# ── Auth guard ─────────────────────────────────────────────────────────────────
async def verify_api_key(x_api_key: Optional[str] = Header(default=None)):
    """
    Gates every endpoint that spends money (AI calls) or mutates state.
    No-op if APP_SECRET_KEY isn't configured (local dev convenience) —
    but config.py refuses to boot with APP_ENV=production in that case,
    so this can't silently ship unprotected.
    """
    if settings.app_secret_key and x_api_key != settings.app_secret_key:
        raise HTTPException(status_code=403, detail="Invalid or missing X-API-Key header.")


# ── Rate limiter (protects the expensive /solve* endpoints from abuse) ────────
limiter = Limiter(key_func=get_remote_address)


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
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security headers ───────────────────────────────────────────────────────────
# Belt-and-suspenders: most deployments will also get these from a reverse
# proxy / platform edge (Railway, Render, nginx, etc), but setting them here
# means the API is self-protecting even served directly.
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if settings.app_env == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


# ── Global exception handler ──────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    log.error("unhandled_exception", path=request.url.path, error=str(exc))
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error. Check backend logs."}
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
    raise HTTPException(
        status_code=429,
        detail={
            "error":    "rate_limit",
            "ai":       e.ai_key,
            "ai_label": e.ai_label,
            "message":  str(e),
        }
    )


ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """
    Public liveness check — no auth required, no secrets returned.
    Load balancers / uptime monitors can hit this freely.
    """
    return {"status": "ok", "version": "2.0.0"}


@app.get("/health/detailed", dependencies=[Depends(verify_api_key)])
async def health_detailed():
    """
    Returns server health + which AI keys are configured.
    Protected: which providers are wired up is not something to expose publicly.
    """
    available = settings.available_keys
    return {
        "status":          "ok",
        "version":         "2.0.0",
        "environment":     settings.app_env,
        "keys":            available,
        "any_ai":          any(available.values()),
        "judge0":          bool(settings.judge0_api_key),
        "chroma_db_path":  settings.chroma_db_path,
    }


@app.post("/solve", dependencies=[Depends(verify_api_key)])
@limiter.limit(settings.solve_rate_limit)
async def solve_text(request: Request, req: SolveRequest):
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
        raise HTTPException(status_code=502, detail=f"{e.agent} agent failed: {e.reason}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.error("solve_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/solve-image", dependencies=[Depends(verify_api_key)])
@limiter.limit(settings.solve_rate_limit)
async def solve_image(
    request:             Request,
    image:               UploadFile = File(...),
    language:            str        = Form(default="python"),
    extra_text:          str        = Form(default=""),
    manual_ai_overrides: str        = Form(default="{}"),
):
    """
    Solve from a screenshot.
    Claude Vision reads the problem directly from the image.
    Protected + rate-limited, same reasoning as /solve.
    """
    if language not in {"python", "cpp", "java"}:
        raise HTTPException(400, "language must be python, cpp, or java")

    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(
            400,
            f"Unsupported image type '{image.content_type}'. "
            f"Allowed: {', '.join(sorted(ALLOWED_IMAGE_TYPES))}"
        )

    image_bytes = await image.read()
    if len(image_bytes) > 10 * 1024 * 1024:  # 10 MB limit
        raise HTTPException(400, "Image too large. Max 10MB.")

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
        )
        return result
    except RateLimitHit as e:
        _handle_rate_limit(e)
    except AgentFailure as e:
        log.error("solve_image_agent_failure", agent=e.agent, reason=e.reason)
        raise HTTPException(status_code=502, detail=f"{e.agent} agent failed: {e.reason}")
    except Exception as e:
        log.error("solve_image_error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/ai-config", dependencies=[Depends(verify_api_key)])
async def ai_config():
    """
    Returns which AI is assigned to each agent.
    Frontend uses this to render the AI config panel.
    """
    return get_ai_config_summary()


@app.get("/usage", dependencies=[Depends(verify_api_key)])
async def usage():
    """
    Returns per-AI usage percentage for the progress bars.
    Example: {"claude": {"percent": 82, "warning": true, "calls": 820}}
    """
    return get_usage_stats()


@app.post("/usage/reset", dependencies=[Depends(verify_api_key)])
async def usage_reset():
    """Resets all usage counters to zero."""
    reset_usage_stats()
    return {"message": "Usage stats reset successfully."}


@app.get("/brain/stats", dependencies=[Depends(verify_api_key)])
async def brain_stats():
    """
    Returns memory statistics for the Brain panel.
    Shows problems solved, pass rate, patterns learned, recent solves.
    """
    episodic = _load_json(EPISODIC_FILE)
    semantic = _load_json(SEMANTIC_FILE)
    proc     = _load_json(PROCEDURAL_FILE)

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


@app.get("/brain/temporal", dependencies=[Depends(verify_api_key)])
async def brain_temporal():
    """Returns performance trends over time."""
    return get_temporal_insights()


@app.get("/brain/procedures", dependencies=[Depends(verify_api_key)])
async def brain_procedures():
    """Returns current learned procedures for each agent (what they've learned)."""
    data = _load_json(PROCEDURAL_FILE)
    return {
        "procedures":   data.get("procedures", DEFAULT_PROCEDURES),
        "last_updated": data.get("last_updated", "Never"),
    }


@app.post("/brain/reset", dependencies=[Depends(verify_api_key)])
async def brain_reset():
    """
    Wipes all memory — fresh start.
    Use this if you want the brain to forget everything.
    """
    deleted = reset_chroma_collections()
    for path in [EPISODIC_FILE, SEMANTIC_FILE, TEMPORAL_FILE]:
        data = _load_json(path)
        key = "entries" if path == EPISODIC_FILE else "patterns" if path == SEMANTIC_FILE else "events"
        deleted[key] = len(data.get(key, []))
        _save_json(path, {})
    deleted["procedures"] = len(_load_json(PROCEDURAL_FILE).get("procedures", {}))
    _save_json(PROCEDURAL_FILE, {"procedures": DEFAULT_PROCEDURES})
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
