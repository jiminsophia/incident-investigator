from __future__ import annotations


def summarize_metrics(metrics: list[dict]) -> dict:
    if not metrics:
        return {
            "highest_latency_service": "unknown",
            "max_latency_ms": 0,
            "baseline_latency_ms": 0,
            "latency_ratio": 0.0,
            "max_error_rate_pct": 0.0,
            "highest_error_service": "unknown",
            "degraded_services": [],
            "latency_summary": "No latency metrics available yet.",
            "healthy_reference_service": "unknown",
        }

    highest = max(metrics, key=lambda item: item["current_p95_ms"])
    baseline = min(metrics, key=lambda item: item["baseline_p95_ms"])
    error_hotspot = max(metrics, key=lambda item: item.get("error_rate_pct", 0.0))
    latency_ratio = round(
        highest["current_p95_ms"] / highest["baseline_p95_ms"],
        2,
    ) if highest["baseline_p95_ms"] else 0.0

    return {
        "highest_latency_service": highest["service"],
        "max_latency_ms": highest["current_p95_ms"],
        "baseline_latency_ms": highest["baseline_p95_ms"],
        "latency_ratio": latency_ratio,
        "max_error_rate_pct": error_hotspot.get("error_rate_pct", 0.0),
        "highest_error_service": error_hotspot["service"],
        "degraded_services": [
            item["service"]
            for item in metrics
            if item["latency_ratio"] >= 1.8 or item["error_rate_pct"] >= 2.0
        ],
        "latency_summary": (
            f"{highest['service']} p95 latency rose from {highest['baseline_p95_ms']} ms "
            f"to {highest['current_p95_ms']} ms ({latency_ratio}x baseline) while error rate reached "
            f"{highest['error_rate_pct']}%."
        ),
        "healthy_reference_service": baseline["service"],
    }
