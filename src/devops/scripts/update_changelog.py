"""Scripts for the changelog: release stamps and changelog fragments."""

import sys
from pathlib import Path
from typing import Annotated

import typer

from devops import __GLOBAL_CONFIG__
from devops.changelog import (
    check_pull_request,
    check_release,
    release_notes,
    stamp_release,
)
from devops.files.update_changelog import DevOpsChangelogError
from devops.files.update_changelog import update_changelog as update_changelog_func
from devops.utils import mstd_print

update_changelog = typer.Typer()
update_changelogs = typer.Typer()
changelog = typer.Typer(
    help="Changelog fragment commands: check a pull request, stamp a release."
)

# Alias for tests and backwards compatibility
app = update_changelog


@update_changelog.command()
def _update_changelog(version: str, changelog_path: str | None = None) -> None:
    """Update the changelog file with a new version entry.

    Parameters
    ----------
    version: str
        The new version to add to the changelog.
    changelog_path: str | None
        The path to the changelog file. If None, it defaults
        to the default_changelog_path from the configuration file.
    """
    if changelog_path is None:
        changelog_path = __GLOBAL_CONFIG__.file.default_changelog_path
    else:
        changelog_path = Path(changelog_path)
    try:
        update_changelog_func(version, changelog_path)
        mstd_print(f"✅ CHANGELOG.md updated for version {version}")
    except DevOpsChangelogError as e:
        mstd_print(f"❌ Error updating changelog: {e}")
        sys.exit(1)


@update_changelogs.command()
def _update_changelogs(version: str, changelog_paths: list[str] | None = None) -> None:
    """Update multiple changelog files with a new version entry.

    Parameters
    ----------
    version: str
        The new version to add to the changelogs.
    changelog_paths: list[str] | None
        The list of paths to the changelog files. If None, it defaults
        to the changelog_paths from the configuration file.
    """
    if changelog_paths is None:
        changelog_paths = __GLOBAL_CONFIG__.file.changelog_paths
    else:
        changelog_paths = [Path(p) for p in changelog_paths]

    failed_updates = []

    for changelog_path in changelog_paths:
        try:
            update_changelog_func(version, changelog_path)
            mstd_print(f"✅ {changelog_path} updated for version {version}")
        except DevOpsChangelogError as e:
            mstd_print(f"❌ Error updating {changelog_path}: {e}")
            failed_updates.append(changelog_path)

    if failed_updates:
        sys.exit(1)


def _fail(error: DevOpsChangelogError) -> typer.Exit:
    """Print a changelog error to stderr and return the exit to raise.

    Parameters
    ----------
    error: DevOpsChangelogError
        The error to report.

    Returns
    -------
    typer.Exit
        An exit with code 1.

    """
    typer.echo(error.message, err=True)
    return typer.Exit(code=1)


def _split_labels(labels: list[str] | None) -> list[str]:
    """Split comma separated label options.

    Parameters
    ----------
    labels: list[str] | None
        The ``--label`` values.

    Returns
    -------
    list[str]
        The single labels.

    """
    return [
        label.strip()
        for value in labels or []
        for label in value.split(",")
        if label.strip()
    ]


@changelog.command("check-pr")
def check_pr(
    base: str = typer.Argument(..., help="Base ref or SHA of the pull request."),
    head: str = typer.Argument("HEAD", help="Head ref or SHA of the pull request."),
    label: Annotated[
        list[str] | None,
        typer.Option(
            help="A label of the pull request; repeat or separate with commas."
        ),
    ] = None,
) -> None:
    """Fail unless the pull request adds or updates a valid fragment."""
    try:
        message = check_pull_request(
            base,
            head,
            __GLOBAL_CONFIG__.changelog,
            Path.cwd(),
            _split_labels(label),
            __GLOBAL_CONFIG__.file.encoding,
        )
    except DevOpsChangelogError as error:
        raise _fail(error) from error
    typer.echo(message)


@changelog.command("check-release")
def check_release_command() -> None:
    """Fail unless the next release has at least one changelog entry."""
    try:
        check_release(
            __GLOBAL_CONFIG__.changelog, Path.cwd(), __GLOBAL_CONFIG__.file.encoding
        )
    except DevOpsChangelogError as error:
        raise _fail(error) from error
    typer.echo("the release contains changelog entries")


@changelog.command()
def stamp(version: str) -> None:
    """Stamp fragments and Next Release entries under VERSION."""
    try:
        result = stamp_release(
            version,
            __GLOBAL_CONFIG__.changelog,
            Path.cwd(),
            encoding=__GLOBAL_CONFIG__.file.encoding,
        )
    except DevOpsChangelogError as error:
        raise _fail(error) from error
    stamped = " and ".join(str(path.name) for path in result.stamped)
    typer.echo(
        f"stamped {stamped} for {version}; "
        f"consumed {len(result.consumed)} changelog fragment(s)"
    )


@changelog.command()
def notes(version: str) -> None:
    """Print the release notes of VERSION from all changelogs."""
    try:
        text = release_notes(
            version,
            __GLOBAL_CONFIG__.changelog,
            Path.cwd(),
            __GLOBAL_CONFIG__.file.encoding,
        )
    except DevOpsChangelogError as error:
        raise _fail(error) from error
    typer.echo(text)
