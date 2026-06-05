#!/usr/bin/env python3
"""GTM metrics dashboard — reads data/gtm_snapshot.json, writes output/gtm_dashboard.html."""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_ROOT))

from lib.gtm_metrics import MetricResult, evaluate_metrics  # noqa: E402

_SNAPSHOT = _ROOT / "data" / "gtm_snapshot.json"
_OUTPUT = _ROOT / "output" / "gtm_dashboard.html"
_CONFIG = _ROOT / "config.json"


def render_html(results: list[MetricResult], generated_at: str) -> str:
    """Return a full HTML string from evaluated MetricResult objects."""

    def _badge(r: MetricResult) -> str:
        if r.stale:
            return '<span class="badge stale">STALE</span>'
        if r.current is None:
            return '<span class="badge no-data">NO DATA</span>'
        if r.breach:
            return '<span class="badge breach">BREACH</span>'
        return '<span class="badge ok">OK</span>'

    def _val(v) -> str:
        if v is None:
            return "—"
        return str(int(v)) if isinstance(v, float) and v == int(v) else str(v)

    def _horizon(h: str) -> str:
        return "Next-Month Signal" if h == "next-month" else "This Month"

    def _row(r: MetricResult) -> str:
        detail = ""
        if r.stale and r.stale_reason:
            detail = f'<div class="det stale-det">⚠ {r.stale_reason}</div>'
        elif r.breach and r.breach_reason:
            detail = f'<div class="det breach-det">▲ {r.breach_reason}</div>'
        row = (
            f'<tr class="{"breach-row" if r.breach else "stale-row" if r.stale else ""}">'
            f'<td class="lbl" data-metric-id="{r.id}">{r.label}</td>'
            f'<td>{_val(r.current)}</td>'
            f'<td>{_val(r.target)}</td>'
            f'<td>{_badge(r)}</td>'
            f'<td class="hz">{_horizon(r.horizon)}</td>'
            f'</tr>'
        )
        if detail:
            row += f'<tr class="det-row"><td colspan="5">{detail}</td></tr>'
        return row

    rows = "\n".join(_row(r) for r in results)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>GTM Metrics</title>
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:760px;margin:0 auto;color:#1a1a1a;background:#f9f9f9}}
  .hdr{{background:linear-gradient(135deg,#1a1a2e,#16213e);color:#fff;padding:28px 32px;border-radius:8px 8px 0 0}}
  .hdr h1{{margin:0;font-size:22px;font-weight:600}}
  .hdr .ts{{margin:4px 0 0;font-size:14px;opacity:.75}}
  .bdy{{background:#fff;padding:28px 32px;border-radius:0 0 8px 8px;border:1px solid #e5e5e5;border-top:none}}
  table{{width:100%;border-collapse:collapse}}
  th{{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:#888;text-align:left;padding:0 8px 8px}}
  td{{padding:10px 8px;border-bottom:1px solid #f0f0f0;font-size:14px}}
  .lbl{{font-weight:600}}
  .badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:12px;font-weight:600}}
  .ok{{background:#e8f5e9;color:#2e7d32}}
  .breach{{background:#fce4e4;color:#c62828}}
  .stale{{background:#fff3e0;color:#e65100}}
  .no-data{{background:#f5f5f5;color:#888}}
  .breach-row td{{background:#fff8f8}}
  .stale-row td{{background:#fffdf0}}
  .det-row td{{padding:2px 8px 10px;font-size:13px;color:#666}}
  .breach-det{{color:#c62828}}
  .stale-det{{color:#e65100}}
  .hz{{font-size:12px;color:#888}}
  .footer{{text-align:center;padding:16px;font-size:12px;color:#aaa}}
</style>
</head>
<body>
<div class="hdr"><h1>GTM Metrics</h1><div class="ts">Generated {generated_at}</div></div>
<div class="bdy">
<table>
<thead><tr><th>Metric</th><th>Current</th><th>Target</th><th>Status</th><th>Horizon</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
</div>
<div class="footer">Chief of Staff · GTM Dashboard</div>
</body>
</html>"""


def main() -> None:
    snapshot_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _SNAPSHOT
    output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else _OUTPUT

    cfg_gtm = json.loads(_CONFIG.read_text()).get("gtm", {})

    if not snapshot_path.exists():
        print(f"Snapshot not found: {snapshot_path}", file=sys.stderr)
        print("Populate data/gtm_snapshot.json first (see doc 2 for daily-run wiring).", file=sys.stderr)
        sys.exit(1)

    snap = json.loads(snapshot_path.read_text())
    results = evaluate_metrics(
        leads_data=snap.get("leads"),
        demos_data=snap.get("demos"),
        sales_data=snap.get("sales"),
        onboarding_active=snap.get("onboarding_active", []),
        cancellations=snap.get("cancellations"),
        cfg=cfg_gtm,
    )
    html = render_html(results, snap.get("generated_at", "unknown"))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"Written to {output_path}")


if __name__ == "__main__":
    main()
