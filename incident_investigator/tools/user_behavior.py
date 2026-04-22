from __future__ import annotations


def summarize_user_behavior(user_events: list[dict]) -> dict:
    if not user_events:
        return {
            "most_impacted_flow": "unknown",
            "dropoff_rate_delta": 0.0,
            "affected_sessions": 0,
            "top_exit_step": "unknown",
            "dropoff_summary": "No user impact is visible yet.",
        }

    most_impacted = max(user_events, key=lambda item: item["dropoff_rate_delta"])
    return {
        "most_impacted_flow": most_impacted["flow"],
        "dropoff_rate_delta": most_impacted["dropoff_rate_delta"],
        "affected_sessions": most_impacted.get("started_sessions", 0),
        "top_exit_step": most_impacted.get("top_exit_step", "unknown"),
        "dropoff_summary": (
            f"{most_impacted['flow']} conversion fell from "
            f"{round(most_impacted['baseline_conversion_rate'] * 100, 1)}% to "
            f"{round(most_impacted['current_conversion_rate'] * 100, 1)}%, "
            f"most often exiting at {most_impacted.get('top_exit_step', 'unknown')}."
        ),
    }
