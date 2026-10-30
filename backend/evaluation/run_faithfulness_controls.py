"""Live positive/negative controls for the faithfulness judge; never uploads data.

Run: python -m backend.evaluation.run_faithfulness_controls
Controls use independent evidence from an actual graph execution. Thresholds
are explicit diagnostic expectations for these focused examples, not grades.
"""
import json
from copy import deepcopy
from langgraph.checkpoint.memory import MemorySaver
from backend.agent.graph import create_approval_graph
from backend.evaluation.dataset import EVAL_DATASET
from backend.evaluation.run_graph_eval import execute_case
from backend.evaluation.three_layer_evaluators import create_hallucination_evaluator


def control_cases(record):
    decision = deepcopy(record["decisions"][0])
    fabricated = {**decision, "stage": "final_signoff", "reviewer": "Executive"}
    return [
        ("configured_policy", {"risk_reasoning": "An amount above 10000 and up to 50000 is medium risk."},
         {"risk_reasoning": "Policy FIN-999 awards this purchase a mandatory 17 percent government rebate."}, "focused"),
        ("department_budget", {"department_budget": record["department_budget"]},
         {"department_budget": 999999}, "focused"),
        ("approval_history", {"approval_history": "The Manager approved this request at manager_review."},
         {"approval_history": "The Executive approved this request at final_signoff."}, "focused"),
        # This record retains genuine timestamps and decision values. A fractional
        # score can remain high despite catching the fabricated reviewer/stage;
        # require explicit detection of the injected claim, not an arbitrary 0.5.
        ("mixed_approval_record", {"decisions": [decision]}, {"decisions": [fabricated]}, "mixed"),
    ]


def main():
    case = EVAL_DATASET[1]
    _, record = execute_case(create_approval_graph(MemorySaver()), case["input"], include_record=True)
    judge = create_hallucination_evaluator()
    results = []
    for name, correct, fabricated, kind in control_cases(record):
        positive = judge(case["input"], correct, case["expected"], workflow_record=record)
        negative = judge(case["input"], fabricated, case["expected"], workflow_record=record)
        good, bad = positive["score"], negative["score"]
        flagged = any(any(term in claim["statement"].lower()
                          for term in ("executive", "final_signoff", "final sign-off", "final signoff"))
                      for claim in negative["unsupported_claims"])
        result = {"control": name, "correct_score": good, "fabricated_score": bad,
                  "unsupported_claims": negative["unsupported_claims"],
                  "criteria": ("correct >= 0.95; fabricated <= 0.5; correct > fabricated" if kind == "focused"
                               else "correct >= 0.95; fabricated < correct; injected reviewer/stage flagged"),
                  "passed": good >= 0.95 and good > bad and (bad <= 0.5 if kind == "focused" else flagged)}
        results.append(result)
        print(json.dumps(result), flush=True)
    print(json.dumps({"passed": all(r["passed"] for r in results)}))
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
