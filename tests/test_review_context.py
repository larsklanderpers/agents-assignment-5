"""Policy explanations must agree with the workflow's boundary and escalation rules."""
import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, START, END
from backend.agent.state import ApprovalState
from backend.agent import nodes
from backend.agent.review_context import build_review_context


@pytest.mark.parametrize("amount,priority,department,risk,reviewers", [
    (10000, "normal", "engineering", "low", []),
    (10000.01, "normal", "engineering", "medium", ["Manager"]),
    (50000, "urgent", "engineering", "medium", ["Manager"]),
    (50000.01, "normal", "research", "high", ["Manager", "Finance"]),
    (95000, "urgent", "engineering", "critical", ["Manager", "Finance", "Executive"]),
    (8000, "normal", "hr", "low", ["Manager"]),
    (35000, "normal", "marketing", "medium", ["Manager", "Finance"]),
])
def test_review_rules_explain_boundaries_and_budget_escalation(amount, priority, department, risk, reviewers):
    context = build_review_context({"amount": amount, "priority": priority,
        "department": department, "risk_level": risk}, "manager_review")
    assert context["rule_risk_level"] == risk
    assert context["matches_assessment"] is True
    assert context["review_path"] == reviewers
    assert len(context["risk_rules"]) == 4


def test_rule_discrepancy_is_not_presented_as_agreement():
    context = build_review_context({"amount": 95000, "priority": "urgent",
        "department": "engineering", "risk_level": "medium"}, "manager_review")
    assert context["matches_assessment"] is False
    assert context["rule_risk_level"] == "critical"


def test_skipped_budget_check_still_supplies_reference_without_changing_state():
    state = {"amount": 95000, "priority": "urgent", "department": "engineering",
             "risk_level": "critical", "department_budget": None, "within_budget": None}
    context = build_review_context(state, "manager_review")
    assert context["budget_reference"]["department_budget"] == 50000
    assert context["budget_reference"]["over_budget_amount"] == 45000
    assert context["budget_reference"]["remaining_if_approved"] == -45000
    assert context["budget_reference"]["automatically_validated"] is False
    assert state["within_budget"] is None
    assert state["department_budget"] is None
    assert context["review_path"] == ["Manager", "Finance", "Executive"]


def test_completed_budget_check_is_distinguished_from_reference():
    context = build_review_context({"amount": 35000, "priority": "normal", "department": "marketing",
        "risk_level": "medium", "within_budget": False}, "finance_review")
    assert context["budget_reference"]["automatically_validated"] is True


def test_business_case_stays_requester_reported_and_does_not_leak_between_requests():
    from backend.agent.nodes import submit_request
    state = {"request_id": "NEW", "amount": 95000, "department": "engineering", "title": "Servers",
        "description": "Proposed replacement", "justification": "Restore service urgently", "priority": "urgent",
        "business_case": {"request_id": "NEW", "current_situation": "unknown", "evidence": "Not confirmed",
                          "business_impact": "Potential impact only", "urgency_reason": "Requester asks for same-day action"}}
    first = submit_request(state)
    assert first["is_valid"] is True
    assert first["business_case"]["current_situation"] == "unknown"
    second = submit_request({**state, "request_id": "NEXT"})
    assert second["business_case"] is None


def test_business_case_injection_is_validated():
    from backend.agent.nodes import submit_request
    result = submit_request({"request_id": "INJECTION", "amount": 500, "department": "engineering",
        "title": "Test", "description": "Test", "justification": "Test",
        "business_case": {"request_id": "INJECTION", "current_situation": "unknown",
                          "evidence": "<script>alert(1)</script>"}})
    assert result["is_valid"] is False


@pytest.mark.parametrize("stage", ["manager_review", "finance_review", "final_signoff"])
def test_review_interrupt_contains_explainable_rules_and_business_facts(stage):
    graph = StateGraph(ApprovalState)
    graph.add_node("review", getattr(nodes, stage))
    graph.add_edge(START, "review")
    graph.add_edge("review", END)
    app = graph.compile(checkpointer=MemorySaver())
    result = app.invoke({"request_id": "CONTEXT-001", "title": "Emergency replacement", "amount": 95000,
        "department": "engineering", "priority": "urgent", "risk_level": "critical",
        "description": "Failed server", "justification": "Restore service", "messages": []},
        {"configurable": {"thread_id": stage}})
    payload = result["__interrupt__"][0].value
    assert payload["priority"] == "urgent"
    assert payload["justification"] == "Restore service"
    assert payload["policy_context"]["matches_assessment"] is True
    assert len(payload["policy_context"]["review_focus"]) == 3
    assert "skip automatic budget" in payload["policy_context"]["budget_rule"]
