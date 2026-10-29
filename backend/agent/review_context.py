"""Explain the configured workflow policy without relying on LLM wording."""
from backend.config import BUDGET_CEILING, DEPARTMENT_BUDGETS, HIGH_RISK_THRESHOLD, MEDIUM_RISK_THRESHOLD


REVIEW_FOCUS = {
    "manager_review": [
        "Confirm the business need and evidence for any stated urgency.",
        "Consider alternatives and the consequences of delaying the request.",
        "Record why the request should proceed or be rejected.",
    ],
    "finance_review": [
        "Verify the cost estimate and available funding, or document the justification for a budget exception.",
        "If the automatic budget check was skipped, verify funding independently; manager approval is not a budget check.",
        "Record the financial basis for approval or rejection.",
    ],
    "final_signoff": [
        "Review the manager and finance decisions and any conditions or unresolved concerns.",
        "Decide whether the business benefit and urgency justify the remaining financial risk.",
        "Record the reason for final approval or rejection.",
    ],
}


def build_review_context(state, stage):
    amount = state["amount"]
    priority = state.get("priority") or "normal"
    assessed = state.get("risk_level")
    budget = DEPARTMENT_BUDGETS.get(state["department"], 0)
    low_limit = f"${MEDIUM_RISK_THRESHOLD:,.0f}"
    high_limit = f"${HIGH_RISK_THRESHOLD:,.0f}"
    ceiling = f"${BUDGET_CEILING:,.0f}"
    risk_rules = [
        {"level": "low", "condition": f"Positive amount up to and including {low_limit}."},
        {"level": "medium", "condition": f"Amount above {low_limit}, up to and including {high_limit}."},
        {"level": "high", "condition": f"Amount above {high_limit}, up to and including {ceiling}, unless urgent."},
        {"level": "critical", "condition": f"Urgent priority AND amount above {high_limit}, within the {ceiling} ceiling."},
    ]
    rule_level = ("critical" if priority == "urgent" and amount > HIGH_RISK_THRESHOLD else
                  "high" if amount > HIGH_RISK_THRESHOLD else
                  "medium" if amount > MEDIUM_RISK_THRESHOLD else "low")
    if rule_level == "critical":
        trigger = f"This request is ${amount:,.2f}, above {high_limit}, and its priority is Urgent. Both critical-risk conditions are met."
    else:
        condition = next(rule["condition"] for rule in risk_rules if rule["level"] == rule_level)
        trigger = f"This request is ${amount:,.2f} with {priority.capitalize()} priority. {rule_level.capitalize()} rule: {condition}"
    routes = {
        "low": ["Manager"] if amount > budget else [],
        "medium": ["Manager", "Finance"] if amount > budget else ["Manager"],
        "high": ["Manager", "Finance"],
        "critical": ["Manager", "Finance", "Executive"],
    }
    reasons = {
        "manager_review": ("Low risk, but the amount exceeds the department budget, so manager review is required."
                           if assessed == "low" else "Medium, high and critical requests require manager review first."),
        "finance_review": ("The medium-risk request exceeded its department budget after manager approval, so finance review is required."
                           if assessed == "medium" else "High and critical requests require finance review after manager approval."),
        "final_signoff": "Critical requests require executive sign-off after manager and finance approval.",
    }
    return {
        "risk_rules": risk_rules,
        "rule_risk_level": rule_level,
        "matches_assessment": assessed == rule_level,
        "trigger": trigger,
        "review_path": routes.get(assessed, []),
        "stage_reason": reasons[stage],
        "ceiling_rule": f"Zero or negative amounts, and amounts above {ceiling}, are rejected before risk assessment or human review.",
        "budget_rule": ("High and critical requests skip automatic budget validation; finance must review funding."
                        if assessed in ("high", "critical") else
                        f"Department budget: ${budget:,.2f}. Low-risk over-budget requests escalate to a manager; medium-risk over-budget requests escalate to finance after the manager and budget check."),
        "review_focus": REVIEW_FOCUS[stage],
        "budget_reference": {
            "department_budget": budget,
            "requested_amount": amount,
            "remaining_if_approved": budget - amount,
            "over_budget_amount": max(0, amount - budget),
            "automatically_validated": state.get("within_budget") is not None,
            "source": "Configured department budget; this is not a live accounting balance.",
        },
    }
