"""Fitness Scout orchestrator + CLI."""
import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from . import backlog, config, discovery, emailer, teardown
from .firecrawl_client import FirecrawlClient

load_dotenv()

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger("scout")


def _anthropic():
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def _firecrawl():
    return FirecrawlClient(os.getenv("FIRECRAWL_API_KEY", ""))


def _today(today=None) -> str:
    return today or datetime.now().strftime("%Y-%m-%d")


def seed(url: str, today=None) -> bool:
    recs = backlog.load(config.CANDIDATES_FILE)
    domain = discovery.extract_domain(url)
    if not domain:
        log.error(f"could not parse domain from {url}")
        return False
    cand = backlog.new_candidate(domain, domain.split(".")[0], f"https://{domain}/", "A", "seed",
                                 _today(today), seed=True)
    added = backlog.add(recs, cand)
    backlog.save(recs, config.CANDIDATES_FILE)
    log.info(f"seed {'added' if added else 'already present'}: {domain}")
    return added


def list_covered() -> list:
    return [r for r in backlog.load(config.CANDIDATES_FILE) if r.get("covered")]


def _archive_brief(subject: str, body: str, today: str):
    Path(config.BRIEFS_DIR).mkdir(parents=True, exist_ok=True)
    (Path(config.BRIEFS_DIR) / f"{today}.html").write_text(body, encoding="utf-8")


def run_weekly(dry_run: bool = False, discover_only: bool = False, today=None) -> dict:
    today = _today(today)
    cfg = config.load_config()
    grounding = config.load_grounding()
    fc = _firecrawl()
    client = _anthropic()

    recs = backlog.load(config.CANDIDATES_FILE)
    kept, dropped = discovery.rebuild_backlog(recs, cfg.get("exclude_domains", []))
    if dropped:
        log.info(f"backlog rebuild: kept {kept}, dropped {dropped}")

    # 1. Discovery (never blocks delivery)
    try:
        n_disc = discovery.run_discovery(cfg, recs, fc, client, grounding, today)
        n_disc += discovery.meta_ad_library_boost(cfg, recs, fc, today)
    except Exception as e:
        log.warning(f"discovery failed, continuing on existing backlog: {e}")
        n_disc = 0
    backlog.save(recs, config.CANDIDATES_FILE)
    log.info(f"discovery added {n_disc} candidate(s)")

    if discover_only:
        return {"discovered": n_disc, "teardowns": 0, "sent": False}

    # 2. Select + analyze (iterative: skip non-platforms, pull the next)
    target = cfg.get("teardowns_per_week", 2)
    max_attempts = target + 6
    candidates = backlog.select_uncovered(recs, len(recs))  # all uncovered, priority order
    teardowns = []
    rejected = []
    attempts = 0
    for cand in candidates:
        if len(teardowns) >= target or attempts >= max_attempts:
            break
        attempts += 1
        try:
            td = teardown.analyze(cand, fc, client, grounding)
        except Exception as e:
            log.warning(f"teardown failed for {cand['domain']}: {e}")
            continue
        if td is None:
            continue  # scrape/analysis failure — leave uncovered, retry a future run
        if not td.get("is_platform", True):
            log.info(f"teardown rejected non-platform: {cand['domain']}")
            rejected.append(cand["domain"])
            continue
        teardowns.append(td)
        backlog.mark_covered(recs, cand["domain"], td["content_hash"], today)
    # Drop confirmed non-platforms so they're never re-selected (scrape failures stay).
    if rejected:
        recs[:] = [r for r in recs if r["domain"] not in rejected]
        log.info(f"dropped {len(rejected)} non-platform candidate(s) at teardown")

    # 3. Format
    subject, body = emailer.format_email(teardowns, today)

    # 4. Persist coverage + archive
    backlog.save(recs, config.CANDIDATES_FILE)
    covered_recs = [r for r in recs if r.get("covered")]
    backlog.save(covered_recs, config.COVERED_FILE)
    _archive_brief(subject, body, today)

    # 5. Send (unless dry-run)
    sent = False
    if dry_run:
        print(subject)
        print(body)
    else:
        sent = emailer.send_email(subject, body, cfg.get("recipient", emailer.GMAIL_USER))

    return {"discovered": n_disc, "teardowns": len(teardowns), "sent": sent}


def _git_commit(today: str):
    """Stage + commit scout/data so state persists across cloud runs. Push handled by the workflow."""
    try:
        subprocess.run(["git", "add", "scout/data"], check=False)
        subprocess.run(["git", "commit", "-m", f"scout run {today} [skip ci]"], check=False)
    except Exception as e:
        log.warning(f"git commit skipped: {e}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Fitness Scout — weekly competitor teardown agent")
    parser.add_argument("--dry-run", action="store_true", help="run everything except sending the email")
    parser.add_argument("--discover-only", action="store_true", help="refill backlog only, no email")
    parser.add_argument("--seed", metavar="URL", help="add a platform URL to the backlog (jumps the queue)")
    parser.add_argument("--covered", action="store_true", help="list platforms already sent")
    parser.add_argument("--commit", action="store_true", help="git commit scout/data after the run")
    args = parser.parse_args(argv)

    if args.seed:
        return 0 if seed(args.seed) else 1
    if args.covered:
        for r in list_covered():
            print(f"{r['covered_at']}  {r['domain']}")
        return 0

    result = run_weekly(dry_run=args.dry_run, discover_only=args.discover_only)
    log.info(f"run complete: {result}")

    send_failed = (not args.dry_run and not args.discover_only
                   and result["sent"] is False)
    if send_failed:
        log.error("scout run did not send an email — marking this run as failed")

    if args.commit and not args.dry_run:
        _git_commit(_today())

    return 1 if send_failed else 0


if __name__ == "__main__":
    sys.exit(main())
