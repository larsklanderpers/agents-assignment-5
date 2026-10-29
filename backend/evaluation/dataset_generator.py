"""
LLM-based evaluation dataset generator for the Financial Approval System.

Students implement functions to:
1. Generate diverse test cases using an LLM
2. Generate edge/adversarial cases
3. Upload datasets to LangSmith
4. Validate generated datasets

Part 5: Dataset Generation (16 points)
"""

import json
import math
import re


def _generate(prompt, num_cases, llm):
    if type(num_cases) is not int or num_cases <= 0:
        raise ValueError("num_cases must be a positive integer")
    if llm is None:
        from backend.config import get_llm
        llm = get_llm()
    request_prompt = prompt.format(num_cases=num_cases, departments=", ".join(VALID_DEPARTMENTS))
    request_prompt += ("\nBudget escalation overrides the generic low/medium paths. For each valid request "
        "compare its amount with its department's budget: low + over budget adds manager_review; "
        "medium + over budget adds finance_review AFTER validate_budget. High/critical skip the budget check.")
    errors = []
    for attempt in range(3):
        response = llm.invoke(request_prompt)
        text = response.text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
        try:
            dataset = json.loads(text)
        except json.JSONDecodeError:
            dataset = None
        valid, errors = validate_generated_dataset(dataset)
        if valid:
            if len(dataset) != num_cases:
                errors.append(f"Expected {num_cases} cases; received {len(dataset)}")
            for case in dataset:
                expected = _policy_reference(case["input"])
                if case["expected"] != expected:
                    errors.append(f"{case['input']['request_id']}: expected labels must be {json.dumps(expected)}")
        if not errors:
            return dataset
        if attempt < 2:
            request_prompt += ("\nReturn the corrected complete array, preserving the input fields where valid. "
                "Previous output:\n" + text + "\nCorrect these validation errors: " + "; ".join(errors))
    raise ValueError("Invalid generated dataset after 3 attempts: " + "; ".join(errors))


def _policy_reference(inputs):
    """Independent policy labels prevent an LLM-generated evaluation baseline from drifting."""
    from backend.guardrails.input_validator import validate_request
    valid, _ = validate_request(*(inputs[k] for k in ("amount", "department", "title", "description", "justification")))
    path = ["submit_request"]
    if not valid:
        return {"risk_level": None, "status": "rejected", "approval_path": path + ["handle_rejection"], "human_reviews": 0}
    amount = inputs["amount"]
    risk = ("critical" if amount > 50000 and inputs["priority"] == "urgent" else
            "high" if amount > 50000 else "medium" if amount > 10000 else "low")
    path.append("assess_risk")
    over_budget = amount > DEPARTMENT_BUDGETS[inputs["department"]]
    if risk == "low":
        path += ["validate_budget"] + (["manager_review"] if over_budget else [])
    elif risk == "medium":
        path += ["manager_review", "validate_budget"] + (["finance_review"] if over_budget else [])
    else:
        path += ["manager_review", "finance_review"] + (["final_signoff"] if risk == "critical" else [])
    path.append("process_request")
    return {"risk_level": risk, "status": "approved", "approval_path": path,
            "human_reviews": sum(s in ("manager_review", "finance_review", "final_signoff") for s in path)}

# ---------------------------------------------------------------------------
# Constants (GIVEN — do not modify)
# ---------------------------------------------------------------------------

VALID_DEPARTMENTS = ["engineering", "marketing", "operations", "research", "hr"]

BUDGET_CEILING = 100_000

DEPARTMENT_BUDGETS = {
    "engineering": 50000,
    "marketing": 30000,
    "operations": 40000,
    "research": 60000,
    "hr": 5000,
}

DATASET_SCHEMA = {
    "input": {
        "request_id": "str — unique identifier (e.g., 'GEN-001')",
        "title": "str — short description of the purchase",
        "description": "str — detailed description",
        "amount": "float — dollar amount (can be negative for edge cases)",
        "department": "str — one of VALID_DEPARTMENTS",
        "requester": "str — person making the request",
        "justification": "str — business justification",
        "priority": "str — one of: low, normal, high, urgent",
    },
    "expected": {
        "risk_level": "str or None: one of low, medium, high, critical; None (JSON null) "
                      "when the request is rejected at submit_request, because assess_risk never runs",
        "status": "str — one of: approved, rejected",
        "approval_path": "list[str] — ordered list of workflow stages",
        "human_reviews": "int — number of human review interrupts expected",
    },
}

