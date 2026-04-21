from __future__ import annotations


def summarize_metrics(metrics: list[dict]) -> dict:
    if not metrics:
        return {
            "highest_latency_service": "unknown",
            "max_latency_ms": 0,
            "baseline_latency_ms": 0,
            "latency_summary": "No latency metrics available yet.",
            "healthy_reference_service": "unknown",
        }

    highest = max(metrics, key=lambda item: item["current_p95_ms"])
    baseline = min(metrics, key=lambda item: item["baseline_p95_ms"])

    return {
        "highest_latency_service": highest["service"],
        "max_latency_ms": highest["current_p95_ms"],
        "baseline_latency_ms": highest["baseline_p95_ms"],
        "latency_summary": (
            f"{highest['service']} p95 latency rose from {highest['baseline_p95_ms']} ms "
            f"to {highest['current_p95_ms']} ms while error rate reached {highest['error_rate_pct']}%."
        ),
        "healthy_reference_service": baseline["service"],
    }
