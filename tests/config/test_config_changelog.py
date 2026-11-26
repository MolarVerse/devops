"""Tests for devops.config.config_changelog."""

import tomllib
from pathlib import Path

import pytest

from devops.config import AudienceConfig, ChangelogConfig
from devops.config.base import ConfigError
from devops.config.config import parse_config
from devops.config.config_changelog import (
    DEFAULT_DEVELOPER_CATEGORIES,
    DEFAULT_USER_CATEGORIES,
    parse_changelog_config,
)


def test_defaults_are_the_pq_values() -> None:
    """A missing [changelog] table gives PQ's fragment layout."""
    config = parse_changelog_config({})
    assert config == ChangelogConfig()
    assert config.fragment_dir == Path("changes")
    assert config.audience_dirs is True
    assert config.skip_label == "skip-changelog"
    assert config.max_entry_length == 360
    assert [audience.name for audience in config.audiences] == ["user", "developer"]
    assert config.changelogs == [Path("CHANGELOG.md"), Path("DEV-CHANGELOG.md")]

    user = config.audience("user")
    developer = config.audience("developer")
    assert user.categories == DEFAULT_USER_CATEGORIES
    assert developer.categories == DEFAULT_DEVELOPER_CATEGORIES
    assert user.notes_heading == ""
    assert developer.notes_heading == "Developer Changes"
    assert developer.order[0] == "Breaking Changes"
    assert developer.order[1:] == list(DEFAULT_DEVELOPER_CATEGORIES.values())


def test_unknown_audience_lookup() -> None:
    """Looking up an unknown audience is a KeyError."""
    with pytest.raises(KeyError):
        ChangelogConfig().audience("ops")


def test_scalar_values_are_read() -> None:
    """The top-level keys are read."""
    config = parse_changelog_config(
        {
            "changelog": {
                "fragment_dir": ".changes",
                "skip_label": "no-changelog",
                "max_entry_length": 200,
            }
        }
    )
    assert config.fragment_dir == Path(".changes")
    assert config.skip_label == "no-changelog"
    assert config.max_entry_length == 200
    assert config.audiences == ChangelogConfig().audiences


def test_audiences_replace_the_defaults() -> None:
    """Configured audiences replace both defaults, in file order."""
    config = parse_changelog_config(
        {
            "changelog": {
                "audiences": {
                    "developer": {"changelog": "docs/DEV.md"},
                    "ops": {
                        "changelog": "OPS.md",
                        "categories": {"deploy": "Deployment", "fix": "Fixes"},
                        "section_order": ["Breaking Changes"],
                        "notes_heading": "Operations",
                    },
                }
            }
        }
    )
    assert [audience.name for audience in config.audiences] == ["developer", "ops"]
    developer, ops = config.audiences
    assert developer.changelog == Path("docs/DEV.md")
    assert developer.categories == DEFAULT_DEVELOPER_CATEGORIES
    assert developer.notes_heading == "Developer Changes"
    assert ops == AudienceConfig(
        name="ops",
        changelog=Path("OPS.md"),
        categories={"deploy": "Deployment", "fix": "Fixes"},
        section_order=["Breaking Changes"],
        notes_heading="Operations",
    )
    assert ops.order == ["Breaking Changes", "Deployment", "Fixes"]


def test_known_audience_categories_can_be_replaced() -> None:
    """Giving categories for user replaces the default ones."""
    config = parse_changelog_config(
        {"changelog": {"audiences": {"user": {"categories": {"fix": "Fixes"}}}}}
    )
    assert config.audience("user").categories == {"fix": "Fixes"}
    assert config.audience("user").changelog == Path("CHANGELOG.md")


def test_single_audience_without_dirs() -> None:
    """audience_dirs = false works with one audience."""
    config = parse_changelog_config(
        {
            "changelog": {
                "audience_dirs": False,
                "audiences": {"user": {}},
            }
        }
    )
    assert config.audience_dirs is False
    assert config.changelogs == [Path("CHANGELOG.md")]


def test_global_config_has_changelog() -> None:
    """parse_config fills GlobalConfig.changelog."""
    config = parse_config({"changelog": {"skip_label": "none"}})
    assert config.changelog.skip_label == "none"


@pytest.mark.parametrize(
    ("table", "message"),
    [
        ({"fragment_dir": 1}, "fragment_dir"),
        ({"audience_dirs": "yes"}, "audience_dirs"),
        ({"skip_label": []}, "skip_label"),
        ({"max_entry_length": 0}, "max_entry_length"),
        ({"audiences": []}, "audiences"),
        ({"audiences": {"user": "CHANGELOG.md"}}, "user"),
        ({"audiences": {"User": {}}}, "audience 'User'"),
        ({"audiences": {"ops": {"categories": {"fix": "F"}}}}, "ops.changelog"),
        ({"audiences": {"ops": {"changelog": "OPS.md"}}}, "ops.categories"),
        (
            {"audiences": {"ops": {"changelog": "O.md", "categories": {}}}},
            "must not be empty",
        ),
        (
            {"audiences": {"ops": {"changelog": "O.md", "categories": {"Fix": "F"}}}},
            "category 'Fix'",
        ),
        (
            {"audiences": {"ops": {"changelog": "O.md", "categories": {"fix": 1}}}},
            "ops.categories.fix",
        ),
        (
            {"audiences": {"ops": {"changelog": "O.md", "categories": {"fix": " "}}}},
            "ops.categories.fix",
        ),
        ({"audiences": {"user": {"section_order": "A"}}}, "section_order"),
        ({"audiences": {"user": {"notes_heading": 1}}}, "notes_heading"),
        (
            {"audiences": {"user": {}, "developer": {"changelog": "CHANGELOG.md"}}},
            "its own changelog",
        ),
        ({"audience_dirs": False}, "exactly one audience"),
    ],
)
def test_invalid_values(table: dict, message: str) -> None:
    """Wrong types and values are config errors."""
    with pytest.raises(ConfigError, match=message):
        parse_changelog_config({"changelog": table})


def test_toml_lines() -> None:
    """The template lists every key, commented out."""
    config = ChangelogConfig(
        audiences=[
            AudienceConfig(
                name="ops",
                changelog=Path("OPS.md"),
                categories={"fix": "Fixes"},
                section_order=["Breaking Changes"],
                notes_heading="Operations",
            )
        ]
    )
    assert config.to_toml_lines() == [
        "[changelog]\n",
        '#fragment_dir = "changes"\n',
        "#audience_dirs = true\n",
        '#skip_label = "skip-changelog"\n',
        "#max_entry_length = 360\n",
        "\n",
        "#[changelog.audiences.ops]\n",
        '#changelog = "OPS.md"\n',
        '#notes_heading = "Operations"\n',
        '#section_order = ["Breaking Changes"]\n',
        '#categories = { fix = "Fixes" }\n',
    ]


def test_default_toml_lines_parse_back() -> None:
    """The default template, uncommented, parses to the defaults."""
    lines = ChangelogConfig().to_toml_lines()
    text = "".join(line.removeprefix("#") for line in lines)
    assert parse_changelog_config(tomllib.loads(text)) == ChangelogConfig()
