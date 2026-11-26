"""Tests for devops.changelog.pr_check."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from devops.changelog.pr_check import (
    changed_files,
    check_pull_request,
    validate_pr_changes,
)
from devops.config import AudienceConfig, ChangelogConfig
from devops.files.update_changelog import DevOpsChangelogError

CONFIG = ChangelogConfig()


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_accepts_one_valid_fragment(tmp_path: Path) -> None:
    """One valid added fragment passes."""
    _write(tmp_path, "changes/developer/ci.workflow.md", "- Enforce audiences.\n")
    changes = [("A", "changes/developer/ci.workflow.md")]
    assert validate_pr_changes(changes, CONFIG, tmp_path) == []


def test_requires_at_least_one_fragment(tmp_path: Path) -> None:
    """A pull request without fragment fails and names the directories."""
    errors = validate_pr_changes([("M", "src/a.py")], CONFIG, tmp_path)
    assert errors == [
        (
            "regular pull requests must add or update at least one changelog "
            "fragment under changes/user/ or changes/developer/"
        )
    ]


def test_placeholder_is_not_a_fragment(tmp_path: Path) -> None:
    """Adding only a .gitkeep is not a fragment."""
    errors = validate_pr_changes([("A", "changes/user/.gitkeep")], CONFIG, tmp_path)
    assert any("at least one" in error for error in errors)


def test_accepts_multiple_fragments(tmp_path: Path) -> None:
    """Fragments of both audiences pass together."""
    _write(tmp_path, "changes/user/bugfix.first.md", "- Fix the output.\n")
    _write(tmp_path, "changes/developer/test.second.md", "- Cover the output.\n")
    changes = [
        ("A", "changes/user/bugfix.first.md"),
        ("A", "changes/developer/test.second.md"),
    ]
    assert validate_pr_changes(changes, CONFIG, tmp_path) == []


def test_accepts_fragment_with_multiple_bullets(tmp_path: Path) -> None:
    """A fragment may hold several bullets."""
    _write(tmp_path, "changes/user/enhancement.batch.md", "- First.\n- Second.\n")
    changes = [("A", "changes/user/enhancement.batch.md")]
    assert validate_pr_changes(changes, CONFIG, tmp_path) == []


def test_validates_every_changed_fragment(tmp_path: Path) -> None:
    """Every added fragment is validated, not only the first."""
    _write(tmp_path, "changes/user/bugfix.first.md", "- Fix the output.\n")
    _write(tmp_path, "changes/user/ci.second.md", "- Cover the output.\n")
    changes = [
        ("A", "changes/user/bugfix.first.md"),
        ("A", "changes/user/ci.second.md"),
    ]
    errors = validate_pr_changes(changes, CONFIG, tmp_path)
    assert any("invalid user category 'ci'" in error for error in errors)


def test_invalid_name_error_explains_allowed_characters(tmp_path: Path) -> None:
    """A bad slug gives one error with the allowed characters."""
    _write(tmp_path, "changes/user/bugfix.Slug-nAme.md", "- Fix the output.\n")
    errors = validate_pr_changes(
        [("A", "changes/user/bugfix.Slug-nAme.md")], CONFIG, tmp_path
    )
    assert len(errors) == 1
    assert "uses only lowercase letters, digits, and hyphens" in errors[0]


def test_invalid_contents(tmp_path: Path) -> None:
    """Fragment contents are validated."""
    _write(tmp_path, "changes/user/bugfix.first.md", "Not a bullet\n")
    errors = validate_pr_changes(
        [("A", "changes/user/bugfix.first.md")], CONFIG, tmp_path
    )
    assert any("Markdown bullets" in error for error in errors)


def test_missing_file_is_an_error(tmp_path: Path) -> None:
    """A fragment listed by git but missing on disk is reported."""
    errors = validate_pr_changes(
        [("A", "changes/user/bugfix.first.md")], CONFIG, tmp_path
    )
    assert len(errors) == 1
    assert "bugfix.first.md" in errors[0]


@pytest.mark.parametrize("changelog", ["CHANGELOG.md", "DEV-CHANGELOG.md"])
def test_rejects_direct_changelog_edits(tmp_path: Path, changelog: str) -> None:
    """Changelogs of all audiences are protected."""
    _write(tmp_path, "changes/developer/ci.workflow.md", "- Enforce audiences.\n")
    changes = [("M", changelog), ("A", "changes/developer/ci.workflow.md")]
    errors = validate_pr_changes(changes, CONFIG, tmp_path)
    assert errors == [f"regular pull requests must not edit {changelog} directly"]


def test_accepts_modified_existing_fragments(tmp_path: Path) -> None:
    """Appending a bullet to an unreleased fragment passes."""
    _write(
        tmp_path,
        "changes/developer/internal.existing.md",
        "- Correct an entry.\n- Add a second point.\n",
    )
    changes = [("M", "changes/developer/internal.existing.md")]
    assert validate_pr_changes(changes, CONFIG, tmp_path) == []


@pytest.mark.parametrize("status", ["D", "T"])
def test_rejects_deleted_or_replaced_fragments(tmp_path: Path, status: str) -> None:
    """Regular pull requests do not delete or replace fragments."""
    errors = validate_pr_changes(
        [(status, "changes/developer/internal.existing.md")], CONFIG, tmp_path
    )
    assert errors == [
        (
            "regular pull requests must not delete or replace changelog fragments: "
            f"{status} changes/developer/internal.existing.md"
        )
    ]


def test_single_audience_config(tmp_path: Path) -> None:
    """A repository with one changelog and no audience folders."""
    config = ChangelogConfig(
        fragment_dir=Path(".changes"),
        audience_dirs=False,
        audiences=[
            AudienceConfig(
                name="changes",
                changelog=Path("docs/CHANGELOG.md"),
                categories={"fix": "Fixes"},
            )
        ],
    )
    _write(tmp_path, ".changes/fix.output.md", "- Fix output.\n")
    assert (
        validate_pr_changes([("A", ".changes/fix.output.md")], config, tmp_path) == []
    )

    errors = validate_pr_changes([("M", "docs/CHANGELOG.md")], config, tmp_path)
    assert errors[0] == (
        "regular pull requests must not edit docs/CHANGELOG.md directly"
    )
    assert errors[1].endswith("changelog fragment under .changes/")


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(  # noqa: S603 - no shell, test git commands
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


@pytest.fixture
def repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return a Git repository with a ``base`` commit and no user config.

    Parameters
    ----------
    tmp_path: Path
        The repository directory.
    monkeypatch: pytest.MonkeyPatch
        Fixture used to isolate Git from the user config.

    Returns
    -------
    Path
        The repository root.

    """
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")

    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "dev")
    _write(root, "CHANGELOG.md", "# Changelog\n\n## Next Release\n")
    _write(root, "changes/user/.gitkeep", "")
    _write(root, "changes/developer/.gitkeep", "")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "tag", "base")
    return root