OUTPUT_FORMAT = """
Output format (validate_generated_dataset rejects a case that does not follow it):
Each test case is a JSON object with exactly two keys, "input" and "expected".
"input" has all 8 of these fields:
  "request_id": string, unique (e.g. "GEN-001")
  "title": string, short name of the purchase
  "description": string, details of the purchase
  "amount": number, not a string (dollars)
  "department": one of {departments}
  "requester": string, name of the person making the request
  "justification": string, business reason for the purchase
  "priority": one of "low", "normal", "high", "urgent"
"expected" has all 4 of these fields:
  "risk_level": one of "low", "medium", "high", "critical", or null when the request is
    rejected at submit_request (its approval_path has no "assess_risk")
  "status": "approved" or "rejected" (lowercase)
  "approval_path": list of stage names in order, taken from: "submit_request",
    "assess_risk", "validate_budget", "manager_review", "finance_review",
    "final_signoff", "process_request", "handle_rejection"
  "human_reviews": integer >= 0, the number of "manager_review", "finance_review" and
    "final_signoff" stages in approval_path
Use these key names exactly ("approval_path", not "path"; "human_reviews", not
"review_count" or "required_reviews"). risk_level, status and priority are lowercase.
Expected values assume every human reviewer approves, so "rejected" is only for
requests rejected at submit_request.

Example of one test case:
{{"input": {{"request_id": "GEN-001", "title": "Team Laptops",
  "description": "Three laptops for new hires", "amount": 4500.0,
  "department": "engineering", "requester": "Dana Lee",
  "justification": "New hires start next month", "priority": "normal"}},
 "expected": {{"risk_level": "low", "status": "approved",
  "approval_path": ["submit_request", "assess_risk", "validate_budget", "process_request"],
  "human_reviews": 0}}}}

Return ONLY a JSON array of test case objects. No markdown, no explanation.
"""

GENERATION_PROMPT = """You are a test case generator for a Financial Approval System.

Generate {num_cases} diverse test cases for evaluating the system. Each test case
should be a JSON object with "input" and "expected" fields.

Business Rules:
- Amounts <= $10,000: low risk, auto-approved (0 human reviews)
  Path: submit_request → assess_risk → validate_budget → process_request
- Amounts $10,001-$50,000: medium risk, needs manager review (1 human review)
  Path: submit_request → assess_risk → manager_review → validate_budget → process_request
- Amounts $50,001-$100,000: high risk, needs manager + finance review (2 human reviews)
  Path: submit_request → assess_risk → manager_review → finance_review → process_request
- Amounts > $100,000: rejected (exceeds budget ceiling)
  Path: submit_request → handle_rejection
- Zero or negative amounts: rejected (invalid)
  Path: submit_request → handle_rejection
- Requests rejected at submit_request never reach assess_risk: their expected
  risk_level is null
- Priority "urgent" + amount > $50,000: critical risk, needs 3 reviews
  Path: submit_request → assess_risk → manager_review → finance_review → final_signoff → process_request
- Department budgets: engineering $50,000, marketing $30,000, operations $40,000,
  research $60,000, hr $5,000. validate_budget escalates when the amount is over budget:
  - Low risk over budget: manager review (1 human review)
    Path: submit_request → assess_risk → validate_budget → manager_review → process_request
  - Medium risk over budget: finance review after the budget check (2 human reviews)
    Path: submit_request → assess_risk → manager_review → validate_budget → finance_review → process_request

Valid departments: {departments}
Valid priorities: low, normal, high, urgent

Generate realistic financial requests covering different departments, amounts,
and risk levels. Include a mix of approved and rejected cases.
""" + OUTPUT_FORMAT

