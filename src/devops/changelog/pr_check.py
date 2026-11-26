"""Require valid changelog fragments in a regular pull request."""

from __future__ import annotations

import subprocess
import typing
from pathlib import PurePosixPath

from devops.files.update_changelog import DevOpsChangelogError

from .fragments import (
    FragmentError,
    audience_dir,
    fragment_audience,
    parse_fragment_name,
    read_fragment_entries,
)

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from devops.config import ChangelogConfig

EDITABLE_STATUSES = frozenset({"A", "M"})


def changed_files(base: str, head: str, root: Path) -> list[tuple[str, str]]:
    """Return status and path of every file changed after the merge base.

    Parameters
    ----------
    base: str
        The base ref of the pull request.
    head: str
        The head ref of the pull request.
    root: Path
        The repository root.

    Returns
    -------
    list[tuple[str, str]]
        ``(status, path)`` pairs as printed by ``git diff --name-status``.

    Raises
    ------
    DevOpsChangelogError
        If ``git diff`` fails.

    """
    result = subprocess.run(  # noqa: S603 - no shell, refs are passed as arguments
        ["git", "diff", "--name-status", "--no-renames", f"{base}...{head}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise DevOpsChangelogError(result.stderr.strip() or "git diff failed")

    changes = []
    for line in result.stdout.splitlines():
        status, path = line.split("\t", maxsplit=1)
        changes.append((status, path))
    return changes


def validate_pr_changes(
    changes: Iterable[tuple[str, str]],
    config: ChangelogConfig,
    root: Path,
    encoding: str = "utf-8",
) -> list[str]:
    """Return the changelog errors of a regular pull request.

    A pull request must add or update at least one fragment, must not
    delete fragments and must not edit a changelog directly.

    Parameters
    ----------
    changes: Iterable[tuple[str, str]]
        ``(status, path)`` pairs of the pull request.
    config: ChangelogConfig
        The changelog configuration.
    root: Path
        The repository root with the head checked out.
    encoding: str
        The file encoding.

    Returns
    -------
    list[str]
        The errors; empty if the pull request is fine.

    """
    changes = list(changes)
    errors = []

    protected = {path.as_posix() for path in config.changelogs}
    direct_edits = sorted(path for _, path in changes if path in protected)
    if direct_edits:
        errors.append(
            "regular pull requests must not edit "
            + " or ".join(direct_edits)
            + " directly"
        )

    fragment_changes = [
        (status, path)
        for status, path in changes
        if fragment_audience(path, config) is not None
    ]
    if not fragment_changes:
        directories = " or ".join(
            f"{audience_dir(audience, config)}/" for audience in config.audiences
        )
        errors.append(
            "regular pull requests must add or update at least one "
            f"changelog fragment under {directories}"
        )

    forbidden = [
        f"{status} {path}"
        for status, path in fragment_changes
        if status not in EDITABLE_STATUSES
    ]
    if forbidden:
        errors.append(
            "regular pull requests must not delete or replace changelog "
            "fragments: " + ", ".join(forbidden)
        )

    for status, path in fragment_changes:
        if status not in EDITABLE_STATUSES:
            continue
        audience = fragment_audience(path, config)
        try:
            parse_fragment_name(PurePosixPath(path).name, audience)
            read_fragment_entries(root / path, config.max_entry_length, encoding)
        except FragmentError as error:
            errors.append(error.message)
        except OSError as error:
            errors.append(str(error))

    return errors


def check_pull_request(
    base: str,
    head: str,
    config: ChangelogConfig,
    root: Path,
    labels: Iterable[str] = (),
    encoding: str = "utf-8",
) -> str:
    """Check the changelog fragments of a pull request.

    Parameters
    ----------
    base: str
        The base ref of the pull request.
    head: str
        The head ref of the pull request.
    config: ChangelogConfig
        The changelog configuration.
    root: Path
        The repository root with the head checked out.
    labels: Iterable[str]
        The labels of the pull request.
    encoding: str
        The file encoding.

    Returns
    -------
    str
        A message describing the passed check.

    Raises
    ------
    DevOpsChangelogError
        If the pull request has no valid fragment or breaks a rule.

    """
    if config.skip_label and config.skip_label in labels:
        return f"The {config.skip_label} label is set, no fragment is required."

    errors = validate_pr_changes(
        changed_files(base, head, root), config, root, encoding
    )
    if errors:
        lines = [f"- {error}" for error in errors]
        if config.skip_label:
            lines.append(
                "- if this pull request needs no entry, "
                f"ask for the {config.skip_label} label"
            )
        raise DevOpsChangelogError("\n".join(lines))

    return "pull request contains valid changelog fragments"
