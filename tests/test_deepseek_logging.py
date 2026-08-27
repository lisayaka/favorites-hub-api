import json
import logging
from types import SimpleNamespace

import pytest

import app.integrations.model as model_integration
from app.integrations.model import (
    ModelInvocationError,
    StructuredAIModel,
    create_model_from_env,
)
from app.schemas.ai import Category, TaxonomyMergeOutput
from app.schemas.ai import (
    ClassificationAssignmentOutput,
    ClassificationCandidateOutput,
    ClassificationRequest,
)


class FakeChat:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error

    def with_structured_output(self, *args, **kwargs):
        return self

    def invoke(self, messages):
        if self.error:
            raise self.error
        return self.result


class RoutingChat:
    def __init__(self) -> None:
        self.schemas = []
        self.messages = []
        self.schema = None

    def with_structured_output(self, schema, **kwargs):
        self.schema = schema
        self.schemas.append(schema)
        return self

    def invoke(self, messages):
        self.messages.append(messages)
        output = (
            ClassificationCandidateOutput(
                categories=[Category(category_id="tech", name="技术", level=1)]
            )
            if self.schema is ClassificationCandidateOutput
            else ClassificationAssignmentOutput(
                assignments=[{"item_id": "item:1", "category_id": "tech"}]
            )
        )
        return {
            "parsed": output,
            "raw": SimpleNamespace(usage_metadata={}),
            "parsing_error": None,
        }


def model_with(chat: FakeChat, *, log_payloads: bool = True) -> StructuredAIModel:
    model = StructuredAIModel.__new__(StructuredAIModel)
    model.provider_name = "test-provider"
    model.model_name = "test-model"
    model.structured_method = "json_mode"
    model.log_payloads = log_payloads
    model.secrets = ("secret-value",)
    model.chat = chat
    return model


def test_model_request_and_response_logs_include_payload(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_logger = logging.getLogger("test.deepseek.success")
    monkeypatch.setattr(model_integration, "logger", test_logger)
    output = TaxonomyMergeOutput(
        categories=[Category(category_id="tech", name="技术", level=1)]
    )
    raw = SimpleNamespace(
        content='{"categories":[]}',
        response_metadata={"finish_reason": "stop"},
        usage_metadata={"input_tokens": 12, "output_tokens": 5},
    )
    model = model_with(FakeChat({"parsed": output, "raw": raw, "parsing_error": None}))

    with caplog.at_level(logging.INFO, logger=test_logger.name):
        result = model._invoke(
            TaxonomyMergeOutput,
            system="系统提示",
            payload={"candidates": [[{"name": "技术"}]], "note": "secret-value"},
        )

    records = [json.loads(record.message) for record in caplog.records]
    assert [record["event"] for record in records] == [
        "ai_model_request",
        "ai_model_response",
    ]
    assert records[0]["candidate_count"] == 1
    assert records[0]["provider"] == "test-provider"
    assert "系统提示" in records[0]["messages"][0]["content"]
    assert "secret-value" not in caplog.text
    assert records[1]["parsed_response"]["categories"][0]["category_id"] == "tech"
    assert records[1]["input_tokens"] == 12
    assert result.usage.output_tokens == 5


def test_model_error_log_contains_sanitized_cause_and_traceback(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    test_logger = logging.getLogger("test.deepseek.error")
    monkeypatch.setattr(model_integration, "logger", test_logger)
    model = model_with(FakeChat(error=TimeoutError("secret-value timed out")))

    with caplog.at_level(logging.ERROR, logger=test_logger.name):
        with pytest.raises(ModelInvocationError):
            model._invoke(TaxonomyMergeOutput, system="系统提示", payload={})

    record = json.loads(caplog.records[-1].message)
    assert record["event"] == "ai_model_error"
    assert record["error_type"] == "TimeoutError"
    assert "Traceback" in record["traceback"]
    assert "secret-value" not in caplog.text
    assert "<redacted>" in caplog.text


def test_classification_phases_use_minimal_output_schemas() -> None:
    chat = RoutingChat()
    model = model_with(chat, log_payloads=False)
    item = {
        "item_id": "item:1",
        "source": "bilibili",
        "title": "示例收藏",
        "content_type": "video",
        "evidence_level": "metadata",
    }

    candidate = model.classify(ClassificationRequest(items=[item]))
    assigned = model.classify(
        ClassificationRequest(
            phase="assign",
            taxonomy=[Category(category_id="tech", name="技术", level=1)],
            items=[item],
        )
    )

    assert chat.schemas == [
        ClassificationCandidateOutput,
        ClassificationAssignmentOutput,
    ]
    assert isinstance(candidate.output, ClassificationCandidateOutput)
    assert isinstance(assigned.output, ClassificationAssignmentOutput)
    assert "只设计候选分类目录，不对收藏逐条归类" in chat.messages[0][0][1]
    assert "只返回 assignments" in chat.messages[1][0][1]


def test_openai_factory_uses_luna_responses_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_chat_openai(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace()

    monkeypatch.setenv("AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.delenv("AI_MODEL", raising=False)
    monkeypatch.setattr(model_integration, "ChatOpenAI", fake_chat_openai)

    model = create_model_from_env()

    assert model.provider_name == "openai"
    assert model.model_name == "gpt-5.6-luna"
    assert model.structured_method == "json_schema"
    assert captured["use_responses_api"] is True
    assert captured["output_version"] == "responses/v1"
    assert captured["reasoning"] == {"effort": "low"}
    assert captured["timeout"] == 120.0
