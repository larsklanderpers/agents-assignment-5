"""Evaluate actual graph executions; human approvals are simulated for repeatability.

Run: python -m backend.evaluation.run_graph_eval [--three-layer] [--limit 2]
Unlike the supplied reference-only runners, this invokes the configured live LLM.
"""
import argparse
import json
from uuid import uuid4
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from backend.agent.graph import create_approval_graph
from backend.evaluation.dataset import EVAL_DATASET
from backend.evaluation.evaluators import create_risk_accuracy_evaluator, create_approval_consistency_evaluator
from backend.evaluation.run_three_layer_eval import EVALUATOR_REGISTRY


def execute_case(graph, inputs):
    config = {"configurable": {"thread_id": str(uuid4())}}
    command, path = {**inputs, "messages": []}, []
    for _ in range(5):
        paused = False
        for update in graph.stream(command, config, stream_mode="updates"):
            if "__interrupt__" in update:
                paused = True
            else:
                path.extend(update)
        if not paused:
            state = graph.get_state(config).values
            return {"status": state["status"], "risk_level": state["risk_level"],
                    "approval_path": path, "human_reviews": len(state["decisions"]),
                    "decisions": state["decisions"]}
        # This is an evaluation harness, never a substitute for live human review.
        command = Command(resume={"approved": True, "comments": "Simulated approval in evaluation"})
    raise RuntimeError("Workflow exceeded the expected number of human reviews")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=len(EVAL_DATASET))
    parser.add_argument("--three-layer", action="store_true", help="Include LLM-judged RAGAS metrics")
    args = parser.parse_args()
    if args.limit <= 0:
        parser.error("--limit must be positive")
    evaluators = {"risk_accuracy": create_risk_accuracy_evaluator(),
                  "approval_consistency": create_approval_consistency_evaluator()}
    for name, (factory, _, _) in EVALUATOR_REGISTRY.items():
        if args.three_layer or name not in {"agent_goal_accuracy", "topic_adherence", "hallucination"}:
            evaluators[name] = factory()
    graph = create_approval_graph(MemorySaver())
    scores = {name: [] for name in evaluators}
    print("Actual graph evaluation with live risk model; human reviews are simulated.")
    for case in EVAL_DATASET[:args.limit]:
        outputs = execute_case(graph, case["input"])
        result = {name: evaluator(case["input"], outputs, case["expected"])["score"]
                  for name, evaluator in evaluators.items()}
        for name, score in result.items():
            scores[name].append(score)
        print(json.dumps({"request_id": case["input"]["request_id"], "outputs": outputs, "scores": result}))
    print(json.dumps({"averages": {name: sum(values) / len(values) for name, values in scores.items()}}, indent=2))


if __name__ == "__main__":
    main()
