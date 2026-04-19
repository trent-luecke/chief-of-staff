import pytest
from pathlib import Path
from processors.people import build_email_index, read_auto_section, write_auto_section, MARKER


@pytest.fixture
def people_dir(tmp_path):
    (tmp_path / "luke-martin.md").write_text(
        "# Luke Martin\n\n**Email:** lmartin@teambuildr.com\n**Role:** Revenue team\n\n## Notes\n- test\n"
    )
    (tmp_path / "nicole-foley.md").write_text(
        "# Nicole Foley\n\n**Email:** nicole@teambuildr.com\n**Role:** Admin\n"
    )
    (tmp_path / "no-email.md").write_text(
        "# Someone\n\n**Role:** Unknown\n"
    )
    return str(tmp_path)


def test_build_email_index_finds_all_emails(people_dir):
    index = build_email_index(people_dir)
    assert "lmartin@teambuildr.com" in index
    assert "nicole@teambuildr.com" in index


def test_build_email_index_skips_files_without_email(people_dir):
    index = build_email_index(people_dir)
    assert len(index) == 2


def test_build_email_index_lowercases_emails(people_dir, tmp_path):
    (tmp_path / "test.md").write_text("# Test\n\n**Email:** TEST@EXAMPLE.COM\n")
    index = build_email_index(str(tmp_path))
    assert "test@example.com" in index


def test_write_auto_section_creates_marker_if_absent(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    write_auto_section(filepath, significant=[], routine=["2026-04-17 | calendar | \"Rev Team Sync\""], open_threads=[])
    content = Path(filepath).read_text()
    assert MARKER in content
    assert "Rev Team Sync" in content


def test_write_auto_section_preserves_human_content(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    original_content = Path(filepath).read_text()
    write_auto_section(filepath, significant=[], routine=[], open_threads=[])
    new_content = Path(filepath).read_text()
    # Human section above MARKER must be byte-for-byte identical
    original_human = original_content.split(MARKER)[0].rstrip()
    new_human = new_content.split(MARKER)[0].rstrip()
    assert original_human == new_human


def test_write_auto_section_replaces_previous_auto_section(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    write_auto_section(filepath, significant=[], routine=["2026-04-15 | email | \"Old thread\""], open_threads=[])
    write_auto_section(filepath, significant=[], routine=["2026-04-17 | calendar | \"New event\""], open_threads=[])
    content = Path(filepath).read_text()
    assert "New event" in content
    assert "Old thread" not in content
    assert content.count(MARKER) == 1


def test_write_auto_section_significant_touchpoints_persist(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    sig = ["2026-04-10 | email | \"Proposal\" | committed to sending by Friday"]
    write_auto_section(filepath, significant=sig, routine=[], open_threads=[])
    content = Path(filepath).read_text()
    assert "Proposal" in content
    assert "committed to sending by Friday" in content


def test_read_auto_section_returns_empty_dict_if_no_marker(people_dir):
    filepath = str(Path(people_dir) / "nicole-foley.md")
    result = read_auto_section(filepath)
    assert result == {"significant": [], "routine": [], "open_threads": []}


def test_read_auto_section_parses_written_data(people_dir):
    filepath = str(Path(people_dir) / "luke-martin.md")
    sig = ["2026-04-10 | email | \"Proposal\" | committed"]
    routine = ["2026-04-17 | calendar | \"Rev Team Sync\""]
    open_threads = ["\"Proposal\" — needs reply"]
    write_auto_section(filepath, significant=sig, routine=routine, open_threads=open_threads)

    result = read_auto_section(filepath)
    assert len(result["significant"]) == 1
    assert "Proposal" in result["significant"][0]
    assert len(result["routine"]) == 1
    assert len(result["open_threads"]) == 1
