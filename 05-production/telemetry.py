"""Every agent run as OpenTelemetry spans: one per run, one per assembly, one per model call, one per tool call.

The spans carry what CWA decided, not what users wrote: each assembly's profile, route policy, snapshot digest,
payload hash and token count, every item it sent, summarized or left out and why, the conflict groups, and the
guard's decision on each tool call. The snapshot digest is the link to the snapshot store, which holds the content
under its own access rules, so user data is not copied into the tracing backend.

Spans go wherever the standard OpenTelemetry environment sends them:

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318         # any OTLP/HTTP backend: Jaeger, Grafana Tempo, Honeycomb
    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:3000/api/public/otel \\
    OTEL_EXPORTER_OTLP_HEADERS="Authorization=Basic <base64 of public-key:secret-key>"   # Langfuse
    DOCS_QA_TRACE_CONSOLE=1                                   # print each span as JSON

With neither set, spans are created and dropped.
"""
from __future__ import annotations

import os
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SimpleSpanProcessor

TRACER = trace.get_tracer("cwa-examples.agent")


def configure() -> TracerProvider:
    provider = TracerProvider(resource=Resource.create({"service.name": "fernway-help-agent"}))
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    if os.environ.get("DOCS_QA_TRACE_CONSOLE"):
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    return provider


def assembly(cwa_trace: dict[str, Any]) -> dict[str, Any]:
    """A CWA trace as span attributes."""
    result = cwa_trace["result"] or {}
    compressed = {row["item_id"] for row in cwa_trace["compressed"]}
    return {
        "cwa.profile": f"{cwa_trace['profile']['id']} v{cwa_trace['profile']['version']}",
        "cwa.route_policy": cwa_trace["context"]["route_policy_version"],
        "cwa.snapshot.digest": cwa_trace["context"]["snapshot_digest"],
        "cwa.payload.sha256": result.get("hash", ""),
        "cwa.input_tokens": result.get("input_tokens", 0),
        "cwa.budget.input": cwa_trace["budget"]["input"],
        "cwa.refused": cwa_trace["refused"]["reason"] or "",
        "cwa.included": [row["item_id"] for row in cwa_trace["included"] if row["item_id"] not in compressed],
        "cwa.compressed": sorted(compressed),
        "cwa.excluded": [f"{row['item_id']}: {row['reason']}" for row in cwa_trace["excluded"]],
        "cwa.conflicts": [f"{group['group_id']}: {group['decided_by']}" + (f", {group['winner']}" if group.get("winner") else "")
                          for group in cwa_trace["conflicts"]],
    }
