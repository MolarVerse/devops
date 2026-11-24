"""Stamp changelog fragments into the changelogs of a release."""

from __future__ import annotations

import re
import typing
from dataclasses import dataclass, field

from devops.files.update_changelog import (
    __CHANGELOG_INSERTION_MARKER__,
    DevOpsChangelogError,
    get_repo_url,
    release_header,
)

from .fragments import load_fragments

if typing.TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from devops.config import AudienceConfig, ChangelogConfig

    from .fragments import Fragment

NEXT_RELEASE = re.compile(r"^##\s+Next Release\s*$")
RELEASE_HEADING = re.compile(r"^##\s+\[")
SECTION_HEADING = re.compile(r"^###\s+(.+?)\s*$")
BULLET = re.compile(r"^\s*-\s+\S")
PREAMBLE = ""


@dataclass
class ChangelogFile:
    """A changelog split around its ``## Next Release`` body."""

    audience: AudienceConfig
    path: Path
    head: list[str]
    body: list[str]
    tail: list[str]


@dataclass
class StampResult:
    """The outcome of :func:`stamp_release`."""

    stamped: list[Path] = field(default_factory=list)
    consumed: list[Path] = field(default_factory=list)


def split_next_release(
    lines: list[str], name: str
) -> tuple[list[str], list[str], list[str]]:
    """Split a changelog into head, Next Release body and release history.

    Parameters
    ----------
    lines: list[str]
        The changelog lines.
    name: str
        The changelog name, used in error messages.

    Returns
    -------
    tuple[list[str], list[str], list[str]]
        The lines up to ``## Next Release``, its body and the history.

    Raises
    ------
    DevOpsChangelogError
        If the changelog has no ``## Next Release`` heading.

    """
    next_index = None
    end_index = len(lines)

    for index, line in enumerate(lines):
        if next_index is None and NEXT_RELEASE.match(line):
            next_index = index
            continue
        if next_index is not None and (
            RELEASE_HEADING.match(line) or __CHANGELOG_INSERTION_MARKER__ in line
        ):
            end_index = index
            break

    if next_index is None:
        msg = f"could not find '## Next Release' in {name}"
        raise DevOpsChangelogError(msg)

    return (
        lines[: next_index + 1],
        lines[next_index + 1 : end_index],
        lines[end_index:],
    )


def parse_subsections(body: Iterable[str], order: list[str]) -> dict[str, list[str]]:
    """Parse ``###`` sections into a mapping of titles to their lines.

    Lines before the first section are kept under the empty title.

    Parameters
    ----------
    body: Iterable[str]
        The Next Release body.
    order: list[str]
        The known section titles.

    Returns
    -------
    dict[str, list[str]]
        The non-blank lines of every section.

    """
    sections = {PREAMBLE: [], **{section: [] for section in order}}
    current = PREAMBLE

    for raw in body:
        match = SECTION_HEADING.match(raw)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        if raw.strip():
            sections[current].append(raw)

    return sections


def render_sections(sections: dict[str, list[str]], order: list[str]) -> list[str]:
    """Render sections in the configured order, unknown sections last.

    Parameters
    ----------
    sections: dict[str, list[str]]
        The section lines, as returned by :func:`parse_subsections`.
    order: list[str]
        The configured section order.

    Returns
    -------
    list[str]
        The rendered lines.

    """
    output = []
    preamble = sections.get(PREAMBLE, [])
    if preamble:
        output.extend([*preamble, ""])

    known = [section for section in order if section in sections]
    unknown = [
        section for section in sections if section not in order and section != PREAMBLE
    ]
    for section in [*known, *unknown]:
        lines = [line for line in sections[section] if line.strip()]
        if lines:
            output.extend([f"### {section}", "", *lines, ""])

    return output


def append_fragments(
    sections: dict[str, list[str]], fragments: Iterable[Fragment], audience: str
) -> None:
    """Append the bullets of one audience's fragments to their sections.

    Parameters
    ----------
    sections: dict[str, list[str]]
        The parsed sections, changed in place.
    fragments: Iterable[Fragment]
        All fragments.
    audience: str
        The audience whose fragments are appended.

    """
    for fragment in fragments:
        if fragment.audience != audience:
            continue
        entries = sections.setdefault(fragment.section, [])
        entries.extend(entry for entry in fragment.entries if entry not in entries)


def trim_blank_lines(lines: list[str]) -> list[str]:
    """Remove blank lines at both ends.

    Parameters
    ----------
    lines: list[str]
        The lines.

    Returns
    -------
    list[str]
        The lines without leading and trailing blank lines.

    """
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def has_release_notes(lines: Iterable[str]) -> bool:
    """Return whether lines contain at least one bullet.

    Parameters
    ----------
    lines: Iterable[str]
        The lines.

    Returns
    -------
    bool
        True if a line is a Markdown bullet.

    """
    return any(BULLET.match(line) for line in lines)


