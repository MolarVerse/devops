"""Tests for devops.changelog.fragments."""

from __future__ import annotations

import typing
from pathlib import Path

import pytest

from devops.changelog.fragments import (
    FragmentError,
    fragment_audience,
    load_fragments,
    parse_fragment_entries,
    parse_fragment_name,
    read_fragment_entries,
)
from devops.config import AudienceConfig, ChangelogConfig

if typing.TYPE_CHECKING:
    from collections.abc import Callable

CONFIG = ChangelogConfig()
USER = CONFIG.audience("user")
DEVELOPER = CONFIG.audience("developer")
SINGLE = ChangelogConfig(
    fragment_dir=Path("docs/changes"),
    audience_dirs=False,
    audiences=[
        AudienceConfig(
            name="changes",
            changelog=Path("CHANGELOG.md"),
            categories={"feature": "Features", "fix": "Fixes"},
        )
    ],
)


@pytest.fixture
def write(tmp_path: Path) -> Callable[[str, str], Path]:
    """Return a helper that writes a file below tmp_path.

    Parameters
    ----------
    tmp_path: Path
        The temporary repository root.

    Returns
    -------
    Callable[[str, str], Path]
        Writes text to a relative path and returns the absolute path.

    """

    def _write(relative: str, text: str) -> Path:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    return _write


@pytest.mark.parametrize(
    ("path", "audience"),
    [
        ("changes/user/bugfix.output.md", "user"),
        ("changes/developer/ci.workflow.md", "developer"),
        ("changes/user/.gitkeep", None),
        ("changes/developer/.gitkeep", None),
        ("changes/user/README.md", None),
        ("changes/README.md", None),
        ("changes/other/bugfix.output.md", None),
        ("changes/user/nested/bugfix.output.md", None),
        ("src/changes/user/bugfix.output.md", None),
        ("CHANGELOG.md", None),
    ],
)
def test_fragment_audience(path: str, audience: str | None) -> None:
    """Only <fragment_dir>/<audience>/<file>.md paths are fragments."""
    found = fragment_audience(path, CONFIG)
    assert (found.name if found else None) == audience


def test_fragment_audience_without_audience_dirs() -> None:
    """With audience_dirs = false fragments sit directly in fragment_dir."""
    assert fragment_audience("docs/changes/fix.output.md", SINGLE).name == "changes"
    assert fragment_audience("docs/changes/changes/fix.output.md", SINGLE) is None
    assert fragment_audience("docs/changes/.gitkeep", SINGLE) is None


def test_user_and_developer_names_select_distinct_sections() -> None:
    """The same category maps to the section of its audience."""
    assert parse_fragment_name("bugfix.trajectory.md", USER) == "Bug Fixes"
    assert parse_fragment_name("ci.changelog.md", DEVELOPER) == "CI"
    assert parse_fragment_name("enhancement.x.md", USER) == "New Features"
    assert parse_fragment_name("enhancement.x.md", DEVELOPER) == "Enhancements"
    assert parse_fragment_name("deprecations.x.md", USER) == "Deprecations"


def test_category_must_match_audience() -> None:
    """A developer category is not valid for the user audience."""
    with pytest.raises(FragmentError, match="invalid user category 'ci'"):
        parse_fragment_name("ci.workflow.md", USER)


def test_name_must_match_category_dot_slug() -> None:
    """The name is <category>.<slug>.md."""
    with pytest.raises(FragmentError, match="invalid fragment name"):
        parse_fragment_name("trajectory.user.bugfix.md", USER)


def test_name_error_explains_allowed_characters() -> None:
    """The error message lists the allowed characters."""
    with pytest.raises(FragmentError) as info:
        parse_fragment_name("bugfix.Slug-nAme.md", USER)

    assert info.value.message == (
        "invalid fragment name 'bugfix.Slug-nAme.md'; expected "
        "<category>.<slug>.md, where <category> uses only lowercase "
        "letters and <slug> starts with a lowercase letter or digit and "
        "uses only lowercase letters, digits, and hyphens"
    )


