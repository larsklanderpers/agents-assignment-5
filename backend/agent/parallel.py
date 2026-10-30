"""Independent manager/finance lanes for the opt-in high-risk bonus route."""
from backend.agent.nodes import manager_review, finance_review, route_after_risk


def route_risk_with_bonus(state):
    if state.get("parallel_approvals") and state.get("risk_level") == "high":
        return ["parallel_manager_review", "parallel_finance_review"]
    return route_after_risk(state)


def _lane(state, review_node, field):
    result = review_node(state)
    decision = result.pop("decisions")[-1]
    result.pop("current_stage")
    result[field] = decision
    return result


def parallel_manager_review(state):
    return _lane(state, manager_review, "parallel_manager_decision")


def parallel_finance_review(state):
    return _lane(state, finance_review, "parallel_finance_decision")


def join_parallel_reviews(state):
    decisions = [state.get("parallel_manager_decision"), state.get("parallel_finance_decision")]
    if any(not isinstance(d, dict) for d in decisions):
        raise ValueError("Both parallel review decisions are required")
    return {"decisions": decisions, "current_stage": "processing"}


def route_parallel_result(state):
    return "process_request" if all(d["approved"] for d in state["decisions"]) else "handle_rejection"