def test_changed_files(repository: Path) -> None:
    """Changes since the merge base are listed with their status."""
    _write(repository, "changes/user/bugfix.output.md", "- Fix output.\n")
    _write(repository, "CHANGELOG.md", "# Changelog\n\n## Next Release\n\n- x\n")
    (repository / "changes/user/.gitkeep").unlink()
    _git(repository, "add", "-A")
    _git(repository, "commit", "-q", "-m", "change")

    assert sorted(changed_files("base", "HEAD", repository)) == [
        ("A", "changes/user/bugfix.output.md"),
        ("D", "changes/user/.gitkeep"),
        ("M", "CHANGELOG.md"),
    ]


def test_changed_files_bad_ref(repository: Path) -> None:
    """A Git error is raised, not read as "no changes"."""
    with pytest.raises(DevOpsChangelogError, match="missing"):
        changed_files("missing", "HEAD", repository)


def test_check_pull_request(repository: Path) -> None:
    """A pull request with a fragment passes the full check."""
    _write(repository, "changes/developer/ci.check.md", "- Check fragments.\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "fragment")

    message = check_pull_request("base", "HEAD", CONFIG, repository)
    assert message == "pull request contains valid changelog fragments"


def test_check_pull_request_fails_with_hint(repository: Path) -> None:
    """A failing check lists every error and the skip label hint."""
    _write(repository, "src/a.py", "print()\n")
    _git(repository, "add", ".")
    _git(repository, "commit", "-q", "-m", "code")

    with pytest.raises(DevOpsChangelogError) as info:
        check_pull_request("base", "HEAD", CONFIG, repository, ["bug"])

    lines = info.value.message.splitlines()
    assert lines[0].startswith("- regular pull requests must add or update")
    assert lines[-1] == (
        "- if this pull request needs no entry, ask for the skip-changelog label"
    )


def test_skip_label(tmp_path: Path) -> None:
    """The skip label passes without running Git."""
    message = check_pull_request(
        "missing", "HEAD", CONFIG, tmp_path, ["bug", "skip-changelog"]
    )
    assert "skip-changelog label is set" in message


def test_empty_skip_label_disables_skipping(repository: Path) -> None:
    """With skip_label = "" no label skips the check and no hint is given."""
    config = ChangelogConfig(skip_label="")
    with pytest.raises(DevOpsChangelogError) as info:
        check_pull_request("base", "HEAD", config, repository, [""])
    assert "skip" not in info.value.message
