from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any

from incident_investigator.execution import get_execution_backend_status
from incident_investigator.llm import LLMConfig
from incident_investigator.orchestration.coordinator import CoordinatorAgent
from incident_investigator.tools.data_loader import list_scenarios, load_scenario_bundle

try:
    from rich.console import Console, Group
    from rich.json import JSON
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - optional at runtime
    Console = None
    Group = None
    JSON = None
    Layout = None
    Live = None
    Panel = None
    Table = None
    RICH_AVAILABLE = False


class JsonlEventLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None
        self._sequence = 0

    def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def stop(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None

    def handle_event(self, event: dict) -> None:
        if self._handle is None:
            return
        self._sequence += 1
        record = {
            "sequence": self._sequence,
            "timestamp": time.time(),
            "event": event,
        }
        self._handle.write(json.dumps(record) + "\n")
        self._handle.flush()


def format_elapsed(started_at: float) -> str:
    elapsed = max(0.0, time.time() - started_at)
    minutes = int(elapsed // 60)
    seconds = elapsed - (minutes * 60)
    return f"{minutes:02d}:{seconds:04.1f}"


def summarize_event_payload(event: dict[str, Any]) -> list[str]:
    payload = event.get("payload", {})
    kind = event["kind"]

    if kind == "run_started":
        return [
            f"scenario={payload.get('scenario', 'unknown')}",
            f"llm_enabled={payload.get('llm_enabled', False)}",
            f"backend={payload.get('execution_backend', 'unknown')}",
        ]

    if kind == "execution_backend":
        return [f"backend={payload.get('backend', 'unknown')}"]

    if kind in {"planned_step", "llm_turn", "tool_call"}:
        return []

    if kind == "state_snapshot":
        known_fields = payload.get("known_fields", {})
        if not known_fields:
            return ["state_snapshot=empty"]
        return [f"known_fields={', '.join(sorted(known_fields))}"]

    if kind in {"skill_success", "skill_failure"}:
        lines = [
            f"attempt={payload.get('attempt', '?')}",
            f"confidence={payload.get('confidence', 0.0):.2f}" if "confidence" in payload else None,
        ]
        findings = payload.get("findings", {})
        lines.extend(summarize_findings(findings))
        errors = payload.get("errors", [])
        if errors:
            lines.append(f"errors={'; '.join(errors[:2])}")
        return [line for line in lines if line]

    if payload:
        return [json.dumps(payload, ensure_ascii=True)]
    return []


def summarize_findings(findings: dict[str, Any]) -> list[str]:
    if not findings:
        return []

    lines: list[str] = []
    metric_summary = findings.get("metric_summary")
    if metric_summary:
        lines.append(
            "latency="
            f"{metric_summary.get('highest_latency_service', 'unknown')} "
            f"({metric_summary.get('baseline_latency_ms', '?')} -> {metric_summary.get('max_latency_ms', '?')} ms)"
        )

    log_summary = findings.get("log_summary")
    if log_summary:
        lines.append(
            "errors="
            f"{log_summary.get('top_error_component', 'unknown')} "
            f"(count={log_summary.get('error_count', '?')})"
        )

    user_summary = findings.get("user_summary")
    if user_summary:
        lines.append(
            "user_impact="
            f"{user_summary.get('most_impacted_flow', 'unknown')} "
            f"(dropoff_delta={user_summary.get('dropoff_rate_delta', '?')})"
        )

    trace_summary = findings.get("trace_summary")
    if trace_summary:
        lines.append(
            "trace_window="
            f"{trace_summary.get('primary_window', 'unknown')}"
        )
        hot_services = trace_summary.get("hot_services", [])
        if hot_services:
            lines.append(f"hot_services={', '.join(hot_services[:3])}")

    relevant_artifacts = findings.get("relevant_artifacts")
    if relevant_artifacts:
        lines.append(f"artifacts={len(relevant_artifacts)} candidates")

    suspicious_components = findings.get("suspicious_components")
    if suspicious_components:
        formatted = ", ".join(component for component, _ in suspicious_components[:3])
        lines.append(f"suspicious_components={formatted}")

    hypotheses = findings.get("hypotheses")
    if hypotheses:
        top = hypotheses[0]
        lines.append(
            f"top_hypothesis={top.get('title', 'unknown')} [{top.get('confidence', 'unknown')}]"
        )

    evidence_gaps = findings.get("evidence_gaps")
    if evidence_gaps is not None:
        lines.append(f"evidence_gaps={len(evidence_gaps)}")

    recommended_actions = findings.get("recommended_actions")
    if recommended_actions:
        lines.append(f"recommended_actions={len(recommended_actions)}")

    inspection_targets = findings.get("inspection_targets")
    if inspection_targets:
        lines.append(f"inspection_targets={len(inspection_targets)}")

    anomalies = findings.get("anomalies")
    if anomalies:
        lines.append(f"anomalies={len(anomalies)}")

    return lines[:5]


def format_flow_line(event: dict[str, Any], event_index: int, started_at: float) -> str:
    elapsed = format_elapsed(started_at)
    kind = event["kind"]
    title = event["title"]
    detail = event["detail"]
    kind_labels = {
        "run_started": "START",
        "execution_backend": "BACKEND",
        "note": "NOTE",
        "planned_step": "STEP",
        "llm_mode": "LLM",
        "llm_turn": "TURN",
        "tool_call": "TOOL",
        "state_snapshot": "STATE",
        "skill_success": "DONE",
        "skill_failure": "RETRY",
        "llm_fallback": "FALLBACK",
        "llm_summary": "SUMMARY",
        "run_completed": "COMPLETE",
        "fatal_error": "ERROR",
    }
    label = kind_labels.get(kind, kind.upper())
    return f"[{event_index:02d} | {elapsed}] {label:<8} {title} :: {detail}"


class PlainTerminalEventStreamer:
    def __init__(self, verbose_payloads: bool = False) -> None:
        self._active_stream_id: str | None = None
        self._event_index = 0
        self._started_at = time.time()
        self._verbose_payloads = verbose_payloads

    def start(self) -> None:
        return None

    def stop(self) -> None:
        self._ensure_break()

    def handle_event(self, event: dict) -> None:
        kind = event["kind"]
        if kind == "llm_response_start":
            self._ensure_break()
            label = event["payload"].get("label", event["title"])
            print(f"\n[llm] {label}", flush=True)
            self._active_stream_id = event["payload"]["stream_id"]
            return

        if kind == "llm_response_delta":
            delta = event["payload"].get("delta", "")
            print(delta, end="", flush=True)
            return

        if kind == "llm_response_end":
            if self._active_stream_id is not None:
                print(flush=True)
            self._active_stream_id = None
            return

        if event.get("transient"):
            return

        self._ensure_break()
        self._event_index += 1
        print(format_flow_line(event, self._event_index, self._started_at), flush=True)
        if self._verbose_payloads and event["payload"]:
            print(json.dumps(event["payload"], indent=2), flush=True)
            return

        for line in summarize_event_payload(event):
            print(f"  - {line}", flush=True)

    def _ensure_break(self) -> None:
        if self._active_stream_id is not None:
            print(flush=True)
            self._active_stream_id = None


class RichTerminalDashboard:
    def __init__(self, scenario: str, llm_enabled: bool) -> None:
        self.console = Console()
        self.scenario = scenario
        self.llm_enabled = llm_enabled
        self.status_title = "Waiting to start"
        self.status_detail = "Preparing investigation..."
        self.started_at = time.time()
        self.event_index = 0
        self.timeline: list[str] = []
        self.recent_detail_lines: list[str] = []
        self.latest_snapshot: dict[str, Any] | None = None
        self.active_llm_label: str | None = None
        self.active_llm_content = ""
        self.completed_llm_streams: list[tuple[str, str]] = []
        self.final_report: dict[str, Any] | None = None
        self._live: Live | None = None

    def start(self) -> None:
        self._live = Live(self.render(), console=self.console, refresh_per_second=8)
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.update(self.render())
            self._live.stop()
            self._live = None

    def handle_event(self, event: dict) -> None:
        kind = event["kind"]
        if kind == "llm_response_start":
            self.active_llm_label = event["payload"].get("label", event["title"])
            self.active_llm_content = ""
            self._refresh()
            return

        if kind == "llm_response_delta":
            self.active_llm_content += event["payload"].get("delta", "")
            self._refresh()
            return

        if kind == "llm_response_end":
            label = event["payload"].get("label", event["title"])
            content = event["payload"].get("content", self.active_llm_content)
            self.completed_llm_streams.append((label, content))
            self.completed_llm_streams = self.completed_llm_streams[-3:]
            self.active_llm_label = None
            self.active_llm_content = ""
            self._refresh()
            return

        if event.get("transient"):
            return

        self.event_index += 1
        self.status_title = event["title"]
        self.status_detail = event["detail"]
        self.timeline.append(format_flow_line(event, self.event_index, self.started_at))
        self.timeline = self.timeline[-12:]
        detail_lines = summarize_event_payload(event)
        if detail_lines:
            self.recent_detail_lines = detail_lines
        if event["payload"]:
            self.latest_snapshot = event["payload"]
        self._refresh()

    def set_final_report(self, report: dict[str, Any]) -> None:
        self.final_report = report
        self.status_title = "Investigation completed"
        self.status_detail = report["anomaly_summary"]["headline"]
        self._refresh()

    def render(self):
        layout = Layout()
        layout.split_column(
            Layout(name="top", size=7),
            Layout(name="middle", ratio=3),
            Layout(name="bottom", ratio=3),
        )
        layout["middle"].split_row(
            Layout(name="timeline"),
            Layout(name="llm"),
        )
        layout["bottom"].split_row(
            Layout(name="snapshot"),
            Layout(name="report"),
        )
        layout["top"].update(self._render_status())
        layout["timeline"].update(self._render_timeline())
        layout["llm"].update(self._render_llm())
        layout["snapshot"].update(self._render_snapshot())
        layout["report"].update(self._render_report())
        return layout

    def _render_status(self):
        table = Table.grid(expand=True)
        table.add_column(justify="left", ratio=2)
        table.add_column(justify="left", ratio=2)
        table.add_column(justify="left", ratio=1)
        table.add_column(justify="left", ratio=1)
        table.add_row(
            f"[bold]Scenario[/bold]\n{self.scenario}",
            f"[bold]Current Step[/bold]\n{self.status_title}\n{self.status_detail}",
            f"[bold]LLM Mode[/bold]\n{'Enabled' if self.llm_enabled else 'Deterministic'}",
            f"[bold]Elapsed[/bold]\n{format_elapsed(self.started_at)}",
        )
        return Panel(table, title="Incident Investigator CLI", border_style="cyan")

    def _render_timeline(self):
        flow_body = "\n".join(self.timeline) if self.timeline else "No events yet."
        detail_body = "\n".join(f"- {line}" for line in self.recent_detail_lines) if self.recent_detail_lines else "No structured details yet."
        return Panel(
            Group(
                Panel(flow_body, title="Flow", border_style="green"),
                Panel(detail_body, title="Current Details", border_style="cyan"),
            ),
            title="Execution Flow",
            border_style="green",
        )

    def _render_llm(self):
        parts: list[Any] = []
        if self.active_llm_label is not None:
            parts.append(
                Panel(
                    self.active_llm_content or "Waiting for model output...",
                    title=f"Streaming: {self.active_llm_label}",
                    border_style="yellow",
                )
            )
        if self.completed_llm_streams:
            for label, content in reversed(self.completed_llm_streams):
                parts.append(
                    Panel(
                        content or "Empty response",
                        title=f"Completed: {label}",
                        border_style="magenta",
                    )
                )
        if not parts:
            parts.append("No LLM output yet.")
        return Panel(Group(*parts), title="LLM Output", border_style="yellow")

    def _render_snapshot(self):
        if self.latest_snapshot is None:
            return Panel("No snapshot yet.", title="Latest Snapshot", border_style="blue")
        return Panel(JSON.from_data(self.latest_snapshot), title="Latest Snapshot", border_style="blue")

    def _render_report(self):
        if self.final_report is None:
            return Panel("Final report will appear here.", title="Final Report", border_style="white")
        summary = self.final_report["anomaly_summary"]
        root_causes = "\n".join(
            f"- {item['title']} ({item['confidence']})"
            for item in self.final_report.get("root_causes", [])[:3]
        ) or "- None"
        actions = "\n".join(
            f"- {item}" for item in self.final_report.get("recommended_actions", [])[:3]
        ) or "- None"
        body = (
            f"[bold]{summary['headline']}[/bold]\n"
            f"{summary['summary']}\n\n"
            f"Severity: {summary['severity']}\n"
            f"Impacted service: {summary['impacted_service']}\n"
            f"Window: {summary['time_window']}\n\n"
            f"[bold]Root Causes[/bold]\n{root_causes}\n\n"
            f"[bold]Actions[/bold]\n{actions}"
        )
        return Panel(body, title="Final Report", border_style="white")

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self.render())


class CompositeEventHandler:
    def __init__(self, handlers: list[Any]) -> None:
        self.handlers = handlers

    def start(self) -> None:
        for handler in self.handlers:
            start = getattr(handler, "start", None)
            if callable(start):
                start()

    def stop(self) -> None:
        for handler in reversed(self.handlers):
            stop = getattr(handler, "stop", None)
            if callable(stop):
                stop()

    def handle_event(self, event: dict) -> None:
        for handler in self.handlers:
            handler.handle_event(event)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Incident Investigator demo.")
    parser.add_argument(
        "scenario",
        nargs="?",
        default="checkout_latency_incident",
        help="Scenario slug under incident_investigator/data.",
    )
    parser.add_argument(
        "--scenario-list",
        action="store_true",
        help="List available scenarios and exit.",
    )
    parser.add_argument(
        "--no-stream",
        action="store_true",
        help="Disable live streaming and print only the final report JSON.",
    )
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Force plain terminal streaming instead of the Rich dashboard.",
    )
    parser.add_argument(
        "--jsonl-log",
        type=Path,
        help="Write all streamed events to a JSONL log file.",
    )
    parser.add_argument(
        "--execution-backend",
        choices=["native", "nemo_nat"],
        default="native",
        help="Select how investigation skills are executed.",
    )
    parser.add_argument(
        "--verbose-events",
        action="store_true",
        help="Print full event payload JSON instead of compact flow summaries in plain mode.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = Path(__file__).parent / "incident_investigator" / "data"
    scenarios = list_scenarios(data_root)
    if args.scenario_list:
        for scenario in scenarios:
            print(f"{scenario['key']}: {scenario['label']}")
        return

    scenario = args.scenario
    bundle = load_scenario_bundle(data_root, scenario)
    llm_config = LLMConfig.from_env()
    backend_status = get_execution_backend_status(args.execution_backend)
    if not backend_status.available:
        raise RuntimeError(backend_status.detail)
    handlers: list[Any] = []
    if not args.no_stream:
        if RICH_AVAILABLE and not args.plain:
            handlers.append(
                RichTerminalDashboard(
                    scenario=bundle["metadata"]["title"],
                    llm_enabled=llm_config is not None,
                )
            )
        else:
            handlers.append(PlainTerminalEventStreamer(verbose_payloads=args.verbose_events))
    if args.jsonl_log is not None:
        handlers.append(JsonlEventLogger(args.jsonl_log))

    composite_handler = CompositeEventHandler(handlers) if handlers else None
    event_callback = composite_handler.handle_event if composite_handler is not None else None

    if composite_handler is not None:
        composite_handler.start()
    try:
        report = CoordinatorAgent(
            llm_config=llm_config,
            execution_backend=args.execution_backend,
        ).run(bundle, event_callback=event_callback)
        if composite_handler is not None:
            for handler in composite_handler.handlers:
                set_final_report = getattr(handler, "set_final_report", None)
                if callable(set_final_report):
                    set_final_report(report)
    finally:
        if composite_handler is not None:
            composite_handler.stop()

    if event_callback is not None and (not RICH_AVAILABLE or args.plain):
        print("\n[final_report]", flush=True)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