EDGE_CASE_PROMPT = """You are a test case generator for a Financial Approval System.
Generate {num_cases} EDGE CASES and ADVERSARIAL scenarios.

Focus on boundary conditions and tricky scenarios:
1. Amounts exactly at thresholds ($10,000, $50,000, $100,000)
2. Negative amounts or zero amounts
3. Very large amounts (> $1,000,000)
4. Unusual descriptions that might confuse the system
5. Requests that test policy boundaries

Business Rules:
- Amounts <= $10,000: low risk, auto-approved (0 human reviews)
  Path: submit_request → assess_risk → validate_budget → process_request
- Amounts $10,001-$50,000: medium risk, manager review (1 human review)
  Path: submit_request → assess_risk → manager_review → validate_budget → process_request
- Amounts $50,001-$100,000: high risk, manager + finance review (2 human reviews)
  Path: submit_request → assess_risk → manager_review → finance_review → process_request
- Priority "urgent" + amount > $50,000: critical risk, 3 reviews (no budget check)
  Path: submit_request → assess_risk → manager_review → finance_review → final_signoff → process_request
- Rejected at submit_request: amounts > $100,000, zero or negative amounts, and text
  containing SQL or script injection (for example "<script>" or "' or '1'='1")
  Path: submit_request → handle_rejection. These never reach assess_risk: their
  expected risk_level is null and human_reviews is 0
- Over the department budget (engineering $50,000, marketing $30,000, operations $40,000,
  research $60,000, hr $5,000), only for low and medium risk:
  - Low risk: submit_request → assess_risk → validate_budget → manager_review → process_request (1 review)
  - Medium risk: submit_request → assess_risk → manager_review → validate_budget → finance_review → process_request (2 reviews)

Valid departments: {departments}
Use only these departments: an invalid department fails validate_generated_dataset.
""" + OUTPUT_FORMAT


# ═══════════════════════════════════════════════════════════════════════════
# Student TODO — Dataset Generation Functions (16 points)
# ═══════════════════════════════════════════════════════════════════════════

def generate_eval_dataset(num_cases=10, llm=None):
    """
    Generate diverse evaluation test cases using an LLM.

    TODO (4 points):
    - If llm is None, create one using: from backend.config import get_llm
    - Format GENERATION_PROMPT with num_cases and VALID_DEPARTMENTS
    - Invoke the LLM with the formatted prompt: response = llm.invoke(prompt)
    - Parse the JSON response into a list of dicts: json.loads(response.text)
      (.text is a property, no parentheses; response.content is a list of content
      blocks with Gemini, and json.loads() on it raises TypeError. If the model wraps
      the array in a ```json fence anyway, strip the fence before json.loads)
    - Each dict must match DATASET_SCHEMA structure
    - Return the list of generated test cases

    Args:
        num_cases: Number of test cases to generate (default 10)
        llm: Optional LangChain LLM instance (if None, use get_llm())

    Returns:
        list[dict]: Generated test cases matching DATASET_SCHEMA

    Example:
        dataset = generate_eval_dataset(num_cases=5)
        # Returns: [{"input": {...}, "expected": {...}}, ...]
    """
    return _generate(GENERATION_PROMPT, num_cases, llm)


def generate_edge_cases(num_cases=5, llm=None):
    """
    Generate boundary and adversarial test cases using an LLM.

    TODO (4 points):
    - If llm is None, create one using: from backend.config import get_llm
    - Format EDGE_CASE_PROMPT with num_cases and VALID_DEPARTMENTS
    - Invoke the LLM with the formatted prompt: response = llm.invoke(prompt)
    - Parse the JSON response into a list of dicts: json.loads(response.text)
      (.text is a property, no parentheses; response.content is a list of content
      blocks with Gemini, and json.loads() on it raises TypeError. If the model wraps
      the array in a ```json fence anyway, strip the fence before json.loads)
    - Focus on boundary conditions (exact thresholds, negatives, etc.)
    - Return the list of generated edge cases

    Args:
        num_cases: Number of edge cases to generate (default 5)
        llm: Optional LangChain LLM instance (if None, use get_llm())

    Returns:
        list[dict]: Generated edge cases matching DATASET_SCHEMA
    """
    return _generate(EDGE_CASE_PROMPT, num_cases, llm)


def upload_to_langsmith(dataset, dataset_name="financial-approval-eval"):
    """
    Upload a dataset to LangSmith for evaluation runs.

    TODO (4 points):
    - Import langsmith and create a Client: client = langsmith.Client()
      (it reads LANGSMITH_API_KEY from the environment. Importing backend.config
      loads .env; if nothing has loaded it, the client sends no key and
      LangSmith answers 401 "Invalid token")
    - Create a new dataset: ls_dataset = client.create_dataset(dataset_name=dataset_name)
      (use a new name; the `dataset` argument is your list of test cases)
    - For each test case in the dataset, create an example:
        client.create_example(
            inputs=case["input"],
            outputs=case["expected"],
            dataset_id=ls_dataset.id,
        )
    - Return the dataset ID as a string

    Args:
        dataset: list[dict] — test cases with "input" and "expected" keys
        dataset_name: str — name for the LangSmith dataset

    Returns:
        str: The LangSmith dataset ID

    Raises:
        ValueError: If dataset is empty
    """
    from backend import config  # Load the local .env before creating the client.
    import langsmith
    valid, errors = validate_generated_dataset(dataset)
    if not valid:
        raise ValueError("Invalid dataset: " + "; ".join(errors))
    client = langsmith.Client()
    ls_dataset = client.create_dataset(dataset_name=dataset_name)
    for case in dataset:
        client.create_example(inputs=case["input"], outputs=case["expected"], dataset_id=ls_dataset.id)
    return str(ls_dataset.id)


