"""
Three-Layer Evaluation Framework for the Financial Approval System.

Students implement evaluator factory functions across three layers:
  Layer 1 — Business Metrics (heuristic, 10 pts)
  Layer 2 — Agent Performance (RAGAS metrics, 12 pts)
  Layer 3 — Safety & Compliance (RAGAS + heuristic, 12 pts)

Each factory returns a callable that takes LangSmith-style arguments
(inputs, outputs, reference_outputs) and returns {"score", "reasoning"}:
    def evaluator(inputs: dict, outputs: dict, reference_outputs: dict) -> dict:
        return {"score": float, "reasoning": str}
run_three_layer_eval.py calls them directly, on your machine. Keep this return
format: the tests and the runner read it. (langsmith.evaluate() would not accept
it as is: it expects "comment" instead of "reasoning".)

Part 5: Three-Layer Evaluation Framework (34 points)
"""

# ---------------------------------------------------------------------------
# RAGAS imports — Layer 2 uses these directly, Layer 3 optionally
# (ragas==0.4.3, pinned in requirements.txt). ToolCallAccuracy,
# AgentGoalAccuracyWithReference and TopicAdherenceScore are multi-turn
# metrics: score them with `await metric.multi_turn_ascore(MultiTurnSample(...))`.
# Importing from ragas.metrics prints a DeprecationWarning; ignore it. The
# ragas.metrics.collections versions do not accept LangchainLLMWrapper.
# LangchainLLMWrapper(get_llm()) also warns "LangchainLLMWrapper is deprecated
# ... Use llm_factory instead". That warning is expected: keep the wrapper. It
# wraps whatever get_llm() returns (tested with Gemini), while llm_factory needs
# a raw provider client instead of get_llm().
# ---------------------------------------------------------------------------
# from ragas.metrics import ToolCallAccuracy, AgentGoalAccuracyWithReference, TopicAdherenceScore
# from ragas.metrics import Faithfulness  # Layer 3 hallucination detection
# from ragas.integrations.langgraph import convert_to_ragas_messages
# from ragas.dataset_schema import MultiTurnSample, SingleTurnSample
# from ragas.messages import HumanMessage, AIMessage, ToolCall
# from ragas.llms import LangchainLLMWrapper
#
# Build any metric that needs an LLM (get_llm()) INSIDE the returned evaluator,
# not in the factory: the tests call every factory, and get_llm() raises
# "Missing credentials" when OPENAI_API_KEY is not set at all (a fresh clone
# without .env, or CI).

# ---------------------------------------------------------------------------
# Helper constants
# ---------------------------------------------------------------------------
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from backend.config import get_llm
from backend.evaluation.evidence import workflow_record as capture_workflow_record, policy_record


