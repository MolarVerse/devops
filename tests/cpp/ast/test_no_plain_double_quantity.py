"""Tests for the NoPlainDoubleQuantity AST check via the shared engine."""

from __future__ import annotations

import typing

import pytest

from devops.config.base import ConfigError
from devops.cpp.ast.checks.no_plain_double_quantity import NoPlainDoubleQuantity
from devops.cpp.ast.engine import run_ast_checks
from devops.cpp.ast.registry import ALL_CHECKS, configure_checks

if typing.TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("clang.cindex")

_QUANTITY = (
    "namespace mstd { struct kcal {}; "
    "template <typename U, typename Rep = double> struct quantity { Rep v; }; "
    "template <typename U, typename Rep = double> "
    "struct quantity_point { Rep v; }; }\n"
)


def _run(
    tmp_path: Path,
    code: str,
    config: dict | None = None,
    name: str = "example.cpp",
) -> list:
    check = NoPlainDoubleQuantity()
    check.configure(config or {})
    source = tmp_path / name
    source.write_text(code)
    return run_ast_checks(source, code, ["-std=c++23"], checks=[check])


@pytest.mark.parametrize(
    "code",
    [
        "struct Frame { double potentialEnergy; };",
        "struct Frame { float kineticEnergy = 0.0F; };",
        "struct Frame { long double totalEnergy; };",
        "class Frame { double _potentialEnergy; };",
        "struct S { double ENERGY; };",
        "struct S { const double mass = 1.0; };",
        "struct S { double timeStep; };",
        "struct S { double targetTemperature; };",
        "struct S { double pressure; };",
        "struct S { double velocity; };",
        "struct S { double charge; };",
        "struct S { double virial[3][3]; };",
        "struct S { double stress[9]; };",
        "struct S { double boxVolume; };",
        "struct S { double cutoffDistance; };",
        "struct S { double _forceConstant; };",
        "using Real = double; struct S { Real energy; };",
        "typedef float real; struct S { real mass; };",
        "union U { double energy; int raw; };",
        "struct Outer { struct Inner { double energy; } inner; };",
        "template <typename T> struct S { T t; double energy; };",
        "namespace ns { class S { public: double forces; }; }",
        "struct S { double &energy; };",
        # Containers of plain floating-point values.
        "#include <vector>\nstruct S { std::vector<double> masses; };",
        "#include <vector>\nstruct S { std::vector<std::vector<float>> forces; };",
        "#include <array>\nstruct S { std::array<double, 3> velocities; };",
        (
            "#include <map>\n#include <string>\n"
            "struct S { std::map<std::string, double> charges; };"
        ),
        "#include <optional>\nstruct S { std::optional<double> temperature; };",
        (
            "template <typename T> struct Vector3D { T x, y, z; };\n"
            "struct S { Vector3D<double> force; };"
        ),
        (
            "template <typename T> struct Vector3D { T x, y, z; };\n"
            "using Vec = Vector3D<double>; struct S { Vec force; };"
        ),
    ],
)
def test_flagged(tmp_path: Path, code: str) -> None:
    """Quantity-named members of a plain floating type are flagged once.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    diagnostics = _run(tmp_path, code)
    assert len(diagnostics) == 1, [d.format() for d in diagnostics]
    assert diagnostics[0].check_id == "noPlainDoubleQuantity"


@pytest.mark.parametrize(
    "code",
    [
        "struct S { double tolerance; };",
        "struct S { double factor; double ratio; };",
        "struct S { int energyIndex; };",
        "struct S { long timeStepCount; };",
        "struct S { bool forceRecompute; };",
        "#include <string>\nstruct S { std::string energyUnit; };",
        "#include <vector>\nstruct S { std::vector<int> massIndices; };",
        "struct S { double *energyBuffer; };",
        "struct S { static constexpr double maxEnergy = 1.0; };",
        "template <typename T> struct S { T energy; };",
        "double energy;",
        "void f() { double energy = 0.0; (void)energy; }",
        "void f(double energy);",
        "struct S { void energy(double e); };",
        "enum class Kind { energy, force };",
        # Templates that are not containers are handles, not values.
        "#include <memory>\nstruct S { std::unique_ptr<double> energy; };",
        (
            "#include <memory>\ntemplate <typename T> struct Element {};\n"
            "struct S { std::unique_ptr<Element<float>> force; };"
        ),
        (
            "template <typename T> struct Strong { T v; };\n"
            "struct S { Strong<double> energy; };"
        ),
        # Typed quantities, also with a double representation.
        _QUANTITY + "struct S { mstd::quantity<mstd::kcal> energy; };",
        _QUANTITY + "struct S { mstd::quantity<mstd::kcal, double> energy; };",
        _QUANTITY
        + "using Temperature = mstd::quantity_point<mstd::kcal>;\n"
        + "struct S { Temperature temperature; };",
        _QUANTITY
        + "#include <vector>\n"
        + "struct S { std::vector<mstd::quantity<mstd::kcal>> energies; };",
    ],
)
def test_not_flagged(tmp_path: Path, code: str) -> None:
    """Other names, types and declarations are not flagged.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    diagnostics = _run(tmp_path, code)
    assert diagnostics == [], [d.format() for d in diagnostics]


