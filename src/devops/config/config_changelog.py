"""Changelog fragment configuration parsing module."""

from __future__ import annotations

import re
import typing
from dataclasses import dataclass, field
from pathlib import Path

from .base import ConfigError, get_bool, get_int, get_str, get_str_list, get_table

if typing.TYPE_CHECKING:
    from typing import Any

NAME_PATTERN = re.compile(r"[a-z]+")
AUDIENCE_PATTERN = re.compile(r"[a-z][a-z0-9-]*")

DEFAULT_USER_CATEGORIES = {
    "enhancement": "New Features",
    "change": "Changes",
    "bugfix": "Bug Fixes",
    "performance": "Performance",
    "compatibility": "Build and Compatibility",
    "documentation": "Documentation",
    "deprecations": "Deprecations",
}

DEFAULT_DEVELOPER_CATEGORIES = {
    "enhancement": "Enhancements",
    "bugfix": "Bug Fixes",
    "performance": "Performance",
    "build": "Build",
    "ci": "CI",
    "test": "Tests",
    "internal": "Internal",
    "documentation": "Documentation",
}


@dataclass(frozen=True)
class AudienceConfig:
    """Dataclass to hold the settings of one changelog audience."""

    name: str
    changelog: Path
    categories: dict[str, str]
    section_order: list[str] = field(default_factory=list)
    notes_heading: str = ""

    @property
    def order(self) -> list[str]:
        """Return the section titles in the order they are rendered.

        Returns
        -------
        list[str]
            ``section_order`` followed by the category titles not in it.

        """
        order = list(self.section_order)
        order.extend(title for title in self.categories.values() if title not in order)
        return order

    def to_toml_lines(self) -> list[str]:
        """Convert the AudienceConfig to TOML lines.

        Returns
        -------
        list[str]
            The list of TOML lines representing the configuration.

        """
        categories = ", ".join(
            f'{key} = "{value}"' for key, value in self.categories.items()
        )
        order = ", ".join(f'"{title}"' for title in self.section_order)
        return [
            f"#[changelog.audiences.{self.name}]\n",
            f'#changelog = "{self.changelog}"\n',
            f'#notes_heading = "{self.notes_heading}"\n',
            f"#section_order = [{order}]\n",
            f"#categories = {{ {categories} }}\n",
        ]


def default_audiences() -> list[AudienceConfig]:
    """Return the default user and developer audiences.

    Returns
    -------
    list[AudienceConfig]
        The audiences used when ``[changelog.audiences]`` is not set.

    """
    return [
        AudienceConfig(
            name="user",
            changelog=Path("CHANGELOG.md"),
            categories=dict(DEFAULT_USER_CATEGORIES),
        ),
        AudienceConfig(
            name="developer",
            changelog=Path("DEV-CHANGELOG.md"),
            categories=dict(DEFAULT_DEVELOPER_CATEGORIES),
            section_order=["Breaking Changes"],
            notes_heading="Developer Changes",
        ),
    ]


@dataclass(frozen=True)
class ChangelogConfig:
    """Dataclass to hold changelog fragment configuration values."""

    fragment_dir: Path = Path("changes")
    audience_dirs: bool = True
    skip_label: str = "skip-changelog"
    max_entry_length: int = 360
    audiences: list[AudienceConfig] = field(default_factory=default_audiences)

    def audience(self, name: str) -> AudienceConfig:
        """Return the audience with the given name.

        Parameters
        ----------
        name: str
            The audience name.

        Returns
        -------
        AudienceConfig
            The matching audience.

        Raises
        ------
        KeyError
            If no audience has this name.

        """
        for audience in self.audiences:
            if audience.name == name:
                return audience
        raise KeyError(name)

    @property
    def changelogs(self) -> list[Path]:
        """Return the changelog files of all audiences.

        Returns
        -------
        list[Path]
            One changelog path per audience.

        """
        return [audience.changelog for audience in self.audiences]

    def to_toml_lines(self) -> list[str]:
        """Convert the ChangelogConfig to TOML lines.

        Returns
        -------
        list[str]
            The list of TOML lines representing the configuration.

        """
        lines = [
            "[changelog]\n",
            f'#fragment_dir = "{self.fragment_dir}"\n',
            f"#audience_dirs = {str(self.audience_dirs).lower()}\n",
            f'#skip_label = "{self.skip_label}"\n',
            f"#max_entry_length = {self.max_entry_length}\n",
        ]
        for audience in self.audiences:
            lines += ["\n", *audience.to_toml_lines()]
        return lines


