import re
from pathlib import Path
from datetime import date

MARKER = "<!-- AUTO-UPDATED: do not edit below this line -->"
MAX_ROUTINE = 5


def build_email_index(people_dir: str) -> dict[str, str]:
    """Scan *.md in people_dir; return {email_lower: filepath} for files with **Email:** fields."""
    index = {}
    for path in Path(people_dir).glob("*.md"):
        content = path.read_text()
        m = re.search(r'\*\*Email:\*\*\s*(\S+@\S+)', content, re.IGNORECASE)
        if m:
            index[m.group(1).lower()] = str(path)
    return index


def read_auto_section(filepath: str) -> dict:
    """Parse the machine-written section. Returns {"significant": [...], "routine": [...], "open_threads": [...]}."""
    content = Path(filepath).read_text()
    if MARKER not in content:
        return {"significant": [], "routine": [], "open_threads": []}

    auto = content.split(MARKER, 1)[1]

    def _extract_list(header: str, text: str) -> list[str]:
        pattern = rf'\*\*{re.escape(header)}\*\*(.*?)(?=\n\*\*|\Z)'
        m = re.search(pattern, text, re.DOTALL)
        if not m:
            return []
        lines = []
        for line in m.group(1).strip().splitlines():
            line = line.strip().lstrip("- ")
            if line and line != "(none)":
                lines.append(line)
        return lines

    return {
        "significant": _extract_list("Significant touchpoints:", auto),
        "routine": _extract_list(f"Recent touchpoints (last {MAX_ROUTINE}):", auto),
        "open_threads": _extract_list("Open threads:", auto),
    }


def write_auto_section(
    filepath: str,
    significant: list[str],
    routine: list[str],
    open_threads: list[str],
) -> None:
    """Replace everything from MARKER onward. The human section above is never touched."""
    content = Path(filepath).read_text()
    human_part = content.split(MARKER, 1)[0].rstrip()
    today = date.today().isoformat()

    lines = ["", MARKER, "## Activity", f"**Last seen:** {today}", ""]

    lines.append("**Significant touchpoints:**")
    for tp in significant:
        lines.append(f"- {tp}")
    if not significant:
        lines.append("- (none)")
    lines.append("")

    lines.append(f"**Recent touchpoints (last {MAX_ROUTINE}):**")
    for tp in routine[:MAX_ROUTINE]:
        lines.append(f"- {tp}")
    if not routine:
        lines.append("- (none)")
    lines.append("")

    lines.append("**Open threads:**")
    for t in open_threads:
        lines.append(f"- {t}")
    if not open_threads:
        lines.append("- (none)")
    lines.append("")

    Path(filepath).write_text(human_part + "\n" + "\n".join(lines))