def test_message_and_location(tmp_path: Path) -> None:
    """The diagnostic names member, class, type and pattern at the member."""
    code = "struct Frame {\n    double potentialEnergy;\n};\n"
    diagnostics = _run(tmp_path, code)
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert (diagnostic.line, diagnostic.column) == (2, 12)
    assert "'potentialEnergy'" in diagnostic.message
    assert "'Frame'" in diagnostic.message
    assert "'double'" in diagnostic.message
    assert "'energy'" in diagnostic.message


def test_each_member_reported(tmp_path: Path) -> None:
    """Every offending member of a class is reported."""
    code = "struct S { double energy; double force; double factor; float mass; };"
    names = sorted(d.message.split("'")[1] for d in _run(tmp_path, code))
    assert names == ["energy", "force", "mass"]


class TestConfig:
    """Configuration options."""

    def test_allowed_names(self, tmp_path: Path) -> None:
        """Names in ``allowed_names`` are skipped, others still flagged."""
        code = "struct S { double energyTolerance; double energy; };"
        config = {"allowed_names": ["energyTolerance"]}
        diagnostics = _run(tmp_path, code, config)
        assert [d.message.split("'")[1] for d in diagnostics] == ["energy"]

    def test_name_patterns_replace_default(self, tmp_path: Path) -> None:
        """A given ``name_patterns`` list replaces the default patterns."""
        code = "struct S { double energy; double spin; };"
        diagnostics = _run(tmp_path, code, {"name_patterns": ["^sp"]})
        assert [d.message.split("'")[1] for d in diagnostics] == ["spin"]

    def test_empty_name_patterns(self, tmp_path: Path) -> None:
        """An empty ``name_patterns`` list flags nothing."""
        code = "struct S { double energy; };"
        assert _run(tmp_path, code, {"name_patterns": []}) == []

    def test_patterns_ignore_case(self, tmp_path: Path) -> None:
        """Patterns match case-insensitively."""
        code = "struct S { double PotentialENERGY; };"
        assert len(_run(tmp_path, code, {"name_patterns": ["Energy"]})) == 1

    def test_container_templates(self, tmp_path: Path) -> None:
        """Only templates in ``container_templates`` are looked into."""
        code = (
            "template <typename T> struct Buffer { T v; };\n"
            "struct S { Buffer<double> energy; };"
        )
        assert _run(tmp_path, code) == []
        assert len(_run(tmp_path, code, {"container_templates": ["Buffer"]})) == 1

    def test_exclude_paths(self, tmp_path: Path) -> None:
        """``exclude_paths`` keeps the check from running on matching files."""
        code = "struct S { double energy; };"
        config = {"noPlainDoubleQuantity": {"exclude_paths": ["*legacy.cpp"]}}
        checks = configure_checks(
            [c for c in ALL_CHECKS if c.id == "noPlainDoubleQuantity"], config
        )
        source = tmp_path / "legacy.cpp"
        source.write_text(code)
        assert run_ast_checks(source, code, ["-std=c++23"], checks=checks) == []
        other = tmp_path / "frame.cpp"
        other.write_text(code)
        assert len(run_ast_checks(other, code, ["-std=c++23"], checks=checks)) == 1

    @pytest.mark.parametrize(
        "config",
        [
            {"name_patterns": "energy"},
            {"name_patterns": [1]},
            {"allowed_names": "energy"},
            {"container_templates": [None]},
        ],
    )
    def test_invalid_type_raises(self, config: dict) -> None:
        """Non-list or non-string values raise a ConfigError.

        Parameters
        ----------
        config: dict
            The invalid configuration.

        """
        with pytest.raises(ConfigError, match="list of strings"):
            NoPlainDoubleQuantity().configure(config)

    def test_invalid_regex_raises(self) -> None:
        """An invalid regular expression raises a ConfigError."""
        with pytest.raises(ConfigError, match="invalid regular expression"):
            NoPlainDoubleQuantity().configure({"name_patterns": ["("]})

    def test_unknown_key_raises(self) -> None:
        """A misspelled key is an error instead of silently ignored."""
        with pytest.raises(ConfigError, match="allowed_name"):
            NoPlainDoubleQuantity().configure({"allowed_name": ["energy"]})

    def test_exclude_paths_key_accepted(self) -> None:
        """The generic ``exclude_paths`` key is not rejected as unknown."""
        NoPlainDoubleQuantity().configure({"exclude_paths": ["src/"]})
