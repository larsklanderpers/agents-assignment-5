"""Execute the real graph with a deterministic model double; no API keys needed."""
import json
from copy import deepcopy
from unittest.mock import Mock

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command
from backend.agent.graph import create_approval_graph
from backend.agent.nodes import assess_risk
from backend.evaluation.dataset import EVAL_DATASET
from backend.guardrails.input_validator import validate_amount, validate_request
from backend.guardrails.output_filter import sanitize_output, mask_financial_details
from backend.evaluation.dataset_generator import generate_eval_dataset, generate_edge_cases, validate_generated_dataset, upload_to_langsmith


@pytest.fixture
def model(monkeypatch):
    def invoke(messages):
        request = json.loads(messages[0].content.split("Request:\n")[1])
        amount = request["amount"]
        risk = ("critical" if amount > 50000 and request["priority"] == "urgent" else
                "high" if amount > 50000 else "medium" if amount > 10000 else "low")
        return AIMessage(content=json.dumps({"risk_level": risk, "risk_reasoning": "Applied amount and priority rules"}))
    llm = Mock()
    llm.invoke.side_effect = invoke
    monkeypatch.setattr("backend.agent.nodes.get_llm", lambda: llm)
    return llm


def run_request(graph, inputs, thread="test", reject=None):
    config = {"configurable": {"thread_id": thread}}
    path, interrupts = [], []
    command = {**inputs, "messages": []}
    while True:
        paused = None
        for update in graph.stream(command, config, stream_mode="updates"):
            if "__interrupt__" in update:
                paused = update["__interrupt__"][0].value
                interrupts.append(paused["type"])
            else:
                path.extend(update.keys())
        if paused is None:
            return graph.get_state(config).values, path, interrupts
        command = Command(resume=json.dumps({"approved": paused["type"] != reject, "comments": "Reviewed"}))


@pytest.mark.parametrize("case", EVAL_DATASET, ids=lambda c: c["input"]["request_id"])
def test_dataset_runs_through_real_graph(model, case):
    result, path, interrupts = run_request(create_approval_graph(MemorySaver()), case["input"])
    expected = case["expected"]
    assert result["status"] == expected["status"]
    assert result["risk_level"] == expected["risk_level"]
    assert path == expected["approval_path"]
    assert len(interrupts) == expected["human_reviews"]
    assert len(result["decisions"]) == len(interrupts)


@pytest.mark.parametrize("stage", ["manager_review", "finance_review", "final_signoff"])
def test_rejection_stops_at_each_review(model, stage):
    request = {**EVAL_DATASET[0]["input"], "amount": 95000, "priority": "urgent"}
    result, path, interrupts = run_request(create_approval_graph(MemorySaver()), request, reject=stage)
    assert result["status"] == "rejected"
    assert interrupts[-1] == stage
    assert path[-1] == "handle_rejection"
    assert result["decisions"][-1]["decision"] == "rejected"


def test_same_thread_resets_previous_approval(model):
    graph = create_approval_graph(MemorySaver())
    request = {**EVAL_DATASET[0]["input"], "amount": 95000, "priority": "urgent"}
    first, _, _ = run_request(graph, request)
    assert len(first["decisions"]) == 3
    second, _, _ = run_request(graph, {**request, "amount": -1})
    assert second["risk_level"] is None
    assert second["decisions"] == []
    assert second["manager_approved"] is None
    assert second["department_budget"] is None


def test_sqlite_pause_survives_reopen(model, tmp_path):
    database = str(tmp_path / "checkpoint.db")
    config = {"configurable": {"thread_id": "restart"}}
    request = {**EVAL_DATASET[0]["input"], "amount": 15000}
    with SqliteSaver.from_conn_string(database) as saver:
        graph = create_approval_graph(saver)
        assert "__interrupt__" in graph.invoke({**request, "messages": []}, config)
    with SqliteSaver.from_conn_string(database) as saver:
        result = create_approval_graph(saver).invoke(Command(resume={"approved": True, "comments": "OK"}), config)
        assert result["status"] == "approved"
        assert len(result["decisions"]) == 1


@pytest.mark.asyncio
async def test_async_checkpoint_resume(model, tmp_path):
    config = {"configurable": {"thread_id": "async"}}
    request = {**EVAL_DATASET[0]["input"], "amount": 95000, "priority": "urgent", "messages": []}
    async with AsyncSqliteSaver.from_conn_string(str(tmp_path / "async.db")) as saver:
        graph = create_approval_graph(saver)
        result = await graph.ainvoke(request, config)
        for stage in ("manager_review", "finance_review", "final_signoff"):
            assert result["__interrupt__"][0].value["type"] == stage
            result = await graph.ainvoke(Command(resume={"approved": True, "comments": "OK"}), config)
        assert result["status"] == "approved"
        assert len(result["decisions"]) == 3


