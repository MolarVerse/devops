"""Tests for the devops_changelog CLI."""

from __future__ import annotations

import typing
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from devops.config import ChangelogConfig
from devops.scripts.update_changelog import changelog

if typing.TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

runner = CliRunner()
EMPTY = "## Next Release\n\n<!-- insertion marker -->\n"


@pytest.fixture(autouse=True)
def repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> typing.Iterator[Path]:
    """Run in a repository with empty changelogs and the default config.

    Parameters
    ----------
    tmp_path: Path
        The repository root.
    monkeypatch: pytest.MonkeyPatch
        Fixture used to change the working directory and environment.

    Yields
    ------
    Path
        The repository root.

    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    (tmp_path / "CHANGELOG.md").write_text(f"# Changelog\n\n{EMPTY}", encoding="utf-8")
    (tmp_path / "DEV-CHANGELOG.md").write_text(f"# Dev\n\n{EMPTY}", encoding="utf-8")
    with patch("devops.scripts.update_changelog.__GLOBAL_CONFIG__") as global_config:
        global_config.changelog = ChangelogConfig()
        global_config.file.encoding = "utf-8"
        yield tmp_path


def invoke(*arguments: str) -> Any:
    """Run the CLI and return the result."""
    return runner.invoke(changelog, list(arguments))


def _fragment(root: Path, relative: str, text: str) -> Path:
    path = root / "changes" / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_help_lists_all_commands() -> None:
    """Every changelog command is registered."""
    result = invoke("--help")
    assert result.exit_code == 0
    for command in ("check-pr", "check-release", "stamp", "notes"):
        assert command in result.stdout


def test_check_pr_passes_arguments() -> None:
    """check-pr passes refs, split labels and the config."""
    with patch(
        "devops.scripts.update_changelog.check_pull_request", return_value="ok"
    ) as check:
        result = invoke("check-pr", "base", "head", "--label", "a, b", "--label", "c")
    assert result.exit_code == 0, result.output
    assert result.stdout == "ok\n"
    arguments = check.call_args.args
    assert arguments[:2] == ("base", "head")
    assert arguments[2] == ChangelogConfig()
    assert arguments[4] == ["a", "b", "c"]


def test_check_pr_head_defaults_to_head() -> None:
    """The head ref defaults to HEAD."""
    with patch(
        "devops.scripts.update_changelog.check_pull_request", return_value="ok"
    ) as check:
        invoke("check-pr", "base")
    assert check.call_args.args[1] == "HEAD"


def test_check_pr_skip_label() -> None:
    """The skip label passes without a Git repository."""
    result = invoke("check-pr", "base", "--label", "skip-changelog")
    assert result.exit_code == 0
    assert "skip-changelog label is set" in result.stdout


def test_check_pr_failure_exits_with_one() -> None:
    """A Git error exits 1 with the message on stderr."""
    result = invoke("check-pr", "missing-ref")
    assert result.exit_code == 1
    assert result.stderr


def test_check_release(repository: Path) -> None:
    """check-release needs at least one entry."""
    result = invoke("check-release")
    assert result.exit_code == 1
    assert "at least one changelog entry" in result.stderr

    _fragment(repository, "user/bugfix.output.md", "- Fix output.\n")
    result = invoke("check-release")
    assert result.exit_code == 0
    assert "contains changelog entries" in result.stdout


def test_stamp_and_notes(repository: Path) -> None:
    """Stamp consumes the fragments; notes prints the stamped release."""
    fragment = _fragment(repository, "user/bugfix.output.md", "- Fix output.\n")
    _fragment(repository, "user/.gitkeep", "")

    result = invoke("stamp", "v1.1.0")
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "stamped CHANGELOG.md for v1.1.0; consumed 1 changelog fragment(s)\n"
    )
    assert not fragment.exists()
    assert (repository / "changes/user/.gitkeep").is_file()
    text = (repository / "CHANGELOG.md").read_text(encoding="utf-8")
    assert "## [v1.1.0](https://github.com/owner/repo/releases/tag/v1.1.0)" in text

    result = invoke("notes", "v1.1.0")
    assert result.exit_code == 0
    assert result.stdout == "### Bug Fixes\n\n- Fix output.\n"


def test_stamp_and_notes_errors_exit_with_one() -> None:
    """An empty release and an unknown version exit 1."""
    for arguments in (("stamp", "v1.1.0"), ("notes", "v9.9.9")):
        result = invoke(*arguments)
        assert result.exit_code == 1
        assert result.stderr