def validate_generated_dataset(dataset):
    """
    Validate that a generated dataset conforms to the expected schema.

    TODO (4 points):
    - Check the following and collect error messages for failures:
      1. dataset is a non-empty list
      2. Each entry has "input" and "expected" top-level keys
      3. Each input has required fields: request_id, title, description,
         amount, department, requester, justification, priority
      4. Each expected has required fields: risk_level, status,
         approval_path, human_reviews
      5. amount is a number (int or float)
      6. department is in VALID_DEPARTMENTS
      7. risk_level is one of: low, medium, high, critical, or None when
         approval_path skips "assess_risk" (rejected at submit_request)
      8. status is one of: approved, rejected
      9. approval_path is a list
      10. human_reviews is an int >= 0
    - Return a tuple: (is_valid: bool, errors: list[str])
      - is_valid is True if no errors found
      - errors is a list of descriptive error strings

    Args:
        dataset: list[dict] — the dataset to validate

    Returns:
        tuple[bool, list[str]]: (is_valid, error_messages)

    Example:
        valid, errors = validate_generated_dataset([{"input": {}, "expected": {}}])
        # valid = False, errors = ["Case 1: input missing 'request_id'", ...]
    """
    if not isinstance(dataset, list) or not dataset:
        return False, ["Dataset must be a non-empty list"]
    errors, identifiers = [], set()
    input_fields = {"request_id", "title", "description", "amount", "department", "requester", "justification", "priority"}
    expected_fields = {"risk_level", "status", "approval_path", "human_reviews"}
    stages = {"submit_request", "assess_risk", "validate_budget", "manager_review", "finance_review", "final_signoff", "process_request", "handle_rejection"}
    for i, case in enumerate(dataset, 1):
        prefix = f"Case {i}: "
        if not isinstance(case, dict) or not isinstance(case.get("input"), dict) or not isinstance(case.get("expected"), dict):
            errors.append(prefix + "input and expected must be objects")
            continue
        inputs, expected = case["input"], case["expected"]
        errors.extend(prefix + f"input missing '{key}'" for key in sorted(input_fields - inputs.keys()))
        errors.extend(prefix + f"expected missing '{key}'" for key in sorted(expected_fields - expected.keys()))
        for key in input_fields - {"amount"}:
            if key in inputs and not isinstance(inputs[key], str):
                errors.append(prefix + f"{key} must be a string")
        identifier = inputs.get("request_id")
        if isinstance(identifier, str):
            if not identifier or identifier in identifiers:
                errors.append(prefix + "request_id must be non-empty and unique")
            identifiers.add(identifier)
        amount = inputs.get("amount")
        if type(amount) not in (int, float) or (isinstance(amount, float) and not math.isfinite(amount)):
            errors.append(prefix + "amount must be a finite number")
        if inputs.get("department") not in VALID_DEPARTMENTS:
            errors.append(prefix + "invalid department")
        if inputs.get("priority") not in ("low", "normal", "high", "urgent"):
            errors.append(prefix + "invalid priority")
        path = expected.get("approval_path")
        valid_path = isinstance(path, list) and all(isinstance(s, str) and s in stages for s in path)
        if not valid_path:
            errors.append(prefix + "approval_path must be a list of valid stages")
        risk = expected.get("risk_level")
        if risk not in ("low", "medium", "high", "critical", None):
            errors.append(prefix + "invalid risk_level")
        if valid_path and (risk is None) != ("assess_risk" not in path):
            errors.append(prefix + "risk_level must be null only when assess_risk was skipped")
        if expected.get("status") not in ("approved", "rejected"):
            errors.append(prefix + "invalid status")
        count = expected.get("human_reviews")
        if type(count) is not int or count < 0:
            errors.append(prefix + "human_reviews must be a non-negative integer")
        elif valid_path and count != sum(s in ("manager_review", "finance_review", "final_signoff") for s in path):
            errors.append(prefix + "human_reviews does not match approval_path")
    return not errors, errors
