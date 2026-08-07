"""Format + send the weekly Fitness Scout email (HTML via Gmail SMTP)."""
import logging
import os
import smtplib
from email.mime.text import MIMEText
from html import escape

log = logging.getLogger(__name__)

GMAIL_USER = "trent@teambuildr.com"


def _teardown_html(td: dict) -> str:
    feats = "".join(f"<li>{escape(str(f))}</li>" for f in td.get("features", []))
    takeaways = "".join(
        f"<li><strong>{escape(t.get('tag',''))}</strong> — "
        f"{escape(t.get('feature',''))}: {escape(t.get('note',''))}</li>"
        for t in td.get("os_takeaways", [])
    )
    jt = td.get("jtbd", {}) or {}
    quoted = jt.get("quoted_line")
    quoted_html = f'<p style="margin:4px 0"><em>&ldquo;{escape(quoted)}&rdquo;</em></p>' if quoted else ""
    bucket = "Online coaching" if td.get("bucket") == "B" else "Brick-and-mortar"
    return f"""
    <div style="margin:0 0 32px 0;padding:0 0 24px 0;border-bottom:1px solid #ddd">
      <h2 style="margin:0 0 2px 0">{escape(td.get('name',''))}
        <span style="font-weight:normal;font-size:13px;color:#888"> · {bucket} ·
        <a href="{escape(td.get('url',''))}">{escape(td.get('url',''))}</a></span></h2>
      <p style="color:#555;margin:2px 0 12px 0">{escape(td.get('description',''))}</p>
      <p style="background:#fff8e1;padding:10px 12px;border-left:3px solid #f0b400;margin:0 0 14px 0">
        <strong>⚡ Standout wedge:</strong> {escape(td.get('standout',''))}</p>
      <p style="margin:2px 0"><strong>Segment:</strong> {escape(td.get('segment',''))}</p>
      <p style="margin:2px 0"><strong>Pricing:</strong> {escape(td.get('pricing',''))}</p>
      <p style="margin:2px 0"><strong>Traction:</strong> {escape(td.get('traction',''))}</p>
      <p style="margin:2px 0"><strong>Maturity:</strong> {escape(td.get('maturity',''))}</p>
      <p style="margin:12px 0 2px 0"><strong>Feature set:</strong></p>
      <ul style="margin:2px 0">{feats}</ul>
      <p style="margin:12px 0 2px 0"><strong>OS-tagged takeaways:</strong></p>
      <ul style="margin:2px 0">{takeaways}</ul>
      <div style="background:#f0f4ff;padding:10px 12px;border-left:3px solid #4361ee;margin:12px 0 0 0">
        <p style="margin:0 0 4px 0"><strong>JTBD:</strong> {escape(jt.get('platform_jtbd',''))}</p>
        {quoted_html}
        <p style="margin:4px 0 0 0"><strong>Verdict:</strong> {escape(jt.get('verdict',''))} —
          {escape(jt.get('note',''))}</p>
      </div>
    </div>"""


def format_email(teardowns: list, date_str: str) -> tuple:
    if not teardowns:
        body = (f'<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:680px">'
                f"<h1>Fitness Scout — {escape(date_str)}</h1>"
                f"<p>No new platforms surfaced this week. The discovery backlog is empty of "
                f"uncovered candidates — seed one with <code>python scout.py --seed &lt;url&gt;</code>.</p></div>")
        return (f"Fitness Scout — {date_str} (no new platforms)", body)

    names = " & ".join(td.get("name", "?") for td in teardowns)
    subject = f"Fitness Scout — {date_str}: {names}"
    inner = "".join(_teardown_html(td) for td in teardowns)
    body = (f'<div style="font-family:-apple-system,Segoe UI,Arial,sans-serif;max-width:680px">'
            f"<h1 style='margin:0 0 4px 0'>Fitness Scout</h1>"
            f"<p style='color:#888;margin:0 0 24px 0'>{escape(date_str)} · "
            f"{len(teardowns)} emerging platform teardown(s)</p>{inner}</div>")
    return subject, body


def send_email(subject: str, html_body: str, recipient: str = GMAIL_USER) -> bool:
    app_password = os.getenv("GMAIL_APP_PASSWORD", "")
    if not app_password:
        log.warning("GMAIL_APP_PASSWORD not set — skipping email")
        return False
    msg = MIMEText(html_body, "html")
    msg["Subject"] = subject
    msg["From"] = GMAIL_USER
    msg["To"] = recipient
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, app_password)
            server.sendmail(GMAIL_USER, [recipient], msg.as_string())
        log.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        log.error(f"Email send failed: {e}")
        return False
