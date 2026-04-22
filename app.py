from __future__ import annotations

import queue
import threading
from pathlib import Path

import streamlit as st

from incident_investigator.execution import get_execution_backend_status
from incident_investigator.llm import LLMConfig
from incident_investigator.orchestration.coordinator import CoordinatorAgent
from incident_investigator.tools.data_loader import (
    build_replay_bundle,
    list_scenarios,
    load_scenario_bundle,
)


st.set_page_config(
    page_title="Incident Investigator",
    page_icon="🚨",
    layout="wide",
)


def inject_ui_styles() -> None:
    st.markdown(
        """
        <style>
        .investigation-shell {
            border: 1px solid rgba(49, 51, 63, 0.15);
            border-radius: 18px;
            padding: 1rem 1rem 0.5rem 1rem;
            background: linear-gradient(180deg, rgba(248, 249, 252, 0.95), rgba(255, 255, 255, 0.98));
        }
        .iteration-card {
            border-left: 4px solid #0f766e;
            border-radius: 14px;
            background: #ffffff;
            padding: 0.85rem 1rem;
            margin-bottom: 0.9rem;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }
        .iteration-label {
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.06em;
            color: #0f766e;
            font-weight: 700;
            margin-bottom: 0.15rem;
        }
        .iteration-title {
            font-size: 1.05rem;
            font-weight: 700;
            color: #0f172a;
            margin-bottom: 0.2rem;
        }
        .iteration-caption {
            color: #475569;
            margin-bottom: 0.2rem;
        }
        .status-pill {
            display: inline-block;
            padding: 0.3rem 0.55rem;
            border-radius: 999px;
            background: #ecfeff;
            color: #155e75;
            font-size: 0.85rem;
            font-weight: 600;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def ensure_session_state() -> None:
    st.session_state.setdefault("investigation_signature", None)
    st.session_state.setdefault("investigation_running", False)
    st.session_state.setdefault("investigation_events", [])
    st.session_state.setdefault("investigation_llm_streams", [])
    st.session_state.setdefault("investigation_llm_stream_lookup", {})
    st.session_state.setdefault("investigation_report", None)
    st.session_state.setdefault("investigation_queue", None)
    st.session_state.setdefault("investigation_thread", None)


def render_overview() -> None:
    st.title("🚨 Incident Investigator")
    st.markdown(
        """
        **AI-Driven Operational Anomaly Investigation**
        
        This system analyzes raw user logs and observability signals to identify bottlenecks and errors. 
        The agent iteratively refines its search scope, analyzes evidence, and produces a structured root-cause report with mitigation steps.
        """
    )
    st.divider()


def render_scenario_preview(bundle: dict) -> None:
    st.subheader("📦 Scenario Dataset")
    
    with st.container():
        overview = bundle["metadata"]
        
        # Display sample data and problem clearly
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("### 📋 Incident Context")
            st.markdown(f"**Title:** {overview['title']}")
            st.info(f"**Summary:** {overview['summary']}")
        
        with col2:
            st.markdown("### ⚠️ Problem Statement")
            st.error(f"**Observed Issue:**\nThe system is detecting an anomaly. The agent needs to analyze the logs to find the bottleneck and explain why the severity is `{bundle.get('incident_severity', overview['severity'])}`.")

        st.divider()
        st.markdown("**📊 Observability Snapshot**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Raw events", len(bundle.get("raw_events", [])))
        c2.metric("Derived logs", len(bundle["logs"]))
        c3.metric("Traces", len(bundle["traces"]))
        c4.metric("Severity", bundle.get("incident_severity", overview["severity"]))

def render_replay_stage(stage: dict) -> None:
    # Keep for compatibility but simplify
    st.caption(f"Replay Phase: {stage['label']} | Severity: {stage['severity_hint']}")


def render_agent_trace(agent_trace: list[dict]) -> None:
    st.subheader("Agent Collaboration")
    for item in agent_trace:
        with st.expander(f'{item["agent"]}: {item["summary"]}', expanded=False):
            st.markdown(item["detail"])


def event_icon(kind: str) -> str:
    return {
        "run_started": "Start",
        "planned_step": "Plan",
        "llm_mode": "LLM",
        "llm_turn": "Turn",
        "tool_call": "Tool",
        "state_snapshot": "State",
        "execution_backend": "Backend",
        "skill_success": "Done",
        "skill_failure": "Retry",
        "llm_fallback": "Fallback",
        "llm_summary": "Summary",
        "run_completed": "Complete",
        "fatal_error": "Error",
        "note": "Note",
    }.get(kind, "Step")


def is_iteration_start(event: dict) -> bool:
    return event["kind"] in {"llm_turn", "planned_step"}


def build_iteration_title(index: int, event: dict) -> str:
    if event["kind"] == "llm_turn":
        return f"Iteration {index}: {event['detail']}"
    if event["kind"] == "planned_step":
        return f"Iteration {index}: {event['title']}"
    return f"Iteration {index}"


def group_events_by_iteration(events: list[dict]) -> tuple[list[dict], list[dict]]:
    prelude: list[dict] = []
    iterations: list[dict] = []
    current_iteration: dict | None = None
    iteration_index = 0

    for event in events:
        if is_iteration_start(event):
            iteration_index += 1
            current_iteration = {
                "index": iteration_index,
                "title": build_iteration_title(iteration_index, event),
                "events": [event],
            }
            iterations.append(current_iteration)
            continue

        if current_iteration is None:
            prelude.append(event)
        else:
            current_iteration["events"].append(event)

    return prelude, iterations


def render_event_item(position: int, event: dict) -> None:
    label = f'{position}. {event_icon(event["kind"])} · {event["title"]}'
    with st.expander(label, expanded=event["kind"] in {"skill_failure", "fatal_error"}):
        st.write(event["detail"])
        if event["payload"]:
            st.json(event["payload"])


def render_chatbot_timeline(events: list[dict]) -> None:
    prelude, iterations = group_events_by_iteration(events)

    st.subheader("Investigation Timeline")
    with st.container():
        st.markdown('<div class="investigation-shell">', unsafe_allow_html=True)

        if prelude:
            with st.chat_message("assistant"):
                st.markdown("**Session setup**")
                for index, event in enumerate(prelude, start=1):
                    render_event_item(index, event)

        for iteration in iterations:
            first_event = iteration["events"][0]
            st.markdown(
                (
                    '<div class="iteration-card">'
                    f'<div class="iteration-label">Iteration {iteration["index"]}</div>'
                    f'<div class="iteration-title">{iteration["title"]}</div>'
                    f'<div class="iteration-caption">{first_event["detail"]}</div>'
                    "</div>"
                ),
                unsafe_allow_html=True,
            )
            with st.chat_message("assistant"):
                for position, event in enumerate(iteration["events"], start=1):
                    render_event_item(position, event)

        st.markdown("</div>", unsafe_allow_html=True)


def guess_stream_language(content: str) -> str:
    stripped = content.strip()
    if stripped.startswith("{") or stripped.startswith("["):
        return "json"
    return "text"


def render_llm_response_streams(streams: list[dict]) -> None:
    if not streams:
        return

    st.subheader("LLM Responses")
    for stream in streams[-4:]:
        status = "Streaming" if not stream["completed"] else "Completed"
        with st.expander(f"{status} · {stream['label']}", expanded=not stream["completed"]):
            content = stream["content"] or "Waiting for model output..."
            st.code(content, language=guess_stream_language(content))


def render_live_event_feed(
    events: list[dict],
    status_placeholder,
    feed_placeholder,
    snapshot_placeholder,
) -> None:
    if not events:
        status_placeholder.markdown('<<spanspan class="status-pill">Waiting to start the investigation.</span>', unsafe_allow_html=True)
        return

    last_event = events[-1]
    status_placeholder.markdown(
        f'<<spanspan class="status-pill">Current step: {last_event["title"]}</span>',
        unsafe_allow_html=True,
    )
    status_placeholder.caption(last_event["detail"])


    # Removed render_chatbot_timeline(events) to simplify UI



def render_report(report: dict) -> None:
    st.subheader("📋 Final Incident Report")
    
    summary = report["anomaly_summary"]
    
    # Highlight the headline as a big banner
    st.info(f"**Incident:** {summary['headline']}")
    
    col1, col2 = st.columns([2, 1])
    with col1:
        st.markdown(f"**Summary**\n\n{summary['summary']}")
    with col2:
        st.markdown("**Quick Stats**")
        st.write(f"🔴 **Severity:** {summary['severity']}")
        st.write(f"⚙️ **Impacted Service:** {summary['impacted_service']}")
        st.write(f"🕒 **Window:** {summary['time_window']}")

    st.divider()

    st.markdown("### 🔍 Root-Cause Hypotheses")
    for idx, hypothesis in enumerate(report["root_causes"], start=1):
        with st.expander(f"Hypothesis {idx}: {hypothesis['title']} (Confidence: {hypothesis['confidence']})", expanded=True):
            st.markdown(f"**Rationale:** {hypothesis['rationale']}")
            if hypothesis["evidence"]:
                st.markdown("**Supporting Evidence:**")
                for evidence in hypothesis["evidence"]:
                    st.write(f"- {evidence}")

    st.divider()

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### ✅ Recommended Actions")
        for action in report["recommended_actions"]:
            st.success(action)
            
    with c2:
        st.markdown("### 🛠️ Technical Inspection Targets")
        for target in report["inspection_targets"]:
            st.code(target, language="text")

    if report.get("supporting_evidence"):
        with st.expander("View All Supporting Evidence"):
            for evidence in report["supporting_evidence"]:
                st.write(f"- {evidence}")


def build_run_signature(
    scenario_key: str,
    stage_index: int | None,
    demo_mode: str,
    execution_backend: str,
    use_vllm: bool,
    vllm_base_url: str,
    vllm_model: str,
) -> tuple:
    return (
        scenario_key,
        stage_index,
        demo_mode,
        execution_backend,
        use_vllm,
        vllm_base_url.strip(),
        vllm_model.strip(),
    )


def reset_investigation_state() -> None:
    st.session_state["investigation_running"] = False
    st.session_state["investigation_events"] = []
    st.session_state["investigation_llm_streams"] = []
    st.session_state["investigation_llm_stream_lookup"] = {}
    st.session_state["investigation_report"] = None
    st.session_state["investigation_queue"] = None
    st.session_state["investigation_thread"] = None


def start_investigation(
    bundle: dict,
    llm_config: LLMConfig | None,
    execution_backend: str,
    signature: tuple,
) -> None:
    if st.session_state["investigation_running"]:
        return

    reset_investigation_state()
    st.session_state["investigation_signature"] = signature
    st.session_state["investigation_running"] = True
    event_queue: queue.Queue[dict] = queue.Queue()
    st.session_state["investigation_queue"] = event_queue
    coordinator = CoordinatorAgent(
        llm_config=llm_config,
        execution_backend=execution_backend,
    )

    def worker() -> None:
        def handle_event(event: dict) -> None:
            event_queue.put({"type": "event", "payload": event})

        try:
            report = coordinator.run(bundle, event_callback=handle_event)
            event_queue.put({"type": "report", "payload": report})
        except Exception as exc:
            event_queue.put(
                {
                    "type": "event",
                    "payload": {
                        "kind": "fatal_error",
                        "title": "Investigation Error",
                        "detail": str(exc),
                        "payload": {},
                    },
                }
            )
            event_queue.put({"type": "report", "payload": None})
        finally:
            event_queue.put({"type": "done"})

    investigation_thread = threading.Thread(target=worker, daemon=True)
    st.session_state["investigation_thread"] = investigation_thread
    investigation_thread.start()


def drain_investigation_queue() -> None:
    event_queue = st.session_state.get("investigation_queue")
    if event_queue is None:
        return

    while not event_queue.empty():
        message = event_queue.get()
        if message["type"] == "event":
            event = message["payload"]
            if handle_llm_stream_event(event):
                continue
            if not event.get("transient", False):
                st.session_state["investigation_events"].append(event)
        elif message["type"] == "report":
            st.session_state["investigation_report"] = message["payload"]
        elif message["type"] == "done":
            st.session_state["investigation_running"] = False


def handle_llm_stream_event(event: dict) -> bool:
    if event["kind"] not in {"llm_response_start", "llm_response_delta", "llm_response_end"}:
        return False

    payload = event["payload"]
    stream_id = payload["stream_id"]
    streams = st.session_state["investigation_llm_streams"]
    lookup = st.session_state["investigation_llm_stream_lookup"]
    stream_index = lookup.get(stream_id)

    if event["kind"] == "llm_response_start":
        if stream_index is None:
            lookup[stream_id] = len(streams)
            streams.append(
                {
                    "id": stream_id,
                    "label": payload.get("label", event["title"]),
                    "content": "",
                    "completed": False,
                }
            )
        return True

    if stream_index is None:
        lookup[stream_id] = len(streams)
        streams.append(
            {
                "id": stream_id,
                "label": payload.get("label", event["title"]),
                "content": "",
                "completed": False,
            }
        )
        stream_index = lookup[stream_id]

    stream = streams[stream_index]
    if event["kind"] == "llm_response_delta":
        stream["content"] += payload.get("delta", "")
    elif event["kind"] == "llm_response_end":
        stream["content"] = payload.get("content", stream["content"])
        stream["completed"] = True
    return True


def render_investigation_panel() -> None:
    drain_investigation_queue()

    report = st.session_state.get("investigation_report")
    if report:
        st.divider()
        render_report(report)
    elif st.session_state["investigation_running"]:
        st.info("🕵️ Agent is currently investigating the logs... Please wait for the final report.")
        st.spinner("Analyzing evidence and synthesizing root cause...")


def main() -> None:
    ensure_session_state()
    inject_ui_styles()
    render_overview()
    data_root = Path(__file__).parent / "incident_investigator" / "data"
    scenarios = list_scenarios(data_root)
    scenario_options = {item["label"]: item["key"] for item in scenarios}
 
    with st.sidebar:
        st.header("Demo Controls")
        selected_label = st.selectbox("Choose scenario", list(scenario_options.keys()))
        scenario_key = scenario_options[selected_label]
        
        # Simplified sidebar - removed mode selection for cleaner UI
        st.divider()
        st.subheader("vLLM Configuration")
        
        execution_backend = "nemo_nat"
        backend_status = get_execution_backend_status(execution_backend)
        if backend_status.available:
            st.caption(backend_status.detail)
        else:
            st.warning(backend_status.detail)
            
        use_vllm = st.checkbox("Use vLLM API", value=True)
        vllm_base_url = st.text_input(
            "Base URL",
            value="http://localhost:8000/v1",
            disabled=not use_vllm,
        )
        vllm_model = st.text_input(
            "Model",
            value="google/gemma-4-31b-it",
            disabled=not use_vllm,
        )
        vllm_api_key = st.text_input(
            "API key",
            value="EMPTY",
            type="password",
            disabled=not use_vllm,
        )
        auto_run = st.checkbox("Run investigation immediately", value=True)
        run_clicked = st.button("Run Incident Investigation", type="primary")
 
    bundle = load_scenario_bundle(data_root, scenario_key)
 
    # Removed demo_mode logic to simplify
    active_bundle = bundle
    stage_index = None
 
    render_scenario_preview(active_bundle)
 
    llm_config = None
    if use_vllm and vllm_base_url and vllm_model:
        llm_config = LLMConfig(
            base_url=vllm_base_url,
            model=vllm_model,
            api_key=vllm_api_key or "EMPTY",
        )
 
    signature = build_run_signature(
        scenario_key=scenario_key,
        stage_index=stage_index,
        demo_mode="static",
        execution_backend=execution_backend,
        use_vllm=use_vllm,
        vllm_base_url=vllm_base_url,
        vllm_model=vllm_model,
    )
    if st.session_state["investigation_signature"] != signature:
        if not st.session_state["investigation_running"]:
            reset_investigation_state()
            st.session_state["investigation_signature"] = signature
 
    if run_clicked or (auto_run and not st.session_state["investigation_running"] and st.session_state["investigation_report"] is None):
        start_investigation(active_bundle, llm_config, execution_backend, signature)
 
    render_investigation_panel()


if __name__ == "__main__":
    main()
