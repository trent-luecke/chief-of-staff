#!/usr/bin/env python3
"""Entry point for weekly synthesis. Called by weekly.yml workflow."""

import json
import os
import sys
from datetime import date

from dotenv import load_dotenv
load_dotenv()

from lib.google_auth import build_gmail_service
from lib.notify import notify_user
from outputs.sender import send_brief_email
from processors.weekly_synthesizer import synthesize_week, WeeklySynthesis
from processors.retrieval_digest import generate_digest
from processors.pattern_detector import (
    detect_anomalies, scan_upcoming_demos,
    AnomalyReport, DemoScanReport,
)


def load_config(path: str = "config.json") -> dict:
    with open(path) as f:
        return json.load(f)


def _render_html(synthesis: WeeklySynthesis, week_end: str) -> str:
    def ul(items: list[str]) -> str:
        if not items:
            return "<p><em>None</em></p>"
        return "<ul>" + "".join(f"<li>{i}</li>" for i in items) + "</ul>"

    sections = [
        f'<h2>Week ending {week_end}</h2>',
        f'<p>{synthesis.executive_summary}</p>',
    ]
    if synthesis.patterns:
        sections += ['<h3>Patterns</h3>', ul(synthesis.patterns)]
    if synthesis.resolved_this_week:
        sections += ['<h3>Resolved This Week</h3>', ul(synthesis.resolved_this_week)]
    if synthesis.carry_forwards:
        sections += ['<h3>Carry-Forwards Into Next Week</h3>', ul(synthesis.carry_forwards)]
    if synthesis.meta_observation:
        sections += [
            '<h3>Meta Observation</h3>',
            f'<p><em>{synthesis.meta_observation}</em></p>',
        ]
    return "\n".join(sections)


def _save_synthesis(storage, synthesis: WeeklySynthesis, run_date: date) -> None:
    key = f"weekly/{run_date.isoformat()}.md"
    lines = [
        f"# Weekly Synthesis — {run_date.isoformat()}",
        "",
        synthesis.executive_summary,
        "",
    ]
    if synthesis.patterns:
        lines += ["## Patterns", *[f"- {p}" for p in synthesis.patterns], ""]
    if synthesis.resolved_this_week:
        lines += ["## Resolved This Week", *[f"- {r}" for r in synthesis.resolved_this_week], ""]
    if synthesis.carry_forwards:
        lines += ["## Carry-Forwards", *[f"- {c}" for c in synthesis.carry_forwards], ""]
    if synthesis.meta_observation:
        lines += ["## Meta Observation", synthesis.meta_observation, ""]
    storage.write(key, "\n".join(lines))
    print(f"Saved: {key}")


def _render_trends_html(anomaly_report: AnomalyReport, demo_report: DemoScanReport) -> str:
    if not anomaly_report.anomalies and not demo_report.demos:
        return ""
    parts = ["<h3>Trends &amp; Demo Health</h3>"]
    if anomaly_report.anomalies:
        parts.append("<h4>Pattern Alerts</h4><ul>")
        for a in anomaly_report.anomalies:
            parts.append(f"<li><strong>{a.title}</strong> — {a.description}</li>")
        parts.append("</ul>")
    if demo_report.demos:
        parts.append(f"<h4>Upcoming Demos ({demo_report.total} in next 28 days)</h4><ul>")
        for d in demo_report.demos:
            lead_info = d.lead_name or "new prospect"
            stage_info = f" ({d.pipeline_stage})" if d.pipeline_stage else " (not in pipeline)"
            parts.append(f"<li>{d.date.isoformat()} — {d.title} — {lead_info}{stage_info}</li>")
        parts.append("</ul>")
    return "\n".join(parts)


