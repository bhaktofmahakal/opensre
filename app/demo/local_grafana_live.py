"""Run RCA against a real local Grafana instance with synthetic alert payload."""

from __future__ import annotations

import argparse
import time
from typing import Any, cast

import requests
from dotenv import load_dotenv

load_dotenv(override=False)

from app.agent.nodes.publish_findings.node import generate_report  # noqa: E402
from app.agent.nodes.root_cause_diagnosis.node import diagnose_root_cause  # noqa: E402
from app.agent.state import InvestigationState, make_initial_state  # noqa: E402
from app.agent.tools.tool_actions.grafana.grafana_actions import query_grafana_logs  # noqa: E402
from app.demo.local_grafana_seed import PIPELINE_NAME, SERVICE_NAME  # noqa: E402
from app.demo.local_rca import require_llm_config  # noqa: E402

LOCAL_GRAFANA_URL = "http://localhost:3000"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run RCA against a live local Grafana+Loki demo stack."
    )
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write the rendered RCA report as Markdown.",
    )
    return parser.parse_args(argv)


def ensure_local_grafana_running() -> None:
    try:
        response = requests.get(f"{LOCAL_GRAFANA_URL}/api/health", timeout=3)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise SystemExit(
            "Local Grafana is not running. Start it with `make grafana-local-up` and retry."
        ) from exc


def fetch_live_grafana_evidence() -> dict[str, Any]:
    last_error = "unknown"
    for _ in range(10):
        result = query_grafana_logs(
            SERVICE_NAME,
            time_range_minutes=15,
            limit=50,
            grafana_endpoint=LOCAL_GRAFANA_URL,
            grafana_api_key="",
        )
        if result.get("available") and result.get("logs"):
            return {
                "grafana_logs": result.get("logs", []),
                "grafana_error_logs": result.get("error_logs", []),
                "grafana_logs_query": result.get("query", ""),
                "grafana_logs_service": result.get("service_name", ""),
            }
        last_error = str(result.get("error") or "no logs found")
        time.sleep(1)

    raise SystemExit(
        "Tracer could not query the local Grafana stack yet. "
        f"Last error: {last_error}. "
        "Make sure `make grafana-local-up` completed, then retry `make local-grafana-live`."
    )


def build_synthetic_alert() -> dict[str, Any]:
    return {
        "title": "[FIRING:1] LocalGrafanaPipelineFailure critical - events_fact",
        "state": "alerting",
        "commonLabels": {
            "alertname": "LocalGrafanaPipelineFailure",
            "severity": "critical",
            "pipeline_name": PIPELINE_NAME,
            "grafana_folder": "local-demos",
        },
        "commonAnnotations": {
            "summary": "events_fact stopped updating after a local pipeline failure",
            "source_url": f"{LOCAL_GRAFANA_URL}/explore",
        },
        "externalURL": LOCAL_GRAFANA_URL,
        "message": (
            "Synthetic local Grafana alert for the live demo. "
            "The events_fact pipeline stopped updating after an authentication failure."
        ),
    }


def build_problem_md(
    *,
    alert_name: str,
    pipeline_name: str,
    severity: str,
    error_message: str,
) -> str:
    parts = [f"# {alert_name}", f"Pipeline: {pipeline_name} | Severity: {severity}"]
    if error_message:
        parts.append(f"\nError: {error_message}")
    return "\n".join(parts)


def prepare_demo_state(evidence: dict[str, Any]) -> InvestigationState:
    alert = build_synthetic_alert()
    state = make_initial_state(
        alert_name=str(alert["title"]),
        pipeline_name=PIPELINE_NAME,
        severity="critical",
        raw_alert={**alert, "alert_source": "grafana"},
    )
    state["problem_md"] = build_problem_md(
        alert_name=str(alert["title"]),
        pipeline_name=PIPELINE_NAME,
        severity="critical",
        error_message=str(alert["commonAnnotations"]["summary"]),
    )
    state["alert_source"] = "grafana"
    state["evidence"] = evidence
    state["available_sources"] = {
        "grafana": {"grafana_endpoint": LOCAL_GRAFANA_URL}
    }
    return state


def run_demo(argv: list[str] | None = None) -> str:
    args = parse_args(argv)
    require_llm_config("make local-grafana-live")
    ensure_local_grafana_running()

    evidence = fetch_live_grafana_evidence()
    state = prepare_demo_state(evidence)

    diagnosis = cast(InvestigationState, diagnose_root_cause(state))
    state.update(diagnosis)

    report = str(generate_report(state)["slack_message"])
    if args.output:
        from pathlib import Path

        Path(args.output).write_text(report + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    run_demo(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