def _parse_categories(table: dict[str, Any], name: str) -> dict[str, str]:
    """Parse the category to section title mapping of one audience.

    Parameters
    ----------
    table: dict[str, Any]
        The audience table.
    name: str
        The audience name, used in error messages.

    Returns
    -------
    dict[str, str]
        The categories in file order.

    Raises
    ------
    ConfigError
        If a category or title is invalid or no category is given.

    """
    categories = get_table(table, "categories")
    if not categories:
        msg = f"changelog.audiences.{name}.categories must not be empty"
        raise ConfigError(msg)

    for category, title in categories.items():
        if not NAME_PATTERN.fullmatch(category):
            msg = (
                f"changelog.audiences.{name}: category '{category}' "
                "must use only lowercase letters"
            )
            raise ConfigError(msg)
        if not isinstance(title, str) or not title.strip():
            msg = (
                f"changelog.audiences.{name}.categories.{category} "
                "must be a non-empty string"
            )
            raise ConfigError(msg)
    return dict(categories)


def _parse_audience(name: str, raw: Any) -> AudienceConfig:
    """Parse one ``[changelog.audiences.<name>]`` table.

    Keys left out fall back to the default audience of the same name.

    Parameters
    ----------
    name: str
        The audience name.
    raw: Any
        The raw audience table.

    Returns
    -------
    AudienceConfig
        The parsed audience.

    Raises
    ------
    ConfigError
        If the name or a value is invalid, or a required key is missing.

    """
    if not AUDIENCE_PATTERN.fullmatch(name):
        msg = (
            f"changelog audience '{name}' must start with a lowercase letter "
            "and use only lowercase letters, digits and hyphens"
        )
        raise ConfigError(msg)

    table = get_table({name: raw}, name)
    default = next((a for a in default_audiences() if a.name == name), None)

    changelog = get_str(table, "changelog")
    if changelog is None and default is None:
        msg = f"changelog.audiences.{name}.changelog is required"
        raise ConfigError(msg)

    if "categories" in table or default is None:
        categories = _parse_categories(table, name)
    else:
        categories = default.categories

    section_order = get_str_list(
        table,
        "section_order",
        default=default.section_order if default is not None else None,
    )
    notes_heading = get_str(
        table,
        "notes_heading",
        default=default.notes_heading if default is not None else "",
    )

    return AudienceConfig(
        name=name,
        changelog=Path(changelog) if changelog is not None else default.changelog,
        categories=categories,
        section_order=section_order,
        notes_heading=notes_heading,
    )


def parse_changelog_config(raw_config: dict) -> ChangelogConfig:
    """Parse changelog fragment configuration from a raw dictionary.

    Parameters
    ----------
    raw_config: dict
        The raw configuration dictionary.

    Returns
    -------
    ChangelogConfig
        The parsed ChangelogConfig dataclass instance.

    Raises
    ------
    ConfigError
        If a value is invalid, two audiences share a changelog, or
        ``audience_dirs = false`` is used with more than one audience.

    """
    table = get_table(raw_config, "changelog")

    fragment_dir = get_str(table, "fragment_dir", default="changes")
    audience_dirs = get_bool(
        table, "audience_dirs", default=ChangelogConfig.audience_dirs
    )
    skip_label = get_str(table, "skip_label", default=ChangelogConfig.skip_label)
    max_entry_length = get_int(
        table, "max_entry_length", default=ChangelogConfig.max_entry_length
    )

    if max_entry_length <= 0:
        msg = f"changelog.max_entry_length must be positive, got {max_entry_length}"
        raise ConfigError(msg)

    raw_audiences = get_table(table, "audiences")
    if raw_audiences:
        audiences = [_parse_audience(name, raw) for name, raw in raw_audiences.items()]
    else:
        audiences = default_audiences()

    changelogs = [audience.changelog for audience in audiences]
    if len(set(changelogs)) != len(changelogs):
        msg = "every changelog audience needs its own changelog file"
        raise ConfigError(msg)

    if not audience_dirs and len(audiences) != 1:
        msg = "changelog.audience_dirs = false needs exactly one audience"
        raise ConfigError(msg)

    return ChangelogConfig(
        fragment_dir=Path(fragment_dir),
        audience_dirs=audience_dirs,
        skip_label=skip_label,
        max_entry_length=max_entry_length,
        audiences=audiences,
    )
