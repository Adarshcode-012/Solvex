"""
agents/all_agents.py

Implements the five pipeline agents — Analyzer, Strategist, Coder, Reviewer,
and Judge — that make up SolveX's solving pipeline. Each agent is an async
function that takes the shared pipeline state, calls an LLM (via
utils.ai_router.call_ai) or Judge0 (for the Judge), and returns the updated
state for the next stage.

If an agent's AI call fails unrecoverably (auth error, malformed response,
empty generation, etc.), it raises AgentFailure rather than silently
continuing with placeholder data — see orchestrator.py and main.py for how
that propagates into a real HTTP error response.
"""

import re
import json
import asyncio
import base64
from typing import Optional

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from config import settings
from logger import log
from utils.ai_router import call_ai, RateLimitHit, AIProviderError
from memory.brain import (
    get_procedure,
    auto_learn_from_mistake,
    recall_similar_problems,
    recall_semantic_insights,
    store_semantic,
    record_temporal_event,
)


class AgentFailure(Exception):
    """
    Raised when an agent cannot produce a usable result and recovery isn't
    possible (bad API key, malformed/empty AI response after retries, etc).
    Distinct from RateLimitHit, which is transient and already handled by
    the caller. orchestrator.py lets this propagate; main.py turns it into
    a real HTTP error instead of a fake "passed" result.
    """
    def __init__(self, agent: str, reason: str):
        self.agent  = agent
        self.reason = reason
        super().__init__(f"{agent} agent failed: {reason}")


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """
    Robustly extracts JSON from AI response.
    Handles: ```json fences, leading/trailing text, partial wrapping.
    """
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Strip ```json ... ``` fences
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # Find first { ... } block
    match = re.search(r"\{[\s\S]+\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    log.warning("json_extract_failed", preview=text[:100])
    return {}


def _strip_code_fences(text: str) -> str:
    """Remove ```python / ```cpp / ```java fences from code."""
    text = text.strip()
    text = re.sub(r"^```(?:python|cpp|c\+\+|java|py)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 1 — ANALYZER
# ─────────────────────────────────────────────────────────────────────────────

async def run_analyzer(state: dict) -> dict:
    log.info("agent_start", agent="analyzer")
    state.setdefault("pipeline_events", []).append({"agent": "analyzer", "status": "started"})

    procedure = get_procedure("analyzer", state["user_id"])

    system = f"""You are the Analyzer Agent in a competitive programming solver.
Your ONLY job: read and understand the problem, return structured JSON.

Learned procedure:
{procedure}

Return ONLY valid JSON — no text outside it:
{{
  "clean_problem": "Rewrite problem in your own words clearly",
  "constraints": {{
    "n_max": "max N or input size (e.g. 10^5)",
    "time_limit": "e.g. 2 seconds",
    "memory_limit": "e.g. 256 MB",
    "value_range": "range of values in input",
    "other": "any other constraints"
  }},
  "dsa_category": "e.g. Dynamic Programming / Graph BFS-DFS / Binary Search / Greedy / Two Pointers / Segment Tree / Math",
  "dsa_subcategory": "e.g. Knapsack / Shortest Path / Sliding Window",
  "sample_inputs": ["exact input string 1", "exact input string 2"],
  "sample_outputs": ["exact output string 1", "exact output string 2"],
  "edge_cases": ["N=1", "all values equal", "negative values if allowed"],
  "difficulty": "Easy / Medium / Hard / Very Hard"
}}"""

    messages = [
        {"role": "system", "content": system},
        {"role": "user",   "content": f"Analyze this problem:\n\n{state['problem']}"},
    ]

    try:
        response, ai_used = await call_ai(
            role="analyzer",
            messages=messages,
            manual_overrides=state.get("manual_ai_overrides"),
            image_base64=state.get("image_base64"),
            image_mime_type=state.get("image_mime_type", "image/png"),
        )
    except RateLimitHit:
        raise
    except (AIProviderError, ValueError) as e:
        log.error("analyzer_ai_error", error=str(e))
        state["pipeline_events"].append({"agent": "analyzer", "status": "failed", "error": str(e)})
        raise AgentFailure("analyzer", str(e)) from e

    state["agents_ai_used"]["analyzer"] = ai_used
    data = _extract_json(response)

    if not data:
        raise AgentFailure("analyzer", "AI response could not be parsed as JSON")

    state["extracted_problem"]          = data.get("clean_problem", state["problem"])
    state["constraints"]                = data.get("constraints", {})
    state["dsa_category"]               = data.get("dsa_category", "Unknown")
    state["sample_inputs"]              = data.get("sample_inputs", [])
    state["sample_outputs"]             = data.get("sample_outputs", [])
    state["constraints"]["subcategory"] = data.get("dsa_subcategory", "")
    state["constraints"]["edge_cases"]  = data.get("edge_cases", [])
    state["constraints"]["difficulty"]  = data.get("difficulty", "Unknown")

    log.info("agent_done", agent="analyzer", category=state["dsa_category"],
             difficulty=data.get("difficulty"), ai=ai_used)
    state["pipeline_events"].append({"agent": "analyzer", "status": "done", "ai": ai_used})
    return state


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 2 — STRATEGIST
# ─────────────────────────────────────────────────────────────────────────────

async def run_strategist(state: dict) -> dict:
    log.info("agent_start", agent="strategist")
    state["pipeline_events"].append({"agent": "strategist", "status": "started"})

    procedure = get_procedure("strategist", state["user_id"])
    similar   = recall_similar_problems(state["extracted_problem"], state["user_id"])
    insights  = recall_semantic_insights(
        f"{state['dsa_category']} {state['constraints'].get('n_max', '')}", state["user_id"]
    )

    memory_ctx = ""
    if similar:
        memory_ctx += "\nSimilar problems solved before:\n"
        for s in similar:
            passed_str = "✅" if s.get("passed") else "❌"
            memory_ctx += f"  {passed_str} Approach: {s.get('approach','?')} | Iterations: {s.get('iterations','?')}\n"
    if insights:
        memory_ctx += "\nLearned DSA insights:\n"
        for i in insights:
            memory_ctx += f"  [{i.get('category','?')}] {i.get('pattern','?')} → {i.get('insight','?')}\n"

    system = f"""You are the Strategist Agent in a competitive programming solver.
Reason from CONSTRAINTS to ALGORITHM — never from memorized solutions.

Learned procedure:
{procedure}

Follow this MANDATORY 8-STEP CHAIN:
STEP 1 OBSERVE:     What is this problem asking? (one sentence)
STEP 2 CONSTRAIN:   What are the hard mathematical limits? (write the numbers)
STEP 3 ELIMINATE:   Which algorithms CANNOT work? (calculate: N²=?, N log N=?)
STEP 4 CANDIDATES:  Which families CAN work within limits?
STEP 5 SELECT:      Best single approach and precise reason
STEP 6 CONSTRUCT:   Algorithm step-by-step in plain English (no code)
STEP 7 VERIFY:      Trace through sample input — confirm correct output
STEP 8 ALTERNATES:  1-2 other valid approaches with tradeoffs

Return ONLY valid JSON:
{{
  "reasoning_chain": "Full 8-step reasoning",
  "chosen_approach": "Algorithm name",
  "approach_description": "Step-by-step guide for Coder Agent",
  "time_complexity": "O(...) — explanation",
  "space_complexity": "O(...) — explanation",
  "key_insight": "The ONE non-obvious observation that makes this work",
  "alternate_approaches": [
    {{"name": "...", "time_complexity": "...", "why_not_chosen": "..."}}
  ],
  "implementation_hints": ["hint1 specific to this problem", "hint2", "hint3"],
  "new_semantic_pattern": "New generalizable rule discovered (empty string if none)"
}}"""

    user_msg = f"""Problem: {state['extracted_problem']}
Constraints: {json.dumps(state['constraints'], indent=2)}
Category: {state['dsa_category']}
Sample Input:  {state['sample_inputs'][:2]}
Sample Output: {state['sample_outputs'][:2]}
{memory_ctx}"""

    try:
        response, ai_used = await call_ai(
            role="strategist",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            manual_overrides=state.get("manual_ai_overrides"),
        )
    except RateLimitHit:
        raise
    except (AIProviderError, ValueError) as e:
        log.error("strategist_ai_error", error=str(e))
        state["pipeline_events"].append({"agent": "strategist", "status": "failed", "error": str(e)})
        raise AgentFailure("strategist", str(e)) from e

    state["agents_ai_used"]["strategist"] = ai_used
    data = _extract_json(response)

    if not data:
        raise AgentFailure("strategist", "AI response could not be parsed as JSON")

    state["reasoning_chain"]      = data.get("reasoning_chain", "")
    state["chosen_approach"]      = data.get("chosen_approach", "Unknown")
    state["time_complexity"]      = data.get("time_complexity", "")
    state["space_complexity"]     = data.get("space_complexity", "")
    state["alternate_approaches"] = data.get("alternate_approaches", [])
    state["constraints"]["approach_description"] = data.get("approach_description", "")
    state["constraints"]["key_insight"]          = data.get("key_insight", "")
    state["constraints"]["implementation_hints"] = data.get("implementation_hints", [])

    # Store new generalizable insight
    new_pattern = data.get("new_semantic_pattern", "").strip()
    if len(new_pattern) > 15:
        store_semantic(
            pattern=f"{state['dsa_category']} N={state['constraints'].get('n_max','')}",
            insight=new_pattern,
            category=state["dsa_category"],
            user_id=state["user_id"],
        )

    log.info("agent_done", agent="strategist", approach=state["chosen_approach"],
             time=state["time_complexity"], ai=ai_used)
    state["pipeline_events"].append({
        "agent": "strategist", "status": "done",
        "ai": ai_used, "approach": state["chosen_approach"]
    })
    return state


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 3 — CODER
# ─────────────────────────────────────────────────────────────────────────────

LANG_RULES = {
    "python": """Language: Python 3.11
- Fast I/O: import sys; input = sys.stdin.readline
- Recursion: sys.setrecursionlimit(300000)
- BFS queues: collections.deque (not list.pop(0))
- Large mod: use MOD = 10**9 + 7
- Variable names MUST reflect the problem domain""",

    "cpp": """Language: C++17
- Header: #include <bits/stdc++.h>\\nusing namespace std;
- Fast I/O: ios_base::sync_with_stdio(false); cin.tie(NULL);
- Overflow: use long long / int64_t for values > 2×10^9
- Variable names MUST reflect the problem domain""",

    "java": """Language: Java 17
- Fast I/O: BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
- Overflow: use long not int for values > 2×10^9
- Output: StringBuilder sb = new StringBuilder(); System.out.print(sb);
- Class: public class Solution { public static void main(String[] args) throws IOException { } }
- Variable names MUST reflect the problem domain""",
}


async def run_coder(state: dict) -> dict:
    iteration = state.get("judge_iteration", 0)
    language  = state.get("language", "python")
    log.info("agent_start", agent="coder", iteration=iteration, language=language)
    state["pipeline_events"].append({"agent": "coder", "status": "started", "iteration": iteration})

    procedure = get_procedure("coder", state["user_id"])

    system = f"""You are the Coder Agent in a competitive programming solver.
Write WORKING, OPTIMIZED code from the algorithm description.

{LANG_RULES.get(language, LANG_RULES['python'])}

Learned procedure:
{procedure}

ANTI-PLAGIARISM RULES (mandatory):
1. Variable names MUST be derived from the problem domain:
   BAD:  dp[i][j] = max(dp[i-1][j], dp[i][j-1])
   GOOD: max_value[day][capacity] = max(max_value[day-1][capacity], ...)
2. Implement EXACTLY what the algorithm description says — no deviations
3. Each logical section needs a brief comment in problem terms
4. Handle all edge cases listed in constraints

OUTPUT: Return ONLY complete runnable code. No explanation outside code."""

    if iteration == 0:
        hints  = state["constraints"].get("implementation_hints", [])
        edges  = state["constraints"].get("edge_cases", [])
        prompt = f"""Problem: {state['extracted_problem']}
Constraints: {json.dumps(state['constraints'], indent=2)}
Algorithm: {state['chosen_approach']}
Step-by-step: {state['constraints'].get('approach_description', '')}
Key insight: {state['constraints'].get('key_insight', '')}
Hints: {hints}
Edge cases to handle: {edges}
Sample I/O: {list(zip(state['sample_inputs'][:2], state['sample_outputs'][:2]))}

Write the complete {language} solution now."""

    else:
        # Targeted fix — give Coder the exact failure
        if state.get("compile_error"):
            error_section = f"COMPILE/SYNTAX ERROR:\n{state['compile_error']}\nFix the syntax error only."
        elif state.get("judge_wrong_output"):
            expected = state["sample_outputs"][0] if state["sample_outputs"] else "?"
            error_section = (
                f"WRONG ANSWER\n"
                f"Your output: {state['judge_wrong_output']!r}\n"
                f"Expected:    {expected!r}\n"
                f"Fix the logic — trace through the sample input manually."
            )
        else:
            error_section = f"RUNTIME ERROR:\n{state.get('judge_error', 'Unknown error')}\nFix the runtime error."

        prompt = f"""Your previous {language} solution FAILED.

PREVIOUS CODE:
{state['generated_code']}

FAILURE:
{error_section}

Problem: {state['extracted_problem']}
Algorithm: {state['chosen_approach']}
Key insight: {state['constraints'].get('key_insight', '')}

Fix ONLY the specific error. Return complete corrected code."""

    try:
        response, ai_used = await call_ai(
            role="coder",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": prompt},
            ],
            manual_overrides=state.get("manual_ai_overrides"),
            max_tokens=4096,
        )
    except RateLimitHit:
        raise
    except (AIProviderError, ValueError) as e:
        log.error("coder_ai_error", error=str(e))
        state["pipeline_events"].append({"agent": "coder", "status": "failed", "error": str(e)})
        raise AgentFailure("coder", str(e)) from e

    state["agents_ai_used"]["coder"] = ai_used
    code = _strip_code_fences(response)

    if not code.strip():
        raise AgentFailure("coder", "AI returned empty code")

    state["generated_code"] = code

    log.info("agent_done", agent="coder", chars=len(state["generated_code"]), ai=ai_used)
    state["pipeline_events"].append({"agent": "coder", "status": "done", "ai": ai_used})
    return state


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 4 — REVIEWER
# ─────────────────────────────────────────────────────────────────────────────

async def run_reviewer(state: dict) -> dict:
    log.info("agent_start", agent="reviewer")
    state["pipeline_events"].append({"agent": "reviewer", "status": "started"})

    procedure = get_procedure("reviewer", state["user_id"])

    system = f"""You are the Reviewer Agent in a competitive programming solver.
Review code for CORRECTNESS bugs only — not style or formatting.

Learned procedure (includes historically caught bugs):
{procedure}

Check these specifically:
1. TIME COMPLEXITY: Is it within limit for max N? (compute ops = N × complexity factor)
2. OVERFLOW: Any variable storing values that could exceed 2×10^9 without long/int64?
3. EDGE CASES: N=0, N=1, all same values, negative numbers (if in constraints)
4. ALGORITHM MATCH: Does the code actually do what Strategist described?
5. BASE CASES: DP/recursion base cases correct for minimum valid input?
6. ARRAY BOUNDS: Any loop that could access arr[n] instead of arr[n-1]?
7. FAST I/O: Is fast input reading present for competitive programming?

Return ONLY valid JSON:
{{
  "verdict": "APPROVE" or "NEEDS_FIX",
  "issues": ["specific issue 1", "specific issue 2"],
  "fix_instructions": "Exact fix if NEEDS_FIX — line-level specifics",
  "confidence": "HIGH / MEDIUM / LOW"
}}"""

    user_msg = f"""Review this {state['language']} code:

```
{state['generated_code']}
```

Problem: {state['extracted_problem']}
Constraints: {json.dumps(state['constraints'], indent=2)}
Expected algorithm: {state['chosen_approach']}
Sample: Input={state['sample_inputs'][:1]} → Expected={state['sample_outputs'][:1]}"""

    try:
        response, ai_used = await call_ai(
            role="reviewer",
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user_msg},
            ],
            manual_overrides=state.get("manual_ai_overrides"),
        )
    except RateLimitHit:
        raise
    except (AIProviderError, ValueError) as e:
        log.error("reviewer_ai_error", error=str(e))
        state["pipeline_events"].append({"agent": "reviewer", "status": "failed", "error": str(e)})
        raise AgentFailure("reviewer", str(e)) from e

    state["agents_ai_used"]["reviewer"] = ai_used
    data    = _extract_json(response)
    verdict = data.get("verdict", "APPROVE") if data else "APPROVE"
    issues  = data.get("issues", []) if data else []

    state["review_notes"] = (
        f"Verdict: {verdict} | Confidence: {data.get('confidence', '?') if data else '?'} | "
        f"Issues: {'; '.join(issues) if issues else 'None'}"
    )

    if verdict == "NEEDS_FIX":
        state["judge_error"] = f"Reviewer flagged:\n{data.get('fix_instructions', '')}"
        log.info("agent_done", agent="reviewer", verdict="NEEDS_FIX", issues=len(issues), ai=ai_used)
    else:
        state["judge_error"] = ""
        log.info("agent_done", agent="reviewer", verdict="APPROVE",
                 confidence=data.get("confidence") if data else None, ai=ai_used)

    state["pipeline_events"].append({
        "agent": "reviewer", "status": "done",
        "ai": ai_used, "verdict": verdict
    })
    return state