def _format_trends_telegram(anomaly_report: AnomalyReport, demo_report: DemoScanReport) -> str:
    lines = []
    if anomaly_report.anomalies:
        lines.append("Pattern Alerts:")
        for a in anomaly_report.anomalies:
            lines.append(f"• {a.title} — {a.description}")
        lines.append("")
    if demo_report.demos:
        lines.append(f"Upcoming Demos ({demo_report.total} in next 28 days):")
        for d in demo_report.demos:
            lead_info = d.lead_name or "new prospect"
            stage_info = f" ({d.pipeline_stage})" if d.pipeline_stage else ""
            lines.append(f"• {d.date.isoformat()} — {d.title} — {lead_info}{stage_info}")
    return "\n".join(lines)


def _main_inner(config: dict, run_date, storage) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    print("Generating weekly synthesis...")
    try:
        synthesis = synthesize_week(
            storage=storage,
            api_key=api_key,
            model=config["ai_model"],
            run_date=run_date,
        )
    except Exception as e:
        print(f"ERROR: synthesis failed: {e}", file=sys.stderr)
        sys.exit(1)

    _save_synthesis(storage, synthesis, run_date)

    anomaly_report = AnomalyReport()
    demo_report = DemoScanReport()

    if config.get("demo_scan", {}).get("enabled"):
        try:
            anomaly_report = detect_anomalies(storage, synthesis, run_date, api_key, config["ai_model"])
        except Exception as e:
            print(f"WARNING: anomaly detection failed: {e}", file=sys.stderr)
        try:
            demo_report = scan_upcoming_demos(config, config["email"], run_date, storage)
        except Exception as e:
            print(f"WARNING: demo scan failed: {e}", file=sys.stderr)

    gmail = build_gmail_service(config["email"])
    subject = f"📊 Weekly Synthesis — week ending {run_date.isoformat()}"
    html = _render_html(synthesis, run_date.isoformat())
    trends_html = _render_trends_html(anomaly_report, demo_report)
    if trends_html:
        html += "\n" + trends_html

    try:
        msg_id, _ = send_brief_email(
            gmail_service=gmail,
            to_email=config["email"],
            subject=subject,
            html_body=html,
            plain_text="Weekly synthesis — view in an HTML-capable email client.",
        )
        print(f"Sent: {msg_id}")
    except Exception as e:
        print(f"WARNING: could not send email: {e}", file=sys.stderr)

    # Retrieval digest — sent via Slack alongside the weekly synthesis
    try:
        vector_cfg = config.get("vector", {})
        digest = generate_digest(
            storage=storage,
            api_key=api_key,
            model=config["ai_model"],
            config_snapshot={
                "retrieval_mode": vector_cfg.get("retrieval_mode", "auto"),
                "top_k": vector_cfg.get("top_k", 20),
                "memory_budget_pct": vector_cfg.get("memory_budget_pct", 0.6),
                "observation_budget_pct": vector_cfg.get("observation_budget_pct", 0.4),
                "score_threshold": vector_cfg.get("score_threshold"),
            },
            run_date=run_date,
        )
        header = f"Brief Scores — week ending {run_date.isoformat()}\n\n"
        notify_user(header + digest, config)
        print("Retrieval digest sent via Slack.")
    except Exception as e:
        print(f"WARNING: retrieval digest failed: {e}", file=sys.stderr)

    trends_text = _format_trends_telegram(anomaly_report, demo_report)
    if trends_text:
        try:
            header = f"📈 Trends & Demo Health — week ending {run_date.isoformat()}\n\n"
            notify_user(header + trends_text, config)
            print("Trends & demo health sent via Slack.")
        except Exception as e:
            print(f"WARNING: trends Slack send failed: {e}", file=sys.stderr)

    print(f"\nSummary: {synthesis.executive_summary}")
    if synthesis.carry_forwards:
        print("\nCarry-Forwards:")
        for item in synthesis.carry_forwards:
            print(f"  → {item}")


def main() -> None:
    config = load_config()
    run_date = date.today()
    from lib.storage import build_storage
    from lib.llm_logger import flush
    storage = build_storage(config)
    try:
        _main_inner(config, run_date, storage)
    finally:
        flush("weekly_synthesis", storage)


if __name__ == "__main__":
    main()