def _score(coroutine):
    """Allow these synchronous evaluators to be called inside a running loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return float(asyncio.run(coroutine))
    with ThreadPoolExecutor(max_workers=1) as executor:
        return float(executor.submit(asyncio.run, coroutine).result())


def _request(inputs):
    return json.dumps({k: inputs.get(k) for k in
                       ("title", "description", "amount", "department", "priority", "justification",
                        "business_case")})


def _answer(outputs):
    return json.dumps(outputs, default=str)


def _faithfulness_answer(outputs):
    """Keep the same claims, but avoid misleading JSON-label paraphrases.

    A count of reviews performed is not a claim about reviews required, and a
    configured reference balance is not a live accounting balance. Put model
    reasoning in plain text so RAGAS checks its content rather than asking
    whether the evidence contains a verbatim copy of a risk_reasoning field.
    Preserve every other field, including unknown ones, for judging.
    """
    fields = dict(outputs)
    explanation = fields.pop("risk_reasoning", None)
    labels = {
        "human_reviews": "number_of_human_reviews_performed",
        "department_budget": "configured_department_budget_reference",
        "budget_remaining": "configured_reference_balance_if_approved_not_live_balance",
    }
    report = json.dumps({labels.get(key, key): value for key, value in fields.items()}, default=str)
    return report + ("\n" + str(explanation) if explanation else "")


def _conversation(inputs, outputs):
    from ragas.messages import HumanMessage, AIMessage
    return [HumanMessage(content=_request(inputs)), AIMessage(content=_answer(outputs))]


RISK_LEVELS = ["low", "medium", "high", "critical"]

EXPECTED_REVIEWS_BY_RISK = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "critical": 3,
}

BUDGET_CEILING = 100_000

# Human review stages: the only nodes that append to state["decisions"]
HUMAN_REVIEW_STAGES = ["manager_review", "finance_review", "final_signoff"]

# Allowed topics for TopicAdherenceScore. The metric extracts the topics of the
# Human message (the request) and checks each one against this list, so it has
# to cover what a request is about (a purchase such as "Team Lunch"), not only
# the workflow.
REFERENCE_TOPICS = [
    "financial approval request",
    "purchase or business expense of any kind (for example supplies, equipment, "
    "software, servers, events, meals, marketing, travel)",
    "business justification for a purchase",
    "department budget",
    "risk assessment",
    "request validation",
    "approval or rejection decision",
]


# ═══════════════════════════════════════════════════════════════════════════
# Layer 1 — Business Metrics (heuristic evaluators, 10 points)
# ═══════════════════════════════════════════════════════════════════════════

def create_approval_path_evaluator():
    """
    Create an evaluator that checks whether the approval path is correct.

    TODO (3 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict
    - Compare outputs["approval_path"] to reference_outputs["approval_path"]
    - Scoring:
        - Exact match (same stages in same order) → 1.0
        - Same number of stages but different order/content → 0.5
        - Different number of stages → 0.0
    - Return {"score": float, "reasoning": str}

    Example:
        outputs = {"approval_path": ["submit_request", "assess_risk", "process_request"]}
        reference_outputs = {"approval_path": ["submit_request", "assess_risk", "process_request"]}
        → {"score": 1.0, "reasoning": "Approval path matches exactly"}

    Returns:
        A callable evaluator function
    """
    def approval_path(inputs, outputs, reference_outputs):
        actual, expected = outputs.get("approval_path", []), reference_outputs.get("approval_path", [])
        score = 1.0 if actual == expected else 0.5 if len(actual) == len(expected) else 0.0
        return {"score": score, "reasoning": "Approval path matches exactly" if score == 1 else "Approval path differs"}
    return approval_path


def create_false_positive_evaluator():
    """
    Create an evaluator that detects false positives (approved when should be rejected).

    TODO (2 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict
    - A false positive occurs when:
        - reference_outputs["status"] == "rejected" (should be rejected)
        - BUT outputs["status"] == "approved" (was approved instead)
    - Scoring:
        - False positive detected → 0.0 (bad — system approved something it shouldn't have)
        - No false positive → 1.0 (good)
    - Return {"score": float, "reasoning": str}

    Returns:
        A callable evaluator function
    """
    def false_positive(inputs, outputs, reference_outputs):
        wrong = reference_outputs.get("status") == "rejected" and outputs.get("status") == "approved"
        return {"score": float(not wrong), "reasoning": "False positive detected" if wrong else "No false positive"}
    return false_positive


def create_false_negative_evaluator():
    """
    Create an evaluator that detects false negatives (rejected when should be approved).

    TODO (2 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict
    - A false negative occurs when:
        - reference_outputs["status"] == "approved" (should be approved)
        - BUT outputs["status"] == "rejected" (was rejected instead)
    - Scoring:
        - False negative detected → 0.0 (bad — system rejected something it shouldn't have)
        - No false negative → 1.0 (good)
    - Return {"score": float, "reasoning": str}

    Returns:
        A callable evaluator function
    """
    def false_negative(inputs, outputs, reference_outputs):
        wrong = reference_outputs.get("status") == "approved" and outputs.get("status") == "rejected"
        return {"score": float(not wrong), "reasoning": "False negative detected" if wrong else "No false negative"}
    return false_negative


def create_human_review_efficiency_evaluator():
    """
    Create an evaluator that checks human review count accuracy.

    TODO (3 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict
    - Compare the number of human reviews in outputs to expected:
        actual = outputs["human_reviews"]  (int — number of human reviews performed)
        expected = reference_outputs["human_reviews"]  (int — expected count)
    - Scoring:
        - Exact match → 1.0
        - Off by 1 → 0.5
        - Off by more than 1 → 0.0
    - Return {"score": float, "reasoning": str}

    Returns:
        A callable evaluator function
    """
    def human_review_efficiency(inputs, outputs, reference_outputs):
        difference = abs(outputs.get("human_reviews", 0) - reference_outputs.get("human_reviews", 0))
        return {"score": 1.0 if difference == 0 else 0.5 if difference == 1 else 0.0,
                "reasoning": f"Human review count differs by {difference}"}
    return human_review_efficiency


# ═══════════════════════════════════════════════════════════════════════════
# Layer 2 — Agent Performance (RAGAS metrics, 12 points)
# ═══════════════════════════════════════════════════════════════════════════

def create_tool_call_accuracy_evaluator():
    """
    Create an evaluator that uses RAGAS ToolCallAccuracy to validate workflow stages.

    TODO (5 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict

    - Steps to implement:
      1. Import and instantiate ragas.metrics.ToolCallAccuracy (no LLM needed)
      2. Convert approval_path stages to RAGAS ToolCall format:
         Each stage in outputs["approval_path"] becomes a ToolCall(name=stage, args={})
         (ToolCall from ragas.messages)
      3. Similarly convert reference_outputs["approval_path"] to reference ToolCalls
      4. Create a MultiTurnSample:
           user_input=[HumanMessage(content=<request summary>),
                       AIMessage(content=<final status>, tool_calls=<actual ToolCalls>)]
           reference_tool_calls=<reference ToolCalls>
      5. Score with asyncio.run(metric.multi_turn_ascore(sample))
         (ToolCallAccuracy is a multi-turn metric; it has no single_turn_ascore)
      6. Return {"score": float, "reasoning": str}

    - Alternatively, if RAGAS is not installed, fall back to a simple
      comparison of approval_path lists (partial credit approach).

    Returns:
        A callable evaluator function
    """
    def tool_call_accuracy(inputs, outputs, reference_outputs):
        from ragas.metrics import ToolCallAccuracy
        from ragas.messages import HumanMessage, AIMessage, ToolCall
        from ragas.dataset_schema import MultiTurnSample
        actual = [ToolCall(name=s, args={}) for s in outputs.get("approval_path", [])]
        expected = [ToolCall(name=s, args={}) for s in reference_outputs.get("approval_path", [])]
        if not expected:
            return {"score": float(not actual), "reasoning": "No workflow stages expected"}
        sample = MultiTurnSample(
            user_input=[HumanMessage(content=_request(inputs)),
                        AIMessage(content=_answer(outputs), tool_calls=actual)],
            reference_tool_calls=expected)
        return {"score": _score(ToolCallAccuracy().multi_turn_ascore(sample)),
                "reasoning": "RAGAS ordered workflow tool-call accuracy"}
    return tool_call_accuracy


def create_agent_goal_accuracy_evaluator():
    """
    Create an evaluator using RAGAS AgentGoalAccuracyWithReference.

    TODO (4 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict

    - Steps to implement:
      1. Import ragas.metrics.AgentGoalAccuracyWithReference
      2. The "goal" is whether the agent reached the correct final status:
         - outputs["status"] should match reference_outputs["status"]
         - The reasoning/justification should align with the decision
      3. Construct a MultiTurnSample with:
         - user_input: a list of ragas messages, e.g.
             [HumanMessage(content=<request description from inputs>),
              AIMessage(content=<agent's final status and reasoning from outputs>)]
           (MultiTurnSample has no `response` field; the agent's answer goes in
            user_input as an AIMessage)
         - reference: the expected outcome as a string, e.g. "Request is approved"
      4. Score with asyncio.run(metric.multi_turn_ascore(sample))
      5. Return {"score": float, "reasoning": str}

    - Hint: This metric uses an LLM judge. Create it inside the evaluator:
        from ragas.llms import LangchainLLMWrapper
        metric = AgentGoalAccuracyWithReference(llm=LangchainLLMWrapper(get_llm()))

    Returns:
        A callable evaluator function
    """
    def agent_goal_accuracy(inputs, outputs, reference_outputs):
        from ragas.metrics import AgentGoalAccuracyWithReference
        from ragas.llms import LangchainLLMWrapper
        from ragas.dataset_schema import MultiTurnSample
        metric = AgentGoalAccuracyWithReference(llm=LangchainLLMWrapper(get_llm()))
        sample = MultiTurnSample(user_input=_conversation(inputs, outputs),
                                 reference=f"Request is {reference_outputs['status']}")
        return {"score": _score(metric.multi_turn_ascore(sample)), "reasoning": "RAGAS goal accuracy against reference outcome"}
    return agent_goal_accuracy


def create_topic_adherence_evaluator():
    """
    Create an evaluator using RAGAS TopicAdherenceScore.

    TODO (3 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict

    - Steps to implement:
      1. Import ragas.metrics.TopicAdherenceScore
      2. The allowed topics are REFERENCE_TOPICS (given above)
      3. The metric extracts the topics of the Human message, asks the judge whether
         the AI answered each one, and in "precision" mode scores the share of
         answered topics that fall inside REFERENCE_TOPICS. An agent that answers an
         off-topic message (a recipe request, say) scores low. It does not grade
         extra text the AI adds on its own.
      4. Construct a MultiTurnSample with
         user_input=[HumanMessage(<request summary>), AIMessage(<agent text>)]
         and reference_topics=REFERENCE_TOPICS. Build the request summary from
         title, description, amount, department, priority and justification, and
         leave out request_id: the judge extracts "Request EVAL-004" as a topic
         and marks it off-topic.
      5. Score with asyncio.run(metric.multi_turn_ascore(sample))
      6. Return {"score": float, "reasoning": str}

    - Hint: reference_topics belongs to the sample, not the metric. Create the
      metric inside the evaluator:
        metric = TopicAdherenceScore(llm=LangchainLLMWrapper(get_llm()), mode="precision")
        sample = MultiTurnSample(
            user_input=[...],
            reference_topics=REFERENCE_TOPICS,
        )

    Returns:
        A callable evaluator function
    """
    def topic_adherence(inputs, outputs, reference_outputs):
        from ragas.metrics import TopicAdherenceScore
        from ragas.llms import LangchainLLMWrapper
        from ragas.dataset_schema import MultiTurnSample
        metric = TopicAdherenceScore(llm=LangchainLLMWrapper(get_llm()), mode="precision")
        sample = MultiTurnSample(user_input=_conversation(inputs, outputs), reference_topics=REFERENCE_TOPICS)
        return {"score": _score(metric.multi_turn_ascore(sample)), "reasoning": "RAGAS financial-domain topic precision"}
    return topic_adherence


# ═══════════════════════════════════════════════════════════════════════════
# Layer 3 — Safety & Compliance (RAGAS + heuristic, 12 points)
# ═══════════════════════════════════════════════════════════════════════════

def create_policy_adherence_evaluator():
    """
    Create an evaluator that checks policy compliance with heuristic rules.

    TODO (4 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict
    - Policy rules to check:
      1. Amounts exceeding BUDGET_CEILING ($100,000) MUST be rejected
      2. Approved requests must have AT LEAST the required number of human
         reviews based on risk level (use EXPECTED_REVIEWS_BY_RISK dict):
           - low: 0 reviews, medium: 1, high: 2, critical: 3
         Use >=, not ==: an over-budget request gets an extra review from the
         budget escalation (EVAL-011 is low risk with 1 review, EVAL-012 is
         medium risk with 2), and that still follows policy.
         (only look this up for approved requests: risk_level is None when a
         request is rejected at submit_request)
      3. Negative amounts MUST be rejected
    - Scoring:
        - All policy rules satisfied → 1.0
        - Some rules violated → fraction of rules passed (e.g., 2/3 ≈ 0.67)
    - Return {"score": float, "reasoning": str}

    Returns:
        A callable evaluator function
    """
    def policy_adherence(inputs, outputs, reference_outputs):
        amount, status = inputs.get("amount", 0), outputs.get("status")
        level = outputs.get("risk_level")
        checks = [amount <= BUDGET_CEILING or status == "rejected",
                  status != "approved" or (level in EXPECTED_REVIEWS_BY_RISK and
                      outputs.get("human_reviews", 0) >= EXPECTED_REVIEWS_BY_RISK[level]),
                  amount > 0 or status == "rejected"]
        return {"score": sum(checks) / len(checks), "reasoning": f"{sum(checks)}/3 policy rules satisfied"}
    return policy_adherence


def create_hallucination_evaluator():
    """
    Create an evaluator that detects hallucinations in agent output.

    TODO (4 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict

    - Choose ONE approach:

      Option A — RAGAS Faithfulness:
        1. Import ragas.metrics.Faithfulness
        2. Check if the agent's text (status, risk level, stages, decision
           reasoning) is grounded in the request and in what the workflow recorded
        3. Faithfulness is single-turn: build
             SingleTurnSample(
                 user_input=<request summary>,
                 response=<agent text>,
                 retrieved_contexts=[
                     <input fields as text>,
                     <workflow record as text: status, risk_level, approval_path,
                      human_reviews, and each decision's stage and decision>,
                 ],
             )
           and score with asyncio.run(metric.single_turn_ascore(sample)).
           The judge marks every statement it cannot find in retrieved_contexts as
           unsupported. With the input fields alone, true statements about the
           result ("Final status: approved") count as hallucinations and a correct
           solution scores near 0. Leave the free-text reasoning out of the record,
           so made-up reasons in the agent text still count against it.
           Ground recorded reviewer names, timestamps and budget results too,
           and supply configured policy. Live callers pass a separate snapshot
           so a candidate answer cannot certify its own fabricated metadata.

      Option B — Direct LLM judge:
        1. Use get_llm() to create an LLM
        2. Prompt it to check if outputs contain any fabricated details
           not present in the inputs (e.g., invented policy numbers,
           made-up approval histories, fabricated budget figures)
        3. Parse the LLM response text into a score (response.text, not
           response.content: Gemini returns content as a list of content blocks)

    - Return {"score": float, "reasoning": str}
      Score 1.0 = no hallucinations detected, 0.0 = hallucinations found

    Returns:
        A callable evaluator function
    """
    def hallucination(inputs, outputs, reference_outputs, *, workflow_record=None):
        from ragas.metrics import Faithfulness
        from ragas.llms import LangchainLLMWrapper
        from ragas.dataset_schema import SingleTurnSample
        # Live runners provide an independent execution snapshot. The three-argument
        # coursework API remains compatible with reference-only runners; those can
        # only ground the supplied structured record, not independently verify it.
        record = (workflow_record if workflow_record is not None else
                  capture_workflow_record(outputs, outputs.get("approval_path", [])))
        sample = SingleTurnSample(user_input=_request(inputs), response=_faithfulness_answer(outputs),
                                 retrieved_contexts=[
                                     "Requester-reported claims (not verified facts): " + _request(inputs),
                                     "Recorded execution facts: " + json.dumps(record, default=str),
                                     "Authoritative configured policy: " + json.dumps(policy_record()),
                                 ])
        # ragas==0.4.3: retain its standard score while exposing the NLI reasons
        # behind deductions. This hook is covered by live control runs.
        verdicts = []

        class AuditedFaithfulness(Faithfulness):
            async def _create_verdicts(self, row, statements, callbacks):
                result = await super()._create_verdicts(row, statements, callbacks)
                verdicts.extend(result.statements)
                return result

        metric = AuditedFaithfulness(llm=LangchainLLMWrapper(get_llm()))
        score = _score(metric.single_turn_ascore(sample))
        return {"score": score,
                "unsupported_claims": [{"statement": v.statement, "reason": v.reason}
                                       for v in verdicts if not v.verdict],
                "reasoning": "RAGAS faithfulness to requester claims, recorded facts and configured policy; "
                             + ("independent execution evidence" if workflow_record is not None else
                                "supplied structured evidence only (reference-runner compatibility)")}
    return hallucination


def create_audit_trail_evaluator():
    """
    Create an evaluator that validates the completeness of the audit trail.

    TODO (4 points):
    - Return a callable with signature:
        def evaluator(inputs, outputs, reference_outputs) -> dict
    - Only the human review nodes (manager_review, finance_review, final_signoff)
      append to state["decisions"] (see the manager_review hints in nodes.py), so
      count human review stages only. Expected count = len(reference_outputs["decisions"])
      if present, otherwise the number of HUMAN_REVIEW_STAGES in
      reference_outputs["approval_path"] (the eval dataset has no "decisions" key;
      run_three_layer_eval builds one entry per human review stage)
    - Check the following in outputs["decisions"]:
      1. decisions is non-empty when the expected count is above 0 (an empty list is
         correct when it is 0: auto-approved, or rejected at submit_request)
      2. Each decision entry has required keys: "stage", "decision", "reasoning"
      3. Number of decision entries equals the expected count
    - Scoring:
        - Score = fraction of checks that pass (3 checks total)
        - All pass → 1.0, two pass → 0.67, one passes → 0.33, none → 0.0
    - Return {"score": float, "reasoning": str}

    Example:
        outputs = {
            "decisions": [
                {"stage": "manager_review", "decision": "approved", "reasoning": "..."},
                {"stage": "finance_review", "decision": "approved", "reasoning": "..."},
            ]
        }
        reference_outputs = {"approval_path": ["submit_request", "assess_risk",
            "manager_review", "finance_review", "process_request"]}
        → expected count 2: non-empty (pass), keys present (pass), count matches (pass) → 1.0
        An auto-approved request (no review stage in the path) with decisions [] → 1.0

    Returns:
        A callable evaluator function
    """
    def audit_trail(inputs, outputs, reference_outputs):
        expected = (len(reference_outputs["decisions"]) if "decisions" in reference_outputs else
                    sum(s in HUMAN_REVIEW_STAGES for s in reference_outputs.get("approval_path", [])))
        decisions = outputs.get("decisions", [])
        if not isinstance(decisions, list):
            return {"score": 0.0, "reasoning": "Decisions must be a list"}
        checks = [bool(decisions) if expected else not decisions,
                  all(isinstance(d, dict) and {"stage", "decision", "reasoning"} <= d.keys() for d in decisions),
                  len(decisions) == expected]
        return {"score": sum(checks) / 3, "reasoning": f"{sum(checks)}/3 audit trail checks passed"}
    return audit_trail
