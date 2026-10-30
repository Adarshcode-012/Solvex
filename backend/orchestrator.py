
from typing import Optional
from langgraph.graph import StateGraph, END
from typing_extensions import TypedDict

from agents.all_agents import (
    run_analyzer, run_strategist, run_coder, run_reviewer, run_judge, AgentFailure,
)
from memory.brain import create_session_state, store_episodic
from logger import log


# ── LangGraph state — must match create_session_state exactly ─────────────────
class SolveXState(TypedDict):
    problem:              str
    language:             str
    image_base64:         Optional[str]
    manual_ai_overrides:  dict
    extracted_problem:    str
    constraints:          dict
    dsa_category:         str
    sample_inputs:        list
    sample_outputs:       list
    chosen_approach:      str
    alternate_approaches: list
    time_complexity:      str
    space_complexity:     str
    reasoning_chain:      str
    generated_code:       str
    review_notes:         str
    judge_iteration:      int
    judge_max_iterations: int
    judge_passed:         bool
    judge_error:          str
    judge_wrong_output:   str
    compile_error:        str
    verified:             bool
    agents_ai_used:       dict
    pipeline_events:      list
    final_solution:       str
    status:               str
    error_message:        str


# ── Node wrappers (async — agents make real network calls) ────────────────────
async def _analyzer_node(state: SolveXState)   -> dict: return await run_analyzer(dict(state))
async def _strategist_node(state: SolveXState) -> dict: return await run_strategist(dict(state))
async def _coder_node(state: SolveXState)      -> dict: return await run_coder(dict(state))
async def _reviewer_node(state: SolveXState)   -> dict: return await run_reviewer(dict(state))
async def _judge_node(state: SolveXState)      -> dict: return await run_judge(dict(state))


def _should_continue(state: SolveXState) -> str:
    if state["judge_passed"] or state["status"] in {"unverified", "judge_unavailable", "compiled_only"}:
        return "end"
    if state["judge_iteration"] >= state["judge_max_iterations"]:
        return "end"
    return "fix_code"


def _build_graph() -> StateGraph:
    """Builds a fresh compiled graph for each request."""
    g = StateGraph(SolveXState)
    g.add_node("analyzer",   _analyzer_node)
    g.add_node("strategist", _strategist_node)
    g.add_node("coder",      _coder_node)
    g.add_node("reviewer",   _reviewer_node)
    g.add_node("judge",      _judge_node)
    g.set_entry_point("analyzer")
    g.add_edge("analyzer",   "strategist")
    g.add_edge("strategist", "coder")
    g.add_edge("coder",      "reviewer")
    g.add_edge("reviewer",   "judge")
    g.add_conditional_edges(
        "judge",
        _should_continue,
        {"fix_code": "coder", "end": END}
    )
    return g.compile()


async def solve_problem(
    problem:             str,
    language:            str,
    image_base64:        Optional[str] = None,
    manual_ai_overrides: Optional[dict] = None,
) -> dict:
    """
    Runs the 5-agent pipeline and returns the full result dict.
    Called by FastAPI endpoints.
    """
    log.info("solve_start", language=language, has_image=bool(image_base64))

    initial = create_session_state(
        problem=problem,
        language=language,
        image_base64=image_base64,
        manual_ai_overrides=manual_ai_overrides or {},
    )

    graph = _build_graph()
    final = await graph.ainvoke(initial)

    # Persist to episodic memory
    store_episodic(
        problem=final["extracted_problem"],
        approach=final["chosen_approach"],
        language=language,
        iterations=final["judge_iteration"],
        passed=final["judge_passed"],
        code_preview=final["final_solution"][:300],
    )

    log.info("solve_complete", status=final["status"],
             iterations=final["judge_iteration"], passed=final["judge_passed"])

    return {
        "status":               final["status"],
        "final_solution":       final["final_solution"],
        "language":             language,
        "dsa_category":         final["dsa_category"],
        "chosen_approach":      final["chosen_approach"],
        "reasoning_chain":      final["reasoning_chain"],
        "time_complexity":      final["time_complexity"],
        "space_complexity":     final["space_complexity"],
        "alternate_approaches": final["alternate_approaches"],
        "review_notes":         final["review_notes"],
        "iterations_used":      final["judge_iteration"],
        "verified":             final.get("verified", True),
        "error_message":        final.get("error_message", ""),
        "extracted_problem":    final["extracted_problem"],
        "constraints":          final["constraints"],
        "agents_ai_used":       final["agents_ai_used"],
        "pipeline_events":      final.get("pipeline_events", []),
    }