def test_configured_categories() -> None:
    """Categories come from the audience config."""
    audience = SINGLE.audiences[0]
    assert parse_fragment_name("fix.output.md", audience) == "Fixes"
    with pytest.raises(FragmentError, match="allowed: feature, fix"):
        parse_fragment_name("bugfix.output.md", audience)


@pytest.mark.parametrize(
    "text",
    ["Not a bullet.\n", "- First.\n\n- Second.\n", "-\n", "- \n", "\n"],
)
def test_entry_must_be_bullets(text: str) -> None:
    """A fragment holds only bullets without blank lines."""
    with pytest.raises(FragmentError, match="Markdown bullets"):
        parse_fragment_entries(text, "change.entry.md", 360)


def test_entries_are_read() -> None:
    """One or more bullets are returned without newlines."""
    assert parse_fragment_entries("- One entry.\n", "a.b.md", 360) == ["- One entry."]
    assert parse_fragment_entries("- First.\n- Second.\n", "a.b.md", 360) == [
        "- First.",
        "- Second.",
    ]


def test_entry_must_end_with_newline() -> None:
    """A missing final newline is an error."""
    with pytest.raises(FragmentError, match="must end with a newline"):
        parse_fragment_entries("- No trailing newline.", "a.b.md", 360)


def test_entry_length_limit() -> None:
    """A bullet longer than max_entry_length is an error."""
    line = "- " + "x" * 18
    assert parse_fragment_entries(line + "\n", "a.b.md", 20) == [line]
    with pytest.raises(FragmentError, match="20-character limit"):
        parse_fragment_entries(line + "x\n", "a.b.md", 20)


def test_read_fragment_entries(write: Callable[[str, str], Path]) -> None:
    """Fragment files are read with the given encoding."""
    path = write("changes/user/bugfix.umlaut.md", "- Fix the Ä output.\n")
    assert read_fragment_entries(path, 360) == ["- Fix the Ä output."]


def test_load_fragments_reads_both_audiences(
    tmp_path: Path, write: Callable[[str, str], Path]
) -> None:
    """Fragments of both audiences are loaded; placeholders are skipped."""
    write("changes/user/bugfix.trajectory.md", "- Fix trajectory output.\n")
    write(
        "changes/developer/test.parser.md",
        "- Cover parser edge cases.\n- Add regression fixture.\n",
    )
    write("changes/user/README.md", "ignored\n")
    write("changes/user/.gitkeep", "")
    write("changes/developer/.gitkeep", "")
    write("changes/README.md", "ignored\n")

    loaded = load_fragments(CONFIG, tmp_path)

    by_audience = {fragment.audience: fragment for fragment in loaded}
    assert len(loaded) == 2
    assert by_audience["user"].section == "Bug Fixes"
    assert by_audience["user"].entries == ("- Fix trajectory output.",)
    assert by_audience["user"].relative_path == "changes/user/bugfix.trajectory.md"
    assert by_audience["developer"].section == "Tests"
    assert by_audience["developer"].entries == (
        "- Cover parser edge cases.",
        "- Add regression fixture.",
    )


def test_load_fragments_without_directories(tmp_path: Path) -> None:
    """A missing fragment directory means no fragments."""
    assert load_fragments(CONFIG, tmp_path) == []


def test_load_fragments_rejects_invalid_files(
    tmp_path: Path, write: Callable[[str, str], Path]
) -> None:
    """An invalid fragment stops loading."""
    write("changes/user/ci.workflow.md", "- Wrong audience.\n")
    with pytest.raises(FragmentError, match="invalid user category"):
        load_fragments(CONFIG, tmp_path)


def test_load_fragments_single_audience(
    tmp_path: Path, write: Callable[[str, str], Path]
) -> None:
    """Without audience dirs the fragments are read from fragment_dir."""
    write("docs/changes/fix.output.md", "- Fix output.\n")
    write("docs/changes/.gitkeep", "")

    loaded = load_fragments(SINGLE, tmp_path)

    assert [(f.audience, f.section, f.relative_path) for f in loaded] == [
        ("changes", "Fixes", "docs/changes/fix.output.md")
    ]
