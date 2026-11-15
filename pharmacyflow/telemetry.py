import json
import logging
import hashlib
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from .config import settings
from .models import Event

tracer = trace.get_tracer("pharmacyflow")
log = logging.getLogger("pharmacyflow")
SAFE_KEYS = {
    "from",
    "to",
    "reason",
    "agent",
    "action_hash",
    "request_id",
    "status",
    "count",
    "policy_ids",
    "version",
    "tool",
    "attempt",
    "error_type",
    "tokens_in",
    "tokens_out",
    "estimated_cost_usd",
    "mode",
    "field",
    "match_count",
    "duplicate_prevented",
    "rubric",
    "provider",
    "model",
}
_configured = False


class LocalExporter(SpanExporter):
    def export(self, spans):
        folder = settings().data_dir
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "traces.jsonl").open("a", encoding="utf8") as out:
            for span in spans:
                out.write(
                    json.dumps(
                        {
                            "trace_id": format(span.context.trace_id, "032x"),
                            "span_id": format(span.context.span_id, "016x"),
                            "name": span.name,
                            "start_ns": span.start_time,
                            "end_ns": span.end_time,
                            "attributes": dict(span.attributes),
                        }
                    )
                    + "\n"
                )
        return SpanExportResult.SUCCESS


def configure():
    global _configured
    if _configured:
        return
    provider = TracerProvider(resource=Resource.create({"service.name": "pharmacyflow"}))
    provider.add_span_processor(SimpleSpanProcessor(LocalExporter()))
    if settings().otel_exporter_otlp_endpoint:
        provider.add_span_processor(
            BatchSpanProcessor(
                OTLPSpanExporter(endpoint=settings().otel_exporter_otlp_endpoint.rstrip("/") + "/v1/traces")
            )
        )
    trace.set_tracer_provider(provider)
    _configured = True


def audit(db, case, actor, category, name, evidence=None, duration_ms=0):
    # Never emit documents, names, DOBs, transcript, credentials, or raw tool responses.
    safe = {k: v for k, v in (evidence or {}).items() if k in SAFE_KEYS}
    safe.setdefault("mode", settings().provider_mode)
    # Signed case context travels API -> queue -> MCP -> browser. Derive a common
    # trace parent from that non-sensitive ID so restarts retain one trace per case.
    from opentelemetry.trace import SpanContext, NonRecordingSpan, TraceFlags

    digest = hashlib.sha256(case.id.encode()).digest()
    parent = SpanContext(
        int.from_bytes(digest[:16], "big"), int.from_bytes(digest[16:24], "big"), True, TraceFlags(1)
    )
    with tracer.start_as_current_span(
        name,
        context=trace.set_span_in_context(NonRecordingSpan(parent)),
        attributes={
            "case.id": case.id,
            "tenant.id": case.tenant,
            "event.category": category,
            "provider.mode": settings().provider_mode,
        },
    ):
        context = trace.get_current_span().get_span_context()
        trace_id = format(context.trace_id, "032x") if context.is_valid else ""
        db.add(
            Event(
                case_id=case.id,
                tenant=case.tenant,
                actor=actor,
                category=category,
                name=name,
                evidence=safe,
                trace_id=trace_id,
                duration_ms=duration_ms,
            )
        )
        log.info(
            json.dumps({"case_id": case.id, "actor": actor, "event": name, "trace_id": trace_id, **safe})
        )
