from __future__ import annotations

from collections import Counter

from incident_investigator.tools.event_processing import parse_timestamp


def summarize_traces(traces: list[dict], start: str | None = None, end: str | None = None) -> dict:
    if not traces:
        return {
            "slow_trace_count": 0,
            "suspicious_span_names": [],
            "hot_services": [],
            "primary_window": "not enough trace data yet",
            "trace_summary": "No slow traces available yet.",
        }

    if start or end:
        traces = [
            trace
            for trace in traces
            if (start is None or parse_timestamp(trace["timestamp"]) >= parse_timestamp(start))
            and (end is None or parse_timestamp(trace["timestamp"]) <= parse_timestamp(end))
        ]

    if not traces:
        return {
            "slow_trace_count": 0,
            "suspicious_span_names": [],
            "hot_services": [],
            "primary_window": "not enough trace data yet",
            "trace_summary": "No slow traces aligned with the focused incident window yet.",
        }

    slow_traces = [trace for trace in traces if trace["duration_ms"] >= 1500]
    span_names = Counter(span["name"] for trace in slow_traces for span in trace["spans"])
    services = Counter(span["service"] for trace in slow_traces for span in trace["spans"])
    window = slow_traces[0]["window"] if slow_traces else "unknown"

    return {
        "slow_trace_count": len(slow_traces),
        "suspicious_span_names": [name for name, _ in span_names.most_common(4)],
        "hot_services": [name for name, _ in services.most_common(3)],
        "primary_window": window,
        "trace_summary": (
            f"{len(slow_traces)} slow traces were concentrated in {window}, "
            f"with hot spans around {', '.join(name for name, _ in span_names.most_common(3)) or 'none yet'}."
        ),
    }
