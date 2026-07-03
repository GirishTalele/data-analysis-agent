"""Conditional edge routers for the analysis graph (spec/agent.md -> "Conditional edges")."""
from __future__ import annotations

from graph.state import AgentState


def after_clarity(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    if state.get("needs_clarification"):
        return "ask_clarification"
    return "generate_code"


def after_generate_code(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "execute_code"


def after_execute_code(state: AgentState) -> str:
    if state.get("error"):
        return "handle_error"
    return "observe_result"


def after_observe_result(state: AgentState) -> str:
    if state.get("execution_error"):
        if state.get("step_count", 0) < state.get("max_steps", 1):
            return "generate_code"  # loop-back — inert while max_steps=1
        return "cannot_answer"
    return "compose_answer"
