"""Graph assembly (spec/agent.md -> "Graph Assembly")."""
from langgraph.graph import StateGraph, END

from graph.state import AgentState
from graph.nodes import (
    check_clarity,
    generate_code,
    execute_code,
    observe_result,
    compose_answer,
    ask_clarification,
    cannot_answer,
    handle_error,
    finalize,
)
from graph.edges import (
    after_clarity,
    after_generate_code,
    after_execute_code,
    after_observe_result,
)


def _build_graph() -> StateGraph:
    g = StateGraph(AgentState)
    g.add_node("check_clarity", check_clarity)
    g.add_node("generate_code", generate_code)
    g.add_node("execute_code", execute_code)
    g.add_node("observe_result", observe_result)
    g.add_node("compose_answer", compose_answer)
    g.add_node("ask_clarification", ask_clarification)
    g.add_node("cannot_answer", cannot_answer)
    g.add_node("handle_error", handle_error)
    g.add_node("finalize", finalize)

    g.set_entry_point("check_clarity")

    g.add_conditional_edges(
        "check_clarity",
        after_clarity,
        {"ask_clarification": "ask_clarification", "generate_code": "generate_code"},
    )
    g.add_conditional_edges(
        "generate_code",
        after_generate_code,
        {"handle_error": "handle_error", "execute_code": "execute_code"},
    )
    g.add_conditional_edges(
        "execute_code",
        after_execute_code,
        {"handle_error": "handle_error", "observe_result": "observe_result"},
    )
    g.add_conditional_edges(
        "observe_result",
        after_observe_result,
        {
            "generate_code": "generate_code",  # loop-back — inert while max_steps=1
            "cannot_answer": "cannot_answer",
            "compose_answer": "compose_answer",
        },
    )

    g.add_edge("ask_clarification", "finalize")
    g.add_edge("compose_answer", "finalize")
    g.add_edge("cannot_answer", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handle_error", END)

    return g.compile()


agentic_ai = _build_graph()
