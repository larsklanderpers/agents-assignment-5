"""
Input validation guardrails for the Financial Approval System.

Students implement validation functions that enforce safety rules
on incoming financial requests.

Part 2: Safety Guardrails (10 points from this file)
"""

import math
import re
from html import unescape
from backend.config import BUDGET_CEILING, VALID_DEPARTMENTS

# --- GIVEN: Blocked patterns for SQL injection detection ---
BLOCKED_PATTERNS = [
    "drop table", "delete from", "insert into", "update set",
    "union select", "' or '1'='1", "'; --", "<script>",
    "javascript:", "onclick=", "onerror=", "eval(",
    "__import__", "os.system", "subprocess",
]

# --- GIVEN: Maximum field lengths ---
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 2000
MAX_JUSTIFICATION_LENGTH = 2000


def validate_request(
    amount: float,
    department: str,
    title: str,
    description: str,
    justification: str,
) -> tuple[bool, str]:
    """
    Validate a financial request against safety rules.

    TODO (5 points):
    - Reject if amount <= 0 (message: "Amount must be positive")
    - Reject if amount > BUDGET_CEILING (message: "Amount exceeds budget ceiling of ${BUDGET_CEILING:,.2f}")
    - Reject if department not in VALID_DEPARTMENTS (message: "Invalid department: {department}")
    - Reject if title exceeds MAX_TITLE_LENGTH (message: "Title too long")
    - Call sanitize_text() on title, description, and justification
      - If any returns (False, message), reject with that message
    - If all checks pass, return (True, "Request validated successfully")

    Args:
        amount: Requested dollar amount
        department: Department name
        title: Request title
        description: Request description
        justification: Business justification

    Returns:
        Tuple of (is_valid, message)
    """
    valid, message = validate_amount(amount)
    if not valid:
        return valid, message
    if department not in VALID_DEPARTMENTS:
        return False, f"Invalid department: {department}"
    for name, value, limit in (("title", title, MAX_TITLE_LENGTH),
                               ("description", description, MAX_DESCRIPTION_LENGTH),
                               ("justification", justification, MAX_JUSTIFICATION_LENGTH)):
        if not isinstance(value, str):
            return False, f"{name.capitalize()} must be text"
        if len(value) > limit:
            return False, f"{name.capitalize()} too long"
        safe, message = sanitize_text(value, name)
        if not safe:
            return False, message
    return True, "Request validated successfully"


def validate_amount(amount: float) -> tuple[bool, str]:
    """
    Validate the requested amount.

    TODO (2 points):
    - Return (False, "Amount must be positive") if amount <= 0
    - Return (False, "Amount exceeds budget ceiling of ${BUDGET_CEILING:,.2f}") if amount > BUDGET_CEILING
    - Return (True, "Amount is valid") otherwise

    Args:
        amount: Dollar amount to validate

    Returns:
        Tuple of (is_valid, message)
    """
    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or (isinstance(amount, float) and not math.isfinite(amount)):
        return False, "Amount must be a finite number"
    if amount <= 0:
        return False, "Amount must be positive"
    if amount > BUDGET_CEILING:
        return False, f"Amount exceeds budget ceiling of ${BUDGET_CEILING:,.2f}"
    return True, "Amount is valid"


def sanitize_text(text: str, field_name: str = "text") -> tuple[bool, str]:
    """
    Check text for injection attacks and malicious content.

    TODO (3 points):
    - Convert text to lowercase for comparison
    - Check if any BLOCKED_PATTERNS appear in the lowercased text
    - If found, return (False, "Blocked content detected in {field_name}: suspicious pattern")
    - If clean, return (True, text)  — return the ORIGINAL text, not lowercased

    Args:
        text: The text to sanitize
        field_name: Name of the field (for error messages)

    Returns:
        Tuple of (is_safe, original_text_or_error_message)
    """
    if not isinstance(text, str):
        return False, f"{field_name} must be text"
    normalized = re.sub(r"\s+", " ", unescape(text).lower())
    if any(pattern in normalized for pattern in BLOCKED_PATTERNS) or re.search(
        r"<\s*script\b|on\w+\s*=|javascript\s*:", normalized
    ):
        return False, f"Blocked content detected in {field_name}: suspicious pattern"
    return True, text


def validate_business_case(business_case) -> tuple[bool, str]:
    """Optional for existing API clients; supplied business-case fields are validated."""
    if business_case is None:
        return True, "No structured business case supplied"
    if not isinstance(business_case, dict):
        return False, "Business case must be an object"
    if business_case.get("current_situation") not in ("unknown", "confirmed_outage", "degraded", "preventive", "other"):
        return False, "Invalid current situation"
    for name in ("evidence", "business_impact", "urgency_reason"):
        value = business_case.get(name, "")
        if not isinstance(value, str) or len(value) > MAX_JUSTIFICATION_LENGTH:
            return False, f"Invalid business-case {name}"
        safe, message = sanitize_text(value, name)
        if not safe:
            return False, message
    return True, "Business case validated"
