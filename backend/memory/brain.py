"""
memory/brain.py

SolveX's 4-layer memory system: episodic (past attempts), semantic (learned
patterns), procedural (per-agent learned heuristics), and temporal
(performance trends over time). Episodic/semantic/procedural/temporal data
persists to local JSON files with atomic writes; semantic recall is backed
by a local ChromaDB collection.
"""

import os
import json
import time
import tempfile
from datetime import datetime
from typing import Optional

from config import settings
from logger import log

# ── Paths ─────────────────────────────────────────────────────────────────────
MEMORY_DIR      = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(MEMORY_DIR, exist_ok=True)

EPISODIC_FILE   = os.path.join(MEMORY_DIR, "episodic.json")
SEMANTIC_FILE   = os.path.join(MEMORY_DIR, "semantic.json")
PROCEDURAL_FILE = os.path.join(MEMORY_DIR, "procedural.json")
TEMPORAL_FILE   = os.path.join(MEMORY_DIR, "temporal.json")

# ── ChromaDB (local vector DB) ────────────────────────────────────────────────
CHROMA_AVAILABLE = False
_episodic_col    = None
_semantic_col    = None
_chroma_client   = None

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    # ChromaDB 0.5.x API. anonymized_telemetry=False: a backend service
    # handling other people's DSA problems shouldn't phone home by default,
    # and it also silences the noisy "Failed to send telemetry event"
    # warnings that otherwise show up on every startup.
    _chroma_client = chromadb.PersistentClient(
        path=settings.chroma_db_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    _episodic_col  = _chroma_client.get_or_create_collection(
        name="episodic_memory",
        metadata={"hnsw:space": "cosine"}
    )
    _semantic_col  = _chroma_client.get_or_create_collection(
        name="semantic_memory",
        metadata={"hnsw:space": "cosine"}
    )
    CHROMA_AVAILABLE = True
    log.info("chromadb_ready", path=settings.chroma_db_path)
except Exception as e:
    log.warning("chromadb_unavailable", error=str(e), fallback="json")


def reset_chroma_collections() -> dict[str, int]:
    """Delete and recreate both vector collections, returning deleted counts."""
    global _episodic_col, _semantic_col
    if not CHROMA_AVAILABLE or _chroma_client is None:
        return {"episodic": 0, "semantic": 0}

    counts = {
        "episodic": _episodic_col.count() if _episodic_col is not None else 0,
        "semantic": _semantic_col.count() if _semantic_col is not None else 0,
    }
    _chroma_client.delete_collection("episodic_memory")
    _chroma_client.delete_collection("semantic_memory")
    _episodic_col = _chroma_client.get_or_create_collection(
        name="episodic_memory", metadata={"hnsw:space": "cosine"}
    )
    _semantic_col = _chroma_client.get_or_create_collection(
        name="semantic_memory", metadata={"hnsw:space": "cosine"}
    )
    return counts


# ── Thread-safe JSON helpers ──────────────────────────────────────────────────
def _load_json(path: str) -> dict:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_json(path: str, data: dict) -> None:
    """Atomic write — write to temp file then rename to avoid corruption."""
    dir_name = os.path.dirname(path)
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=dir_name,
            delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(data, tmp, indent=2, ensure_ascii=False)
            tmp_path = tmp.name
        os.replace(tmp_path, path)  # Atomic on POSIX, near-atomic on Windows
    except OSError as e:
        log.error("json_write_failed", path=path, error=str(e))


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — EPISODIC MEMORY
# ══════════════════════════════════════════════════════════════════════════════

def store_episodic(
    problem: str, approach: str, language: str,
    iterations: int, passed: bool, code_preview: str
) -> None:
    entry = {
        "timestamp":    datetime.now().isoformat(),
        "problem":      problem[:400],
        "approach":     approach,
        "language":     language,
        "iterations":   iterations,
        "passed":       passed,
        "code_preview": code_preview[:300],
    }

    if CHROMA_AVAILABLE and _episodic_col is not None:
        try:
            _episodic_col.add(
                documents=[problem[:400]],
                metadatas=[{k: str(v) if isinstance(v, bool) else v for k, v in entry.items()}],
                ids=[f"ep_{int(time.time() * 1000)}"]
            )
            log.info("episodic_stored", approach=approach, passed=passed)
            return
        except Exception as e:
            log.warning("episodic_chroma_fail", error=str(e))

    # JSON fallback
    data    = _load_json(EPISODIC_FILE)
    entries = data.get("entries", [])
    entries.append(entry)
    _save_json(EPISODIC_FILE, {"entries": entries[-200:]})


def recall_similar_problems(current_problem: str, top_k: int = 3) -> list[dict]:
    if CHROMA_AVAILABLE and _episodic_col is not None:
        try:
            count = _episodic_col.count()
            if count == 0:
                return []
            results = _episodic_col.query(
                query_texts=[current_problem[:400]],
                n_results=min(top_k, count)
            )
            metas = results.get("metadatas", [[]])[0]
            # Convert string booleans back
            for m in metas:
                if "passed" in m and isinstance(m["passed"], str):
                    m["passed"] = m["passed"].lower() == "true"
            return metas
        except Exception as e:
            log.warning("episodic_recall_fail", error=str(e))

    # JSON fallback
    data          = _load_json(EPISODIC_FILE)
    entries       = data.get("entries", [])
    current_words = set(current_problem.lower().split())
    scored        = []
    for e in entries:
        past_words = set(e.get("problem", "").lower().split())
        overlap    = len(current_words & past_words) / max(len(current_words), 1)
        if overlap > 0.2:
            scored.append((overlap, e))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:top_k]]


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — SEMANTIC MEMORY
# ══════════════════════════════════════════════════════════════════════════════