# ─────────────────────────────────────────────────────────────────────────────
# AGENT 5 — JUDGE
# ─────────────────────────────────────────────────────────────────────────────

LANGUAGE_IDS = {"python": 71, "cpp": 54, "java": 62}

# Judge0 status codes
STATUS_COMPILE_ERROR  = 6
STATUS_TLE            = 5
STATUS_ACCEPTED       = 3
STATUS_WRONG_ANSWER   = 4
RUNTIME_ERROR_CODES   = {7, 8, 9, 10, 11, 12, 13}

JUDGE_FAILED_WRONG_ANSWER = "failed_wrong_answer"
JUDGE_FAILED_COMPILE = "failed_compile"
JUDGE_FAILED_RUNTIME = "failed_runtime"
JUDGE_FAILED_TLE = "failed_tle"
JUDGE_DISABLED = "judge_disabled"
JUDGE_UNAVAILABLE = "judge_unavailable"


class JudgeUnavailable(Exception):
    """Raised when Judge0 cannot accept or complete a submission."""


def _b64e(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")

def _b64d(text: Optional[str]) -> str:
    if not text:
        return ""
    try:
        return base64.b64decode(text).decode("utf-8")
    except Exception:
        return text or ""


async def _run_judge0(code: str, language: str, stdin: str) -> dict:
    """Submits code to Judge0 and polls for result. Async — uses httpx +
    asyncio.sleep so the ~1.5-18s poll wait doesn't block the event loop."""

    # An agent failure upstream should never be able to masquerade as a pass —
    # refuse to even attempt "verification" of empty code.
    if not code.strip():
        return {
            "status": {"id": STATUS_COMPILE_ERROR, "description": "No code to run"},
            "stdout": "", "stderr": "", "compile_output": "No code was generated.",
            "time": "0", "memory": "0", "verified": True,
        }

    if not settings.judge0_api_key:
        return {"result_state": JUDGE_DISABLED, "verified": False}

    headers = {
        "Content-Type":    "application/json",
        "X-RapidAPI-Key":  settings.judge0_api_key,
        "X-RapidAPI-Host": "judge0-ce.p.rapidapi.com",
    }
    payload = {
        "source_code":    _b64e(code),
        "language_id":    LANGUAGE_IDS.get(language, 71),
        "stdin":          _b64e(stdin),
        "cpu_time_limit": 5,
        "memory_limit":   262144,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            sub_resp = await client.post(
                f"{settings.judge0_base_url}/submissions?base64_encoded=true&wait=false",
                json=payload, headers=headers,
            )
            sub_resp.raise_for_status()
            token = sub_resp.json().get("token")
            if not token:
                raise JudgeUnavailable("Judge0 submission returned no token")

            # Poll until done (max 18 seconds)
            result = {}
            for _ in range(12):
                await asyncio.sleep(1.5)
                poll = await client.get(
                    f"{settings.judge0_base_url}/submissions/{token}?base64_encoded=true",
                    headers=headers, timeout=10,
                )
                poll.raise_for_status()
                result = poll.json()
                if result.get("status", {}).get("id", 0) > 2:
                    break

            if result.get("status", {}).get("id", 0) == 0:
                raise JudgeUnavailable("Judge0 polling timed out")

        return {
            "status":         result.get("status", {"id": 0, "description": "Unknown"}),
            "stdout":         _b64d(result.get("stdout")),
            "stderr":         _b64d(result.get("stderr")),
            "compile_output": _b64d(result.get("compile_output")),
            "time":           result.get("time", "?"),
            "memory":         result.get("memory", "?"),
            "verified":       True,
        }
    except (httpx.HTTPError, JudgeUnavailable) as e:
        log.warning("judge0_request_failed", error=str(e))
        raise JudgeUnavailable(str(e)) from e


async def _run_judge0_with_retries(code: str, language: str, stdin: str) -> dict:
    if not settings.judge0_api_key:
        return await _run_judge0(code, language, stdin)

    async for attempt in AsyncRetrying(
        retry=retry_if_exception_type(JudgeUnavailable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        reraise=True,
    ):
        with attempt:
            return await _run_judge0(code, language, stdin)
    raise JudgeUnavailable("Judge0 retry policy exhausted")


def _normalize(text: str) -> str:
    """Normalize output for comparison — strip whitespace per line."""
    return "\n".join(line.strip() for line in text.strip().split("\n"))


async def run_judge(state: dict) -> dict:
    iteration = state.get("judge_iteration", 0)
    language  = state.get("language", "python")
    code      = state.get("generated_code", "")
    user_id   = state.get("user_id", "guest_default")

    log.info("agent_start", agent="judge", iteration=iteration + 1,
             max=state["judge_max_iterations"])
    state["pipeline_events"].append({"agent": "judge", "status": "started", "iteration": iteration})

    # If Reviewer flagged issues (iteration 0), route back immediately
    if state.get("judge_error") and iteration == 0:
        state["judge_iteration"] = 1
        log.info("judge_routing_reviewer_fix")
        state["pipeline_events"].append({"agent": "judge", "status": "reviewer_reroute"})
        return state

    all_passed    = True
    first_failure: Optional[dict] = None

    sample_pairs = list(zip(
        state.get("sample_inputs", []),
        state.get("sample_outputs", [])
    ))
    has_samples = bool(sample_pairs)
    if not has_samples:
        sample_pairs = [("", "")]  # Compile-and-run only

    for idx, (inp, expected) in enumerate(sample_pairs):
        log.info("judge_test", test=idx + 1, of=len(sample_pairs))
        try:
            result = await _run_judge0_with_retries(code, language, inp)
        except JudgeUnavailable:
            state["verified"] = False
            state["status"] = JUDGE_UNAVAILABLE
            state["error_message"] = "Judge0 is unavailable; the solution was not verified."
            state["pipeline_events"].append({"agent": "judge", "status": JUDGE_UNAVAILABLE})
            state["agents_ai_used"]["judge"] = "judge0"
            return state

        if result.get("result_state") == JUDGE_DISABLED:
            state["verified"] = False
            state["status"] = "unverified"
            state["error_message"] = "Judge0 is not configured; the solution was not verified."
            state["pipeline_events"].append({"agent": "judge", "status": JUDGE_DISABLED})
            state["agents_ai_used"]["judge"] = "judge0"
            return state

        status_id = result["status"]["id"]

        if status_id == 0:
            state["verified"] = False
            state["status"] = JUDGE_UNAVAILABLE
            state["error_message"] = "Judge0 is unavailable; the solution was not verified."
            state["pipeline_events"].append({"agent": "judge", "status": JUDGE_UNAVAILABLE})
            state["agents_ai_used"]["judge"] = "judge0"
            return state

        if status_id == STATUS_COMPILE_ERROR or result["compile_output"]:
            all_passed    = False
            first_failure = {"type": JUDGE_FAILED_COMPILE, "msg": result["compile_output"] or result["stderr"]}
            break

        elif status_id == STATUS_TLE:
            all_passed    = False
            first_failure = {"type": JUDGE_FAILED_TLE, "msg": "Time Limit Exceeded. Algorithm is O() too slow — reconsider approach."}
            break

        elif status_id in RUNTIME_ERROR_CODES:
            all_passed    = False
            first_failure = {"type": JUDGE_FAILED_RUNTIME, "msg": result["stderr"] or result["status"].get("description", "Runtime Error")}
            break

        elif status_id != STATUS_ACCEPTED:
            all_passed = False
            first_failure = {"type": JUDGE_FAILED_RUNTIME, "msg": result["status"].get("description", "Judge0 rejected the submission")}
            break

        actual = _normalize(result.get("stdout", ""))
        if has_samples and actual != _normalize(expected):
            all_passed = False
            first_failure = {
                "type": JUDGE_FAILED_WRONG_ANSWER,
                "actual": actual,
                "expected": _normalize(expected),
                "input": inp,
            }
            break

    if not has_samples and all_passed:
        state["status"] = "compiled_only"
        state["judge_passed"] = False
        state["final_solution"] = code
        state["pipeline_events"].append({"agent": "judge", "status": "compiled_only"})
        state["agents_ai_used"]["judge"] = "judge0"
        return state

    # ── Process result ────────────────────────────────────────────────────────
    if all_passed:
        log.info("judge_passed", iteration=iteration + 1)
        state["judge_passed"]   = True
        state["final_solution"] = code
        state["status"]         = "passed"
        record_temporal_event("solve_complete", {
            "passed":     True,
            "iterations": iteration + 1,
            "approach":   state["chosen_approach"],
            "language":   language,
            "category":   state["dsa_category"],
        }, user_id)
        state["pipeline_events"].append({"agent": "judge", "status": "passed"})

    else:
        state["judge_iteration"] = iteration + 1

        if state["judge_iteration"] >= state["judge_max_iterations"]:
            log.warning("judge_max_retries", iterations=state["judge_iteration"])
            state["status"]         = "max_retries"
            state["final_solution"] = code
            state["error_message"]  = (
                f"Could not pass all test cases after {state['judge_max_iterations']} attempts. "
                "Best solution shown — review the approach and try again."
            )
            record_temporal_event("solve_complete", {
                "passed": False, "iterations": state["judge_iteration"],
                "category": state["dsa_category"],
            }, user_id)
            state["pipeline_events"].append({"agent": "judge", "status": "max_retries"})

        else:
            ftype = first_failure.get("type", "unknown")
            log.info("judge_failed", failure=ftype, retry=state["judge_iteration"])

            # Learn from mistake
            auto_learn_from_mistake("reviewer", ftype, user_id)

            # Set precise error for Coder
            state["compile_error"]      = first_failure["msg"] if ftype == JUDGE_FAILED_COMPILE else ""
            state["judge_wrong_output"] = first_failure.get("actual", "") if ftype == JUDGE_FAILED_WRONG_ANSWER else ""
            state["judge_error"]        = (
                first_failure["msg"] if ftype in (JUDGE_FAILED_TLE, JUDGE_FAILED_RUNTIME)
                else (f"Wrong answer on input:\n{first_failure.get('input','?')}" if ftype == JUDGE_FAILED_WRONG_ANSWER else "")
            )
            state["pipeline_events"].append({"agent": "judge", "status": "failed", "failure_type": ftype})

    state["agents_ai_used"]["judge"] = "judge0"
    return state