def stamp_lines(
    head: list[str], body: list[str], tail: list[str], header: str
) -> list[str]:
    """Move a Next Release body under a release heading.

    Parameters
    ----------
    head: list[str]
        The lines up to ``## Next Release``.
    body: list[str]
        The release body.
    tail: list[str]
        The release history.
    header: str
        The release heading.

    Returns
    -------
    list[str]
        The new changelog lines, with an empty Next Release.

    """
    history = trim_blank_lines(
        [line for line in tail if __CHANGELOG_INSERTION_MARKER__ not in line]
    )
    output = [
        *trim_blank_lines(head),
        "",
        __CHANGELOG_INSERTION_MARKER__,
        header,
        "",
        *trim_blank_lines(body),
    ]
    if history:
        output.extend(["", *history])
    return output


def _release_pattern(version: str) -> re.Pattern[str]:
    return re.compile(rf"^## \[{re.escape(version)}\]\(")


def prepared_release(
    tail: list[str], version: str
) -> tuple[str | None, list[str], list[str]]:
    """Take the latest release out of the history to refresh it.

    Parameters
    ----------
    tail: list[str]
        The release history.
    version: str
        The version being stamped.

    Returns
    -------
    tuple[str | None, list[str], list[str]]
        The existing heading (None if the version is new), its body and the
        remaining history.

    Raises
    ------
    DevOpsChangelogError
        If the version exists but is not the latest release.

    """
    history = trim_blank_lines(
        [line for line in tail if __CHANGELOG_INSERTION_MARKER__ not in line]
    )
    pattern = _release_pattern(version)
    matches = [index for index, line in enumerate(history) if pattern.match(line)]
    if not matches:
        return None, [], tail
    if matches != [0]:
        msg = f"cannot refresh {version}: it is not the latest release"
        raise DevOpsChangelogError(msg)

    end = next(
        (i for i in range(1, len(history)) if RELEASE_HEADING.match(history[i])),
        len(history),
    )
    return history[0], history[1:end], history[end:]


def release_section(lines: list[str], version: str) -> list[str]:
    """Return the body of a stamped release.

    Parameters
    ----------
    lines: list[str]
        The changelog lines.
    version: str
        The release version.

    Returns
    -------
    list[str]
        The release body, or an empty list if the version is not stamped.

    """
    pattern = _release_pattern(version)
    start = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if start is None:
        return []
    end = next(
        (i for i in range(start + 1, len(lines)) if RELEASE_HEADING.match(lines[i])),
        len(lines),
    )
    return trim_blank_lines(lines[start + 1 : end])


def _read_lines(path: Path, encoding: str) -> list[str]:
    if not path.is_file():
        msg = f"{path} not found"
        raise DevOpsChangelogError(msg)
    return path.read_text(encoding=encoding).splitlines()


def read_changelogs(
    config: ChangelogConfig, root: Path, encoding: str = "utf-8"
) -> list[ChangelogFile]:
    """Read and split the changelog of every audience.

    Parameters
    ----------
    config: ChangelogConfig
        The changelog configuration.
    root: Path
        The repository root.
    encoding: str
        The file encoding.

    Returns
    -------
    list[ChangelogFile]
        One split changelog per audience.

    """
    changelogs = []
    for audience in config.audiences:
        path = root / audience.changelog
        head, body, tail = split_next_release(
            _read_lines(path, encoding), str(audience.changelog)
        )
        changelogs.append(ChangelogFile(audience, path, head, body, tail))
    return changelogs


def reject_released_fragments(
    fragments: Iterable[Fragment], histories: dict[str, list[str]]
) -> None:
    """Fail if a fragment repeats a bullet of an earlier release.

    Parameters
    ----------
    fragments: Iterable[Fragment]
        All fragments.
    histories: dict[str, list[str]]
        The release history of every audience.

    Raises
    ------
    DevOpsChangelogError
        If a fragment bullet is already released.

    """
    released = {
        audience: {line.strip() for line in history if BULLET.match(line)}
        for audience, history in histories.items()
    }
    repeated = sorted(
        fragment.relative_path
        for fragment in fragments
        if any(
            entry.strip() in released.get(fragment.audience, set())
            for entry in fragment.entries
        )
    )
    if repeated:
        msg = (
            "these fragments repeat an entry of an earlier release; "
            "delete them on the development branch: " + ", ".join(repeated)
        )
        raise DevOpsChangelogError(msg)


