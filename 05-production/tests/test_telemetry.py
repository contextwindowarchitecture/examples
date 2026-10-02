"""Every run is traced with OpenTelemetry: one span per run, assembly, model call and tool call, carrying what CWA
decided and what the guard decided, and pointing at the snapshot store instead of copying what users wrote."""
from __future__ import annotations

import json
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from conftest import RESULTS, replay

EXPORTER = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(EXPORTER))
trace.set_tracer_provider(_provider)


@pytest.fixture
def spans() -> list[ReadableSpan]:
    EXPORTER.clear()
    replay(RESULTS[0] / "owner-reenables")
    return list(EXPORTER.get_finished_spans())


def named(spans: list[ReadableSpan], prefix: str) -> list[ReadableSpan]:
    return [span for span in spans if span.name.startswith(prefix)]


def test_one_span_per_run_assembly_model_call_and_tool_call(spans: list[ReadableSpan]) -> None:
    recorded = json.loads((RESULTS[0] / "owner-reenables" / "run.json").read_text(encoding="utf-8"))
    turns = len(list((RESULTS[0] / "owner-reenables").glob("turn-*")))
    assert len(named(spans, "agent.run")) == 1
    assert len(named(spans, "cwa.assemble")) == turns
    assert len(named(spans, "chat ")) == turns
    assert len(named(spans, "tool ")) == len(recorded["steps"])
    [run] = named(spans, "agent.run")
    assert all(span.parent is not None and span.parent.span_id == run.context.span_id
               for span in named(spans, "cwa.assemble") + named(spans, "chat ") + named(spans, "tool "))


def test_an_assembly_span_carries_cwas_decisions(spans: list[ReadableSpan]) -> None:
    first: dict[str, Any] = dict(named(spans, "cwa.assemble")[0].attributes or {})
    trace_json = json.loads((RESULTS[0] / "owner-reenables" / "turn-1" / "trace.json").read_text(encoding="utf-8"))
    assert first["cwa.snapshot.digest"] == trace_json["context"]["snapshot_digest"]
    assert first["cwa.payload.sha256"] == trace_json["result"]["hash"]
    assert first["cwa.profile"] == "account-agent-messages v2"
    assert "cap:delete_webhook: capability_not_allowed" in first["cwa.excluded"]


def test_a_tool_span_carries_the_guards_decision(spans: list[ReadableSpan]) -> None:
    for span in named(spans, "tool "):
        attributes = dict(span.attributes or {})
        assert attributes["cwa.guard.approved"] is True and attributes["cwa.guard.reason"]


def test_no_span_carries_the_users_question(spans: list[ReadableSpan]) -> None:
    question = json.loads((RESULTS[0] / "owner-reenables" / "scenario.json").read_text(encoding="utf-8"))["question"]
    for span in spans:
        assert not any(question in str(value) for value in (span.attributes or {}).values())