def store_semantic(pattern: str, insight: str, category: str) -> None:
    entry = {
        "pattern":    pattern,
        "insight":    insight,
        "category":   category,
        "timestamp":  datetime.now().isoformat(),
        "confidence": 1,
    }

    if CHROMA_AVAILABLE and _semantic_col is not None:
        try:
            count = _semantic_col.count()
            if count > 0:
                existing = _semantic_col.query(query_texts=[pattern], n_results=1)
                distances = existing.get("distances", [[]])[0]
                if distances and distances[0] < 0.15:
                    existing_id   = existing["ids"][0][0]
                    existing_meta = existing["metadatas"][0][0]
                    existing_meta["confidence"] = int(existing_meta.get("confidence", 1)) + 1
                    _semantic_col.update(ids=[existing_id], metadatas=[existing_meta])
                    return

            _semantic_col.add(
                documents=[pattern],
                metadatas=[entry],
                ids=[f"sem_{int(time.time() * 1000)}"]
            )
            return
        except Exception as e:
            log.warning("semantic_store_fail", error=str(e))

    data     = _load_json(SEMANTIC_FILE)
    patterns = data.get("patterns", [])
    patterns.append(entry)
    _save_json(SEMANTIC_FILE, {"patterns": patterns[-500:]})


def recall_semantic_insights(query: str, top_k: int = 5) -> list[dict]:
    if CHROMA_AVAILABLE and _semantic_col is not None:
        try:
            count = _semantic_col.count()
            if count == 0:
                return []
            results = _semantic_col.query(
                query_texts=[query],
                n_results=min(top_k, count)
            )
            return results.get("metadatas", [[]])[0]
        except Exception as e:
            log.warning("semantic_recall_fail", error=str(e))

    data = _load_json(SEMANTIC_FILE)
    return data.get("patterns", [])[:top_k]


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — PROCEDURAL MEMORY (self-improving agent instructions)
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_PROCEDURES: dict[str, str] = {
    "analyzer": (
        "Extract all constraints with mathematical precision. "
        "Always identify the tightest constraint as it drives algorithm choice. "
        "Parse ALL sample input/output pairs from the problem."
    ),
    "strategist": (
        "Always eliminate O(N²) when N > 10^4. "
        "When constraints involve primes or modular arithmetic, consider NTT. "
        "Verify chosen approach manually against sample input before finalizing. "
        "Never suggest an approach without computing its exact operation count."
    ),
    "coder": (
        "Use domain-specific variable names derived from the problem context. "
        "Never use generic names like res, tmp, dp, i, j as standalone variables. "
        "Add fast I/O for competitive programming inputs. "
        "Always handle the minimum input edge case (N=0 or N=1)."
    ),
    "reviewer": (
        "Always check for integer overflow when values exceed 10^9. "
        "Verify base cases in DP/recursion against minimum valid input. "
        "Check array bounds for off-by-one errors in loop conditions. "
        "Confirm algorithm exactly matches what Strategist described."
    ),
    "judge": (
        "Extract the exact error type before routing back to Coder. "
        "Distinguish between compile error, wrong answer, TLE, and runtime error. "
        "On wrong answer: always include the failing input in the error context."
    ),
}

LEARNING_MAP: dict[str, str] = {
    "integer overflow":    "Always use long/int64 when constraint values can exceed 2×10^9.",
    "off by one":          "Double-check loop bounds — use < vs <= carefully on array ends.",
    "wrong base case":     "Verify DP/recursion base cases against minimum valid input (N=0, N=1).",
    "time limit exceeded": "Re-verify O() complexity against max N before finalizing algorithm.",
    "segmentation fault":  "Check all array index accesses against declared bounds.",
    "wrong answer":        "Trace through sample input manually step-by-step before submission.",
    "compile error":       "Verify all variable types and syntax before finalizing code.",
    "runtime error":       "Add bounds checking and null checks for edge cases.",
}


