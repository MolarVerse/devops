"""Tests for devops.changelog.stamp."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

import pytest

from devops.changelog.stamp import (
    check_release,
    has_release_notes,
    parse_subsections,
    prepared_release,
    release_notes,
    release_section,
    render_sections,
    split_next_release,
    stamp_lines,
    stamp_release,
)
from devops.config import AudienceConfig, ChangelogConfig
from devops.files.update_changelog import DevOpsChangelogError

CONFIG = ChangelogConfig()
URL = "https://github.com/MolarVerse/PQ"
TODAY = datetime.now(tz=UTC).date().isoformat()
EMPTY = "## Next Release\n\n<!-- insertion marker -->\n"
OLD = "## [v1.0.0](release-url) - 2025-01-01\n"


def _write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _changelogs(root: Path, user: str = "", developer: str = "") -> tuple[Path, Path]:
    return (
        _write(root, "CHANGELOG.md", f"# Changelog\n\n{user or EMPTY}{OLD}"),
        _write(
            root,
            "DEV-CHANGELOG.md",
            f"# Developer Changelog\n\n{developer or EMPTY}{OLD}",
        ),
    )


def _stamp(root: Path, version: str = "v1.1.0") -> None:
    stamp_release(version, CONFIG, root, repo_url=URL)


def test_release_notes_require_a_bullet() -> None:
    """Text without a bullet is no release note."""
    assert not has_release_notes(["", "### Bug Fixes", "", "No release notes yet."])
    assert has_release_notes(["", "### Bug Fixes", "", "- Fix trajectory output."])


def test_split_next_release_requires_heading() -> None:
    """A changelog without ## Next Release is an error."""
    with pytest.raises(DevOpsChangelogError, match=r"'## Next Release' in X\.md"):
        split_next_release(["# Changelog"], "X.md")


def test_stamp_keeps_empty_next_release_and_history() -> None:
    """The release goes below the marker and above the history."""
    lines = [
        "# Changelog",
        "",
        "## Next Release",
        "",
        "### Bug Fixes",
        "",
        "- Fix trajectory output.",
        "",
        "<!-- insertion marker -->",
        "## [v1.0.0](release-url) - 2025-01-01",
    ]
    head, body, tail = split_next_release(lines, "CHANGELOG.md")
    stamped = stamp_lines(head, body, tail, "## [v1.1.0](url) - 2026-01-02")

    assert stamped == [
        "# Changelog",
        "",
        "## Next Release",
        "",
        "<!-- insertion marker -->",
        "## [v1.1.0](url) - 2026-01-02",
        "",
        "### Bug Fixes",
        "",
        "- Fix trajectory output.",
        "",
        "## [v1.0.0](release-url) - 2025-01-01",
    ]


def test_sections_render_in_order_unknown_last() -> None:
    """Configured order first, then unknown sections, preamble kept."""
    body = [
        "- Loose entry.",
        "### Custom",
        "- Custom entry.",
        "### Tests",
        "",
        "- Test entry.",
        "### Breaking Changes",
        "- Break.",
    ]
    order = CONFIG.audience("developer").order
    rendered = render_sections(parse_subsections(body, order), order)
    assert rendered == [
        "- Loose entry.",
        "",
        "### Breaking Changes",
        "",
        "- Break.",
        "",
        "### Tests",
        "",
        "- Test entry.",
        "",
        "### Custom",
        "",
        "- Custom entry.",
        "",
    ]


def test_release_routes_fragments_and_preserves_unreleased_entries(
    tmp_path: Path,
) -> None:
    """Fragments go to their audience; existing entries stay; refresh works."""
    user, dev = _changelogs(
        tmp_path,
        "## Next Release\n\n### Bug Fixes\n\n- Fix trajectory output.\n\n"
        "<!-- insertion marker -->\n",
        "## Next Release\n\n### Internal\n\n- Existing developer note.\n\n"
        "<!-- insertion marker -->\n",
    )
    user_fragment = _write(
        tmp_path, "changes/user/enhancement.trajectory.md", "- Add step metadata.\n"
    )
    dev_fragment = _write(
        tmp_path,
        "changes/developer/test.parser.md",
        "- Cover fragment parsing.\n- Add a regression fixture.\n",
    )

    result = stamp_release("v1.1.0", CONFIG, tmp_path, repo_url=URL)

    assert result.stamped == [user, dev]
    assert result.consumed == [user_fragment, dev_fragment]
    user_text = user.read_text(encoding="utf-8")
    dev_text = dev.read_text(encoding="utf-8")
    assert user_text == (
        "# Changelog\n\n## Next Release\n\n<!-- insertion marker -->\n"
        f"## [v1.1.0]({URL}/releases/tag/v1.1.0) - {TODAY}\n\n"
        "### New Features\n\n- Add step metadata.\n\n"
        "### Bug Fixes\n\n- Fix trajectory output.\n\n"
        f"{OLD}"
    )
    assert "- Existing developer note." in dev_text
    assert "- Cover fragment parsing.\n- Add a regression fixture." in dev_text
    assert "step metadata" not in dev_text
    assert not user_fragment.exists()
    assert not dev_fragment.exists()

    dev_fragment.write_text("- Include a later correction.\n", encoding="utf-8")
    _stamp(tmp_path)
    updated = dev.read_text(encoding="utf-8")
    assert updated.count("## [v1.1.0]") == 1
    assert updated.count("- Existing developer note.") == 1
    assert updated.count("- Cover fragment parsing.") == 1
    assert "- Include a later correction." in updated
    assert OLD in updated
    assert user.read_text(encoding="utf-8") == user_text
    assert not dev_fragment.exists()

    _stamp(tmp_path)
    assert dev.read_text(encoding="utf-8") == updated


