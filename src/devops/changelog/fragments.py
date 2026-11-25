"""Parse changelog fragments shared by the PR check and the release stamp."""

from __future__ import annotations

import re
import typing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from devops.files.update_changelog import DevOpsChangelogError

if typing.TYPE_CHECKING:
    from devops.config import AudienceConfig, ChangelogConfig

FRAGMENT_PATTERN = re.compile(
    r"^(?P<category>[a-z]+)\.(?P<slug>[a-z0-9][a-z0-9-]*)\.md$"
)
IGNORED_NAMES = frozenset({"README.md"})


class FragmentError(DevOpsChangelogError):
    """Exception raised when a changelog fragment is malformed."""


@dataclass(frozen=True)
class Fragment:
    """One parsed changelog fragment file."""

    path: Path
    relative_path: str
    audience: str
    section: str
    entries: tuple[str, ...]


def audience_dir(audience: AudienceConfig, config: ChangelogConfig) -> PurePosixPath:
    """Return the repository relative directory of an audience's fragments.

    Parameters
    ----------
    audience: AudienceConfig
        The audience.
    config: ChangelogConfig
        The changelog configuration.

    Returns
    -------
    PurePosixPath
        ``<fragment_dir>/<audience>`` or just ``<fragment_dir>``.

    """
    base = PurePosixPath(config.fragment_dir.as_posix())
    return base / audience.name if config.audience_dirs else base


def fragment_audience(
    relative_path: str, config: ChangelogConfig
) -> AudienceConfig | None:
    """Return the audience of a repository relative fragment path, if any.

    Parameters
    ----------
    relative_path: str
        A path as printed by ``git diff --name-status``.
    config: ChangelogConfig
        The changelog configuration.

    Returns
    -------
    AudienceConfig | None
        The audience, or None if the path is not a fragment.

    """
    path = PurePosixPath(relative_path)
    if not path.name.endswith(".md") or path.name in IGNORED_NAMES:
        return None

    for audience in config.audiences:
        if path.parent == audience_dir(audience, config):
            return audience
    return None


def parse_fragment_name(name: str, audience: AudienceConfig) -> str:
    """Return the changelog section encoded by a fragment filename.

    Parameters
    ----------
    name: str
        The file name, ``<category>.<slug>.md``.
    audience: AudienceConfig
        The audience the fragment belongs to.

    Returns
    -------
    str
        The section title of the category.

    Raises
    ------
    FragmentError
        If the name is malformed or the category is unknown.

    """
    match = FRAGMENT_PATTERN.match(name)
    if not match:
        msg = (
            f"invalid fragment name '{name}'; expected <category>.<slug>.md, "
            "where <category> uses only lowercase letters and <slug> starts "
            "with a lowercase letter or digit and uses only lowercase letters, "
            "digits, and hyphens"
        )
        raise FragmentError(msg)

    category = match.group("category")
    if category not in audience.categories:
        allowed = ", ".join(sorted(audience.categories))
        msg = (
            f"invalid {audience.name} category '{category}' in {name}; "
            f"allowed: {allowed}"
        )
        raise FragmentError(msg)

    return audience.categories[category]


def parse_fragment_entries(text: str, name: str, max_length: int) -> list[str]:
    """Parse the Markdown bullets of a fragment.

    Parameters
    ----------
    text: str
        The fragment contents.
    name: str
        The fragment name, used in error messages.
    max_length: int
        The maximum length of one bullet line.

    Returns
    -------
    list[str]
        The bullet lines.

    Raises
    ------
    FragmentError
        If the text is not one or more bullets ending with a newline.

    """
    if not text.endswith("\n"):
        msg = f"{name} must end with a newline"
        raise FragmentError(msg)

    entries = []
    for line in text.rstrip("\n").split("\n"):
        if not line.startswith("- ") or not line[2:].strip():
            msg = (
                f"{name} must contain only Markdown bullets ('- ...'), "
                "with no blank lines"
            )
            raise FragmentError(msg)
        if len(line) > max_length:
            msg = f"{name} has a bullet exceeding the {max_length}-character limit"
            raise FragmentError(msg)
        entries.append(line)

    return entries


def read_fragment_entries(
    path: Path, max_length: int, encoding: str = "utf-8"
) -> list[str]:
    """Read the Markdown bullets of a fragment file.

    Parameters
    ----------
    path: Path
        The fragment file.
    max_length: int
        The maximum length of one bullet line.
    encoding: str
        The file encoding.

    Returns
    -------
    list[str]
        The bullet lines.

    """
    text = path.read_text(encoding=encoding)
    return parse_fragment_entries(text, path.name, max_length)


def load_fragments(
    config: ChangelogConfig, root: Path, encoding: str = "utf-8"
) -> list[Fragment]:
    """Load every fragment of every audience below a repository root.

    Placeholders such as ``.gitkeep`` and ``README.md`` are not fragments.

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
    list[Fragment]
        The fragments, by audience and then by file name.

    """
    fragments = []
    for audience in config.audiences:
        relative_dir = audience_dir(audience, config)
        directory = root / relative_dir
        if not directory.is_dir():
            continue

        for path in sorted(directory.glob("*.md")):
            if path.name in IGNORED_NAMES:
                continue
            section = parse_fragment_name(path.name, audience)
            entries = read_fragment_entries(path, config.max_entry_length, encoding)
            fragments.append(
                Fragment(
                    path=path,
                    relative_path=str(relative_dir / path.name),
                    audience=audience.name,
                    section=section,
                    entries=tuple(entries),
                )
            )

    return fragments
