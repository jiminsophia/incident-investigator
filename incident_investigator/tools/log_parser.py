from __future__ import annotations

from collections import Counter


def summarize_logs(logs: list[dict]) -> dict:
    if not logs:
        return {
            "error_count": 0,
            "warning_count": 0,
            "top_error_component": "none yet",
            "top_failing_entry_point": "none yet",
            "error_summary": "No significant errors observed yet.",
        }

    levels = Counter(log["level"] for log in logs)
    error_components = Counter(log["component"] for log in logs if log["level"] == "ERROR")
    error_entry_points = Counter(
        log.get("entry_point", "unknown")
        for log in logs
        if log["level"] == "ERROR"
    )
    common_messages = Counter(log["message"] for log in logs if log["level"] == "ERROR")
    top_component = error_components.most_common(1)[0][0] if error_components else "unknown"
    top_entry_point = error_entry_points.most_common(1)[0][0] if error_entry_points else "unknown"
    top_message = common_messages.most_common(1)[0][0] if common_messages else "unknown"

    return {
        "error_count": levels.get("ERROR", 0),
        "warning_count": levels.get("WARN", 0),
        "top_error_component": top_component,
        "top_failing_entry_point": top_entry_point,
        "error_summary": (
            f"Most errors came from {top_component} on {top_entry_point}; top message was '{top_message}'."
        ),
    }