@pytest.mark.parametrize("failure", ["write", "unlink"])
def test_retry_after_interrupted_write_or_cleanup_keeps_each_note_once(
    tmp_path: Path, failure: str
) -> None:
    """A re-run after a crash neither loses nor repeats entries."""
    paths = _changelogs(tmp_path)
    fragments = [
        _write(tmp_path, f"changes/{name}/bugfix.correction.md", f"- Fix {name}.\n")
        for name in ("user", "developer")
    ]
    write_text = Path.write_text
    unlink = Path.unlink

    def interrupt_write(path: Path, *args: object, **kwargs: object) -> int:
        if path == paths[1]:
            msg = "simulated interrupted write"
            raise OSError(msg)
        return write_text(path, *args, **kwargs)

    def interrupt_unlink(path: Path, *args: object, **kwargs: object) -> None:
        if path == fragments[0]:
            msg = "simulated interrupted cleanup"
            raise OSError(msg)
        unlink(path, *args, **kwargs)

    patch = (
        mock.patch.object(Path, "write_text", interrupt_write)
        if failure == "write"
        else mock.patch.object(Path, "unlink", interrupt_unlink)
    )
    with patch, pytest.raises(OSError, match="simulated interrupted"):
        _stamp(tmp_path)
    _stamp(tmp_path)

    for path, name in zip(paths, ("user", "developer"), strict=True):
        text = path.read_text(encoding="utf-8")
        assert text.count(f"- Fix {name}.") == 1
        assert text.count("## [v1.1.0]") == 1
    assert not any(fragment.exists() for fragment in fragments)


def test_release_keeps_the_placeholder_files(tmp_path: Path) -> None:
    """.gitkeep files survive a release."""
    _changelogs(tmp_path)
    for name in ("user", "developer"):
        _write(tmp_path, f"changes/{name}/.gitkeep", "")
    fragment = _write(tmp_path, "changes/user/bugfix.output.md", "- Fix output.\n")

    _stamp(tmp_path)

    assert not fragment.exists()
    assert (tmp_path / "changes/user/.gitkeep").is_file()
    assert (tmp_path / "changes/developer/.gitkeep").is_file()


def test_developer_only_release_leaves_user_changelog_unchanged(
    tmp_path: Path,
) -> None:
    """Only changelogs with entries are stamped."""
    user, dev = _changelogs(tmp_path)
    user_text = user.read_text(encoding="utf-8")
    _write(tmp_path, "changes/developer/ci.workflow.md", "- Enforce audiences.\n")

    check_release(CONFIG, tmp_path)
    result = stamp_release("v1.1.0", CONFIG, tmp_path, repo_url=URL)

    assert result.stamped == [dev]
    assert user.read_text(encoding="utf-8") == user_text
    assert "- Enforce audiences." in dev.read_text(encoding="utf-8")


def test_release_without_entries_fails(tmp_path: Path) -> None:
    """A release needs at least one entry in any changelog."""
    user, _ = _changelogs(tmp_path)
    before = user.read_text(encoding="utf-8")
    for run in (lambda: check_release(CONFIG, tmp_path), lambda: _stamp(tmp_path)):
        with pytest.raises(DevOpsChangelogError, match="at least one changelog entry"):
            run()
    assert user.read_text(encoding="utf-8") == before


def test_release_rejects_a_fragment_already_in_an_earlier_release(
    tmp_path: Path,
) -> None:
    """A fragment repeating a released bullet stops the release."""
    user, _ = _changelogs(
        tmp_path,
        EMPTY + "## [v1.0.1](release-url) - 2025-01-02\n\n"
        "### Bug Fixes\n\n- Fix MACE startup.\n\n",
    )
    before = user.read_text(encoding="utf-8")
    fragment = _write(tmp_path, "changes/user/bugfix.mace.md", "- Fix MACE startup.\n")

    for run in (lambda: check_release(CONFIG, tmp_path), lambda: _stamp(tmp_path)):
        with pytest.raises(
            DevOpsChangelogError, match=r"changes/user/bugfix\.mace\.md"
        ):
            run()

    assert user.read_text(encoding="utf-8") == before
    assert fragment.exists()


def test_refresh_only_the_latest_release(tmp_path: Path) -> None:
    """An older version cannot be stamped again."""
    _changelogs(
        tmp_path,
        EMPTY + "## [v1.1.0](url) - 2025-02-01\n\n- New.\n\n",
    )
    _write(tmp_path, "changes/user/bugfix.output.md", "- Fix output.\n")
    with pytest.raises(DevOpsChangelogError, match="not the latest release"):
        _stamp(tmp_path, "v1.0.0")


