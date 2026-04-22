from __future__ import annotations

from collections import defaultdict

from incident_investigator.tools.event_processing import (
    calculate_incident_severity,
    derive_log_records,
    derive_service_metrics,
    derive_user_journeys,
    summarize_request_paths,
)


def reduce_observability(
    raw_events: list[dict],
    filters: dict,
    baseline_events: list[dict] | None = None,
) -> dict:
    baseline_events = baseline_events or []
    metrics = derive_service_metrics(raw_events, baseline_events)
    logs = derive_log_records(raw_events, baseline_events)
    user_events = derive_user_journeys(raw_events, baseline_events)
    traces = derive_traces(raw_events, filters)
    request_path_summary = summarize_request_paths(raw_events)
    severity_summary = calculate_incident_severity(metrics, user_events, logs)

    return {
        "logs": logs,
        "metrics": metrics,
        "traces": traces,
        "user_events": user_events,
        "request_path_summary": request_path_summary,
        "severity_summary": severity_summary,
        "reduction_summary": {
            "raw_event_count": len(raw_events),
            "baseline_event_count": len(baseline_events),
            "service_count": len(metrics),
            "entrypoints": request_path_summary["top_entry_points"],
        },
        "incident_score": severity_summary["incident_score"],
        "incident_severity": severity_summary["severity"],
        "severity_hint": severity_summary["severity"],
    }


def derive_traces(raw_events: list[dict], filters: dict) -> list[dict]:
    by_trace: dict[str, list[dict]] = defaultdict(list)
    for event in raw_events:
        if event.get("event_type") != "service_request":
            continue
        trace_id = event.get("trace_id")
        if trace_id:
            by_trace[trace_id].append(event)

    traces = []
    for trace_id, events in sorted(
        by_trace.items(),
        key=lambda item: min(event["timestamp"] for event in item[1]),
    ):
        ordered = sorted(events, key=lambda item: item["timestamp"])
        traces.append(
            {
                "timestamp": ordered[0]["timestamp"],
                "trace_id": trace_id,
                "window": _format_window_label(filters.get("start"), filters.get("end")),
                "duration_ms": sum(event.get("latency_ms", 0) for event in ordered),
                "entrypoint": ordered[0].get("entrypoint"),
                "spans": [
                    {
                        "service": event["service"],
                        "name": event["operation"],
                        "duration_ms": event.get("latency_ms", 0),
                        "status_code": event.get("status_code"),
                    }
                    for event in ordered
                ],
            }
        )
    return traces


def _format_window_label(start: str | None, end: str | None) -> str:
    if not start or not end:
        return "unknown"
    return f"{start[11:16]}-{end[11:16]} UTC"