def get_procedure(agent_role: str) -> str:
    data       = _load_json(PROCEDURAL_FILE)
    procedures = data.get("procedures", DEFAULT_PROCEDURES)
    return procedures.get(agent_role, DEFAULT_PROCEDURES.get(agent_role, ""))


def update_procedure(agent_role: str, new_learning: str) -> None:
    data       = _load_json(PROCEDURAL_FILE)
    procedures = data.get("procedures", DEFAULT_PROCEDURES.copy())
    current    = procedures.get(agent_role, DEFAULT_PROCEDURES.get(agent_role, ""))

    if new_learning.lower().strip() not in current.lower():
        procedures[agent_role] = current.rstrip() + f"\n{new_learning}"
        log.info("procedure_updated", agent=agent_role, learning=new_learning[:60])

    _save_json(PROCEDURAL_FILE, {
        "procedures":   procedures,
        "last_updated": datetime.now().isoformat(),
    })


def auto_learn_from_mistake(agent_role: str, mistake_type: str) -> None:
    """Derives a procedural rule from a mistake type and stores it."""
    if not mistake_type:
        return
    for pattern, learning in LEARNING_MAP.items():
        if pattern in mistake_type.lower():
            update_procedure(agent_role, learning)
            return


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — TEMPORAL MEMORY
# ══════════════════════════════════════════════════════════════════════════════

def record_temporal_event(event_type: str, details: dict) -> None:
    data   = _load_json(TEMPORAL_FILE)
    events = data.get("events", [])
    events.append({
        "timestamp":  datetime.now().isoformat(),
        "event_type": event_type,
        "details":    details,
    })
    _save_json(TEMPORAL_FILE, {"events": events[-1000:]})


def get_temporal_insights() -> dict:
    data   = _load_json(TEMPORAL_FILE)
    events = data.get("events", [])
    solves = [e for e in events if e["event_type"] == "solve_complete"]

    if not solves:
        return {
            "total_solves":   0,
            "pass_rate":      0.0,
            "avg_iterations": 0.0,
            "message":        "No solves yet — start solving to build memory!",
            "by_category":    {},
        }

    passed      = sum(1 for e in solves if e.get("details", {}).get("passed"))
    total       = len(solves)
    avg_iters   = sum(e.get("details", {}).get("iterations", 1) for e in solves) / total

    # Per-category breakdown
    by_category: dict[str, dict] = {}
    for e in solves:
        cat = e.get("details", {}).get("category", "Unknown")
        if cat not in by_category:
            by_category[cat] = {"total": 0, "passed": 0}
        by_category[cat]["total"] += 1
        if e.get("details", {}).get("passed"):
            by_category[cat]["passed"] += 1

    return {
        "total_solves":   total,
        "pass_rate":      round((passed / total) * 100, 1),
        "avg_iterations": round(avg_iters, 2),
        "message":        f"{total} problems attempted, {round((passed/total)*100)}% pass rate",
        "by_category":    by_category,
    }


# ══════════════════════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════════════════════

def create_session_state(
    problem: str,
    language: str,
    image_base64: Optional[str] = None,
    manual_ai_overrides: Optional[dict] = None,
) -> dict:
    return {
        "problem":              problem,
        "language":             language,
        "image_base64":         image_base64,
        "manual_ai_overrides":  manual_ai_overrides or {},
        # Analyzer
        "extracted_problem":    "",
        "constraints":          {},
        "dsa_category":         "",
        "sample_inputs":        [],
        "sample_outputs":       [],
        # Strategist
        "chosen_approach":      "",
        "alternate_approaches": [],
        "time_complexity":      "",
        "space_complexity":     "",
        "reasoning_chain":      "",
        # Coder
        "generated_code":       "",
        # Reviewer
        "review_notes":         "",
        # Judge loop
        "judge_iteration":      0,
        "judge_max_iterations": settings.judge_max_iterations,
        "judge_passed":         False,
        "judge_error":          "",
        "judge_wrong_output":   "",
        "compile_error":        "",
        # True unless a Judge0 call was simulated (no JUDGE0_API_KEY set) — lets
        # the frontend flag "passed" results that were never actually executed.
        "verified":             True,
        # Meta
        "agents_ai_used":       {},
        "pipeline_events":      [],   # SSE events for real-time progress
        # Output
        "final_solution":       "",
        "status":               "pending",
        "error_message":        "",
    }
