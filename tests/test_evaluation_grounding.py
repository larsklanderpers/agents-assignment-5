"""Guard the boundary between candidate explanations and execution evidence."""
import json
from copy import deepcopy
from unittest.mock import Mock

from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver

from backend.agent.graph import create_approval_graph
from backend.evaluation.dataset import EVAL_DATASET
from backend.evaluation.evidence import workflow_record
from backend.evaluation.run_graph_eval import execute_case
from backend.evaluation.three_layer_evaluators import create_hallucination_evaluator


def test_live_runner_keeps_explanation_and_independent_factual_record(monkeypatch):
    model = Mock()
    model.invoke.return_value = AIMessage(content=json.dumps({
        "risk_level": "medium", "risk_reasoning": "UNVERIFIED_EXPLANATION"}))
    monkeypatch.setattr("backend.agent.nodes.get_llm", lambda: model)
    answer, record = execute_case(create_approval_graph(MemorySaver()), EVAL_DATASET[1]["input"],
                                  include_record=True)
    assert answer["risk_reasoning"] == "UNVERIFIED_EXPLANATION"
    assert record["department_budget"] == 50000
    assert record["within_budget"] is True
    assert record["validation_message"] == "Request validated successfully"
    assert record["risk_reasoning_provided"] is True
    assert "UNVERIFIED_EXPLANATION" not in json.dumps(record)
    assert record["review_submissions"][0]["comments"] == "Simulated approval in evaluation"
    assert {"reviewer", "timestamp", "stage", "approved", "decision"} <= record["decisions"][0].keys()
    answer["decisions"][0]["reviewer"] = "Invented Executive"
    answer["decisions"][0]["comments"] = "Fabricated review comment"
    assert record["decisions"][0]["reviewer"] == "Manager"
    assert "Fabricated review comment" not in json.dumps(record)


def test_judge_receives_independent_evidence_without_candidate_claims(monkeypatch):
    import ragas.metrics
    import ragas.llms
    captured = []

    class Judge:
        def __init__(self, **kwargs):
            pass

        async def single_turn_ascore(self, sample):
            captured.append(sample)
            return 1.0

    monkeypatch.setattr(ragas.metrics, "Faithfulness", Judge)
    monkeypatch.setattr(ragas.llms, "LangchainLLMWrapper", lambda model: model)
    monkeypatch.setattr("backend.evaluation.three_layer_evaluators.get_llm", lambda: object())
    original = {"status": "approved", "risk_level": "medium", "department_budget": 50000,
                "decisions": [{"stage": "manager_review", "decision": "approved",
                               "reviewer": "Manager", "timestamp": "2026-10-30T00:00:00Z",
                               "comments": "UNSUPPORTED_COMMENT", "reasoning": "UNSUPPORTED_REASON"}]}
    record = workflow_record(original, ["submit_request", "manager_review", "process_request"])
    candidate = deepcopy(original)
    candidate.update(department_budget=999999, risk_reasoning="INVENTED_POLICY_FIN_999")
    candidate["decisions"][0]["reviewer"] = "FABRICATED_EXECUTIVE"
    create_hallucination_evaluator()(EVAL_DATASET[1]["input"], candidate, {}, workflow_record=record)
    sample = captured[0]
    context = " ".join(sample.retrieved_contexts)
    for unsupported in ("INVENTED_POLICY_FIN_999", "FABRICATED_EXECUTIVE", "999999",
                        "UNSUPPORTED_COMMENT", "UNSUPPORTED_REASON"):
        assert unsupported in sample.response
        assert unsupported not in context
    assert '"reviewer": "Manager"' in context
    assert "2026-10-30T00:00:00Z" in context
    assert '"department_budget": 50000' in context
    assert "not verified facts" in context
    assert "Authoritative configured policy" in context


def test_faithfulness_wording_preserves_claims_and_distinguishes_reference_values():
    from backend.evaluation.three_layer_evaluators import _faithfulness_answer
    answer = _faithfulness_answer({"human_reviews": 0, "budget_remaining": 27000,
                                  "risk_reasoning": "INVENTED_POLICY", "unexpected_claim": "FAKE_REVIEW"})
    assert "number_of_human_reviews_performed" in answer
    assert "configured_reference_balance_if_approved_not_live_balance" in answer
    assert "27000" in answer
    assert "INVENTED_POLICY" in answer and "FAKE_REVIEW" in answer
    assert '"risk_reasoning"' not in answer


def test_reference_runner_three_argument_api_stays_supported(monkeypatch):
    import ragas.metrics
    import ragas.llms
    samples = []

    class Judge:
        def __init__(self, **kwargs):
            pass

        async def single_turn_ascore(self, sample):
            samples.append(sample)
            return 1.0

    monkeypatch.setattr(ragas.metrics, "Faithfulness", Judge)
    monkeypatch.setattr(ragas.llms, "LangchainLLMWrapper", lambda model: model)
    monkeypatch.setattr("backend.evaluation.three_layer_evaluators.get_llm", lambda: object())
    expected = EVAL_DATASET[0]["expected"]
    result = create_hallucination_evaluator()(EVAL_DATASET[0]["input"], expected, expected)
    assert result["score"] == 1.0
    assert "supplied structured evidence only" in result["reasoning"]
    assert samples
