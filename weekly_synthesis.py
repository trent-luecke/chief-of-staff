#!/usr/bin/env python3
"""Entry point for weekly synthesis. Called by weekly.yml workflow."""

import json
import os
import sys
from datetime import date

from dotenv import load_dotenv
load_dotenv()

from lib.google_auth import build_gmail_service
from lib.telegram import send_message
from outputs.sender import send_brief_email
from processors.weekly_synthesizer import synthesize_week, WeeklySynthesis
from processors.retrieval_digest import generate_digest


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


def _save_synthesis(synthesis: WeeklySynthesis, weekly_dir: str, run_date: date) -> None:
    os.makedirs(weekly_dir, exist_ok=True)
    path = os.path.join(weekly_dir, f"{run_date.isoformat()}.md")
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
    with open(path, "w") as f:
        f.write("\n".join(lines))
    print(f"Saved: {path}")


def _main_inner(config: dict, run_date) -> None:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set.", file=sys.stderr)
        sys.exit(1)

    memory_cfg = config.get("memory", {})

    print("Generating weekly synthesis...")
    try:
        synthesis = synthesize_week(
            api_key=api_key,
            model=config["ai_model"],
            obs_file=memory_cfg.get("observations_file", "data/memory/observations.jsonl"),
            state_dir=config["state_dir"],
            issues_file=config["issues_file"],
            captures_file=config.get("captures_file", "data/captures.md"),
            run_date=run_date,
            log_file=config.get("logs_file"),
        )
    except Exception as e:
        print(f"ERROR: synthesis failed: {e}", file=sys.stderr)
        sys.exit(1)

    _save_synthesis(synthesis, "data/weekly", run_date)

    gmail = build_gmail_service(config["email"])
    subject = f"📊 Weekly Synthesis — week ending {run_date.isoformat()}"
    html = _render_html(synthesis, run_date.isoformat())

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

    # Retrieval digest — sent via Telegram alongside the weekly synthesis
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "")
    if bot_token and chat_id:
        try:
            vector_cfg = config.get("vector", {})
            digest = generate_digest(
                api_key=api_key,
                model=config["ai_model"],
                scores_file=config.get("brief_scores_file", "data/state/brief_scores.jsonl"),
                retrieval_log_file=vector_cfg.get("retrieval_log_file", "data/state/retrieval_log.jsonl"),
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
            send_message(bot_token, chat_id, header + digest)
            print("Retrieval digest sent via Telegram.")
        except Exception as e:
            print(f"WARNING: retrieval digest failed: {e}", file=sys.stderr)

    print(f"\nSummary: {synthesis.executive_summary}")
    if synthesis.carry_forwards:
        print("\nCarry-Forwards:")
        for item in synthesis.carry_forwards:
            print(f"  → {item}")


def main() -> None:
    config = load_config()
    run_date = date.today()

    from lib.llm_logger import flush
    try:
        _main_inner(config, run_date)
    finally:
        flush("weekly_synthesis", config.get("logs_file", "data/logs/run_log.jsonl"))


if __name__ == "__main__":
    main()