def test_prepared_release_for_a_new_version() -> None:
    """A new version leaves the history alone."""
    tail = ["<!-- insertion marker -->", "## [v1.0.0](url) - 2025-01-01"]
    assert prepared_release(tail, "v1.1.0") == (None, [], tail)


def test_missing_changelog(tmp_path: Path) -> None:
    """Every audience needs its changelog file."""
    _write(tmp_path, "CHANGELOG.md", f"# Changelog\n\n{EMPTY}")
    with pytest.raises(DevOpsChangelogError, match=r"DEV-CHANGELOG\.md not found"):
        check_release(CONFIG, tmp_path)


def test_body_without_fragments_is_kept_verbatim(tmp_path: Path) -> None:
    """Without fragments the Next Release body keeps its own layout."""
    body = "### Features\n\n#### CPP Rules\n\n- Add a rule.\n\n#### AST\n\n- Fix.\n"
    config = ChangelogConfig(audiences=[CONFIG.audience("user")])
    user = _write(tmp_path, "CHANGELOG.md", f"# Changelog\n\n## Next Release\n\n{body}")

    stamp_release("1.4.0", config, tmp_path, repo_url=URL)

    assert user.read_text(encoding="utf-8") == (
        "# Changelog\n\n## Next Release\n\n<!-- insertion marker -->\n"
        f"## [1.4.0]({URL}/releases/tag/1.4.0) - {TODAY}\n\n{body}"
    )


def test_single_audience_without_folders(tmp_path: Path) -> None:
    """One changelog, fragments directly in the fragment directory."""
    config = ChangelogConfig(
        fragment_dir=Path("changes"),
        audience_dirs=False,
        audiences=[
            AudienceConfig(
                name="changes",
                changelog=Path("CHANGELOG.md"),
                categories={"feature": "Features", "fix": "Fixes"},
            )
        ],
    )
    user = _write(tmp_path, "CHANGELOG.md", f"# Changelog\n\n{EMPTY}")
    _write(tmp_path, "changes/fix.output.md", "- Fix output.\n")
    _write(tmp_path, "changes/feature.input.md", "- Add input.\n")
    _write(tmp_path, "changes/.gitkeep", "")

    stamp_release("2.0.0", config, tmp_path, repo_url=URL)

    assert user.read_text(encoding="utf-8").endswith(
        "### Features\n\n- Add input.\n\n### Fixes\n\n- Fix output.\n"
    )
    assert [path.name for path in (tmp_path / "changes").iterdir()] == [".gitkeep"]


def test_repo_url_defaults_to_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without repo_url the GitHub repository comes from the environment."""
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    user, _ = _changelogs(tmp_path)
    _write(tmp_path, "changes/user/bugfix.output.md", "- Fix output.\n")

    stamp_release("v1.1.0", CONFIG, tmp_path)

    assert "(https://github.com/owner/repo/releases/tag/v1.1.0)" in user.read_text(
        encoding="utf-8"
    )


def test_release_section_returns_only_the_requested_release() -> None:
    """Only the body of the requested version is returned."""
    lines = [
        "# Changelog",
        "<!-- insertion marker -->",
        "## [v1.1.0](url) - 2026-01-02",
        "",
        "### Bug Fixes",
        "",
        "- Fix trajectory output.",
        "",
        "## [v1.0.0](url) - 2026-01-01",
        "",
        "- Old entry.",
    ]
    assert release_section(lines, "v1.1.0") == [
        "### Bug Fixes",
        "",
        "- Fix trajectory output.",
    ]
    assert release_section(lines, "v2.0.0") == []


def test_release_notes_combine_both_audiences(tmp_path: Path) -> None:
    """The developer notes get their own heading."""
    release = "<!-- insertion marker -->\n## [v1.1.0](url) - 2026-01-02\n\n"
    _write(
        tmp_path,
        "CHANGELOG.md",
        f"# Changelog\n\n## Next Release\n\n{release}### Bug Fixes\n\n- Fix.\n",
    )
    _write(
        tmp_path,
        "DEV-CHANGELOG.md",
        f"# Dev\n\n## Next Release\n\n{release}### CI\n\n- Add a check.\n",
    )

    assert release_notes("v1.1.0", CONFIG, tmp_path) == (
        "### Bug Fixes\n\n- Fix.\n\n## Developer Changes\n\n### CI\n\n- Add a check."
    )
    with pytest.raises(DevOpsChangelogError, match="no changelog entries"):
        release_notes("v9.9.9", CONFIG, tmp_path)


def test_release_notes_of_one_audience(tmp_path: Path) -> None:
    """A missing or unstamped changelog is skipped."""
    release = "<!-- insertion marker -->\n## [v1.1.0](url) - 2026-01-02\n\n"
    _write(tmp_path, "DEV-CHANGELOG.md", f"# Dev\n\n{release}### CI\n\n- Check.\n")
    assert release_notes("v1.1.0", CONFIG, tmp_path) == (
        "## Developer Changes\n\n### CI\n\n- Check."
    )