def render_release(
    changelog: ChangelogFile,
    fragments: list[Fragment],
    previous_body: list[str] | None = None,
) -> list[str]:
    """Render the release body of one changelog.

    The Next Release body is kept as it is when there is nothing to merge.

    Parameters
    ----------
    changelog: ChangelogFile
        The split changelog.
    fragments: list[Fragment]
        All fragments.
    previous_body: list[str] | None
        The body of the release being refreshed.

    Returns
    -------
    list[str]
        The rendered release body.

    """
    audience = changelog.audience
    previous_body = previous_body or []
    if not previous_body and not any(
        fragment.audience == audience.name for fragment in fragments
    ):
        return trim_blank_lines(changelog.body)

    sections = parse_subsections([*previous_body, *changelog.body], audience.order)
    append_fragments(sections, fragments, audience.name)
    return render_sections(sections, audience.order)


def check_release(config: ChangelogConfig, root: Path, encoding: str = "utf-8") -> None:
    """Check that the next release has at least one changelog entry.

    Parameters
    ----------
    config: ChangelogConfig
        The changelog configuration.
    root: Path
        The repository root.
    encoding: str
        The file encoding.

    Raises
    ------
    DevOpsChangelogError
        If a fragment is malformed or repeats a release, or there is no entry.

    """
    fragments = load_fragments(config, root, encoding)
    changelogs = read_changelogs(config, root, encoding)
    reject_released_fragments(
        fragments, {log.audience.name: log.tail for log in changelogs}
    )
    if not any(has_release_notes(render_release(log, fragments)) for log in changelogs):
        msg = "the release needs at least one changelog entry"
        raise DevOpsChangelogError(msg)


def stamp_release(
    version: str,
    config: ChangelogConfig,
    root: Path,
    *,
    repo_url: str | None = None,
    encoding: str = "utf-8",
) -> StampResult:
    """Stamp all fragments and Next Release entries under a version.

    Only changelogs with entries are stamped. Stamping the latest version
    again merges new fragments into it. Consumed fragments are deleted;
    placeholders such as ``.gitkeep`` stay.

    Parameters
    ----------
    version: str
        The release version, for example ``v1.2.0``.
    config: ChangelogConfig
        The changelog configuration.
    root: Path
        The repository root.
    repo_url: str | None
        The repository URL for new headings. Defaults to
        :func:`~devops.files.update_changelog.get_repo_url`.
    encoding: str
        The file encoding.

    Returns
    -------
    StampResult
        The stamped changelogs and the deleted fragments.

    Raises
    ------
    DevOpsChangelogError
        If a fragment or changelog is invalid or the release has no entry.

    """
    changelogs = read_changelogs(config, root, encoding)
    previous = {}
    for log in changelogs:
        header, body, log.tail = prepared_release(log.tail, version)
        previous[log.audience.name] = (header, body)

    fragments = load_fragments(config, root, encoding)
    reject_released_fragments(
        fragments, {log.audience.name: log.tail for log in changelogs}
    )

    rendered = [
        (log, render_release(log, fragments, previous[log.audience.name][1]))
        for log in changelogs
    ]
    rendered = [(log, body) for log, body in rendered if has_release_notes(body)]
    if not rendered:
        msg = "the release needs at least one changelog entry"
        raise DevOpsChangelogError(msg)

    result = StampResult()
    for log, body in rendered:
        header = previous[log.audience.name][0]
        if header is None:
            repo_url = repo_url or get_repo_url()
            header = release_header(version, repo_url)
        output = stamp_lines(log.head, body, log.tail, header)
        log.path.write_text("\n".join(output) + "\n", encoding=encoding)
        result.stamped.append(log.path)

    for fragment in fragments:
        fragment.path.unlink()
        result.consumed.append(fragment.path)

    return result


def release_notes(
    version: str, config: ChangelogConfig, root: Path, encoding: str = "utf-8"
) -> str:
    """Return the release notes of a stamped version for all audiences.

    Parameters
    ----------
    version: str
        The release version.
    config: ChangelogConfig
        The changelog configuration.
    root: Path
        The repository root.
    encoding: str
        The file encoding.

    Returns
    -------
    str
        The notes; an audience with a ``notes_heading`` gets a ``##`` heading.

    Raises
    ------
    DevOpsChangelogError
        If no changelog has entries for the version.

    """
    blocks = []
    for audience in config.audiences:
        path = root / audience.changelog
        if not path.is_file():
            continue
        section = release_section(_read_lines(path, encoding), version)
        if not section:
            continue
        if audience.notes_heading:
            section = [f"## {audience.notes_heading}", "", *section]
        blocks.append("\n".join(section))

    if not blocks:
        msg = f"no changelog entries found for {version}"
        raise DevOpsChangelogError(msg)
    return "\n\n".join(blocks)
