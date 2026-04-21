from __future__ import annotations

from pathlib import Path

import streamlit as st

from incident_investigator.orchestration.coordinator import CoordinatorAgent
from incident_investigator.tools.data_loader import build_replay_bundle, load_scenario_bundle


st.set_page_config(
    page_title="Incident Investigator",
    page_icon="🚨",
    layout="wide",
)


SCENARIOS = {
    "Checkout latency incident": "checkout_latency_incident",
    "Search relevance regression": "search_relevance_regression",
}


def render_overview() -> None:
    st.title("Incident Investigator")
    st.caption(
        "A multi-agent ops investigation MVP for logs, metrics, traces, and user signals."
    )
    st.markdown(
        """
        This demo treats incidents like an operations problem:
        anomalies are detected, evidence is gathered, hypotheses are ranked,
        and recommended actions are produced in a structured report.
        """
    )


def render_scenario_preview(bundle: dict) -> None:
    overview = bundle["metadata"]
    st.subheader("Scenario")
    st.write(overview["title"])
    st.caption(overview["summary"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Logs", len(bundle["logs"]))
    c2.metric("Metrics series", len(bundle["metrics"]))
    c3.metric("Traces", len(bundle["traces"]))
    c4.metric("User events", len(bundle["user_events"]))


def render_replay_stage(stage: dict) -> None:
    st.subheader("Live Replay Stage")
    c1, c2, c3 = st.columns(3)
    c1.metric("Elapsed", f"{stage['elapsed_sec']} sec")
    c2.metric("Phase", stage["label"])
    c3.metric("Detected severity", stage["severity_hint"])
    st.caption(stage["summary"])
    if stage.get("operator_note"):
        st.info(stage["operator_note"])


def render_agent_trace(agent_trace: list[dict]) -> None:
    st.subheader("Agent Collaboration")
    for item in agent_trace:
        with st.expander(f'{item["agent"]}: {item["summary"]}', expanded=False):
            st.markdown(item["detail"])


def render_report(report: dict) -> None:
    st.subheader("Final Incident Report")

    summary = report["anomaly_summary"]
    st.markdown(f"### {summary['headline']}")
    st.write(summary["summary"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Severity", summary["severity"])
    c2.metric("Impacted service", summary["impacted_service"])
    c3.metric("Primary window", summary["time_window"])

    st.markdown("### Root-Cause Hypotheses")
    for idx, hypothesis in enumerate(report["root_causes"], start=1):
        st.markdown(
            f"""
            **{idx}. {hypothesis['title']}**  
            Confidence: `{hypothesis['confidence']}`  
            Why: {hypothesis['rationale']}
            """
        )
        if hypothesis["evidence"]:
            st.markdown("Evidence:")
            for evidence in hypothesis["evidence"]:
                st.write(f"- {evidence}")

    st.markdown("### Recommended Actions")
    for action in report["recommended_actions"]:
        st.write(f"- {action}")

    st.markdown("### Supporting Evidence")
    for evidence in report["supporting_evidence"]:
        st.write(f"- {evidence}")

    if report["inspection_targets"]:
        st.markdown("### Code / Config To Inspect")
        for target in report["inspection_targets"]:
            st.code(target)


def main() -> None:
    render_overview()

    with st.sidebar:
        st.header("Demo Controls")
        selected_label = st.selectbox("Choose scenario", list(SCENARIOS.keys()))
        scenario_key = SCENARIOS[selected_label]
        demo_mode = st.radio(
            "View mode",
            ["Static incident report", "Replay incident over time"],
            index=1,
        )
        auto_run = st.checkbox("Run investigation immediately", value=True)
        run_clicked = st.button("Run Incident Investigation", type="primary")

    data_root = Path(__file__).parent / "incident_investigator" / "data"
    bundle = load_scenario_bundle(data_root, scenario_key)

    active_bundle = bundle
    if demo_mode == "Replay incident over time" and bundle.get("timeline"):
        stage_count = len(bundle["timeline"])
        stage_index = st.slider(
            "Replay progress",
            min_value=0,
            max_value=stage_count - 1,
            value=stage_count - 1,
            format="%d",
        )
        active_bundle = build_replay_bundle(bundle, stage_index)
        render_replay_stage(active_bundle["replay_stage"])

    render_scenario_preview(active_bundle)

    if auto_run or run_clicked:
        coordinator = CoordinatorAgent()
        report = coordinator.run(active_bundle)

        left, right = st.columns([1.4, 1])
        with left:
            render_report(report)
        with right:
            render_agent_trace(report["agent_trace"])


if __name__ == "__main__":
    main()