def test_invalid_resume_cannot_approve(model):
    config = {"configurable": {"thread_id": "invalid-resume"}}
    graph = create_approval_graph(MemorySaver())
    graph.invoke({**EVAL_DATASET[0]["input"], "amount": 15000, "messages": []}, config)
    with pytest.raises(ValueError, match="boolean"):
        graph.invoke(Command(resume={"approved": "false", "comments": "Invalid type"}), config)
    assert graph.get_state(config).values["status"] != "approved"


@pytest.mark.parametrize("amount", [float("nan"), float("inf"), True, "500", None, 0])
def test_invalid_amounts(amount):
    assert not validate_amount(amount)[0]


def test_validation_blocks_obfuscated_script_and_long_fields():
    assert not validate_request(100, "engineering", "Test", "<script src='x'>", "ok")[0]
    assert not validate_request(100, "engineering", "Test", "ok", "a" * 2001)[0]


@pytest.mark.parametrize("generate", [generate_eval_dataset, generate_edge_cases])
def test_generator_parses_fenced_content_blocks(generate):
    llm = Mock()
    llm.invoke.return_value = AIMessage(content=[{"type": "text", "text": "```json\n" + json.dumps(EVAL_DATASET[:1]) + "\n```"}])
    assert generate(1, llm) == EVAL_DATASET[:1]


def test_generator_rejects_malformed_dataset():
    for dataset in [None, {}, [None], [{"input": [], "expected": {}}]]:
        assert not validate_generated_dataset(dataset)[0]
    dataset = deepcopy(EVAL_DATASET[:1])
    dataset[0]["input"]["amount"] = True
    assert not validate_generated_dataset(dataset)[0]


def test_generator_retries_incorrect_policy_labels():
    good = deepcopy(EVAL_DATASET[-1:])
    bad = deepcopy(good)
    bad[0]["expected"]["approval_path"].remove("finance_review")
    bad[0]["expected"]["human_reviews"] = 1
    llm = Mock()
    llm.invoke.side_effect = [AIMessage(content=json.dumps(bad)), AIMessage(content=json.dumps(good))]
    assert generate_edge_cases(1, llm) == good
    assert llm.invoke.call_count == 2


def test_generator_never_returns_uncorrected_policy_labels():
    bad = deepcopy(EVAL_DATASET[-1:])
    bad[0]["expected"]["risk_level"] = "low"
    llm = Mock()
    llm.invoke.return_value = AIMessage(content=json.dumps(bad))
    with pytest.raises(ValueError, match="after 3 attempts"):
        generate_eval_dataset(1, llm)
    assert llm.invoke.call_count == 3


def test_dataset_upload_uses_expected_schema(monkeypatch):
    client = Mock()
    client.create_dataset.return_value.id = "dataset-id"
    monkeypatch.setattr("langsmith.Client", lambda: client)
    assert upload_to_langsmith(EVAL_DATASET[:1], "test-dataset") == "dataset-id"
    client.create_example.assert_called_once_with(inputs=EVAL_DATASET[0]["input"],
        outputs=EVAL_DATASET[0]["expected"], dataset_id="dataset-id")


@pytest.mark.parametrize("reply, expected", [("low", "low"), ("```", "medium"),
    ('```json\n{"risk_level":"critical","risk_reasoning":"urgent"}\n```', "critical"),
    ('{"risk_level":"unknown"}', "medium")])
def test_risk_response_parsing(monkeypatch, reply, expected):
    llm = Mock()
    llm.invoke.return_value = AIMessage(content=[{"type": "text", "text": reply}])
    monkeypatch.setattr("backend.agent.nodes.get_llm", lambda: llm)
    assert assess_risk(EVAL_DATASET[0]["input"])["risk_level"] == expected


def test_output_redaction_covers_combined_sensitive_data():
    text = "SSN 123-45-6789 card 4111-1111-1111-1111 email alice@example.com phone 555-123-4567 account 123456789012 amount $45,000.00"
    result = sanitize_output(text)
    for sensitive in ("123-45-6789", "4111-1111-1111-1111", "alice@example.com", "555-123-4567", "123456789012", "$45,000.00"):
        assert sensitive not in result
    assert sanitize_output(result) == result


@pytest.mark.parametrize("original, masked", [
    ("$45,678.91", "$***8.91"),
    ("$45678", "$***678"),
    ("$12.34", "$***2.34"),
    ("$123.4", "$***23.4"),
    ("$12", "$***12"),
    ("Amount $45,678.91.", "Amount $***8.91."),
    ("Amount $45678.", "Amount $***678."),
])
def test_financial_mask_retains_numeric_digits(original, masked):
    assert mask_financial_details(original) == masked
    assert mask_financial_details(masked) == masked
