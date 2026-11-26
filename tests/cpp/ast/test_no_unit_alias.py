"""Tests for the NoUnitAlias AST check via the shared engine."""

from __future__ import annotations

import typing

import pytest

from devops.config.base import ConfigError
from devops.cpp.ast.checks.no_unit_alias import NoUnitAlias
from devops.cpp.ast.engine import run_ast_checks
from devops.cpp.ast.registry import configure_checks

if typing.TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("clang.cindex")

# A tiny stand-in for mp-units: units multiply into units, a number times a
# unit gives a quantity.
_UNITS = """
namespace mp_units {
template <typename T> concept Unit = requires { typename T::is_unit; };
struct unit_base { using is_unit = void; };
template <typename... Ts> struct derived_unit : unit_base {};
template <typename U> struct quantity { double value; };
template <typename... Ts> struct derived_quantity_spec {};
template <Unit A, Unit B> constexpr derived_unit<A, B> operator*(A, B) { return {}; }
template <Unit A, Unit B> constexpr derived_unit<A, B> operator/(A, B) { return {}; }
template <Unit U> constexpr quantity<U> operator*(double, U) { return {1.0}; }
template <int N, Unit U> constexpr derived_unit<U> pow(U) { return {}; }
template <Unit U> constexpr derived_unit<U> sqrt(U) { return {}; }
template <Unit U> constexpr U id(U u) { return u; }
namespace si {
inline constexpr struct metre : mp_units::unit_base {} m;
inline constexpr struct second : mp_units::unit_base {} s;
inline constexpr struct electronvolt : mp_units::unit_base {} eV;
}
namespace isq {
inline constexpr struct length {} length;
inline constexpr struct time {} time;
template <typename A, typename B>
constexpr derived_quantity_spec<A, B> operator/(A, B) { return {}; }
}
}
namespace mstd::units {
inline constexpr struct angstrom : mp_units::unit_base {} angstrom;
}
namespace other {
inline constexpr struct widget : mp_units::unit_base {} w;
}
using mp_units::si::eV;
using mp_units::si::m;
using mp_units::si::s;
using mstd::units::angstrom;
"""


def _run(
    tmp_path: Path,
    code: str,
    config: dict | None = None,
    name: str = "example.cpp",
) -> list:
    check = NoUnitAlias()
    check.configure(config or {})
    source = tmp_path / name
    content = _UNITS + code
    source.write_text(content)
    return run_ast_checks(source, content, ["-std=c++23"], checks=[check])


@pytest.mark.parametrize(
    "code",
    [
        "constexpr auto ASE_FORCE = eV / angstrom;",
        "inline constexpr auto ASE_FORCE = eV / angstrom;",
        "const auto ASE_FORCE = eV / angstrom;",
        "constexpr auto SPEED = (m / s);",
        "constexpr auto VOLUME = m * m * m;",
        "constexpr auto AREA = mp_units::pow<2>(angstrom);",
        "constexpr auto ROOT = mp_units::sqrt(m);",
        "constexpr auto ENERGY = eV;",
        "constexpr auto LENGTH = mstd::units::angstrom;",
        "constexpr mp_units::si::metre LENGTH = m;",
        "void f() { constexpr auto FORCE = eV / angstrom; }",
        "struct S { static constexpr auto FORCE = eV / angstrom; };",
        "namespace pq { constexpr auto FORCE = eV / angstrom; }",
    ],
)
def test_flagged(tmp_path: Path, code: str) -> None:
    """Unit aliases are flagged exactly once.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    diagnostics = _run(tmp_path, code)
    assert len(diagnostics) == 1
    assert diagnostics[0].check_id == "noUnitAlias"
    assert "only gives a unit a new name" in diagnostics[0].message


@pytest.mark.parametrize(
    "code",
    [
        "constexpr auto CUTOFF = 9.0 * angstrom;",
        (
            "using Distance = mp_units::quantity<struct mstd::units::angstrom>;\n"
            "constexpr Distance D = 2.0 * angstrom;"
        ),
        "auto unit = eV / angstrom;",
        "const auto &unit = eV;",
        "constexpr auto SPEC = mp_units::isq::length / mp_units::isq::time;",
        "constexpr auto W = other::w;",
        "constexpr auto LENGTH = mp_units::id(m);",
        "constexpr int N = 3 * 4;",
        "constexpr double X = 1.0 / 3.0;",
        "double f(); const double y = f();",
        "void g(double v) { const auto q = v * angstrom; }",
        "double h(); const auto q = h() * angstrom;",
        "constexpr bool B = 1 < 2;",
        "constexpr auto COMMA = (0, m);",
        "constexpr auto PICK = true ? m : m;",
    ],
)
def test_not_flagged(tmp_path: Path, code: str) -> None:
    """Quantities, non-const variables and other types are not flagged.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    assert _run(tmp_path, code) == []


def test_reports_variable_location(tmp_path: Path) -> None:
    """The diagnostic points at the variable's name."""
    code = "constexpr auto ASE_FORCE = eV / angstrom;\n"
    diagnostics = _run(tmp_path, code)
    line = _UNITS.count("\n") + 1
    assert [(d.line, d.column) for d in diagnostics] == [(line, 16)]
    assert "'ASE_FORCE'" in diagnostics[0].message


def test_custom_unit_namespaces(tmp_path: Path) -> None:
    """Only the configured namespaces count as unit namespaces."""
    code = "constexpr auto W = other::w;\nconstexpr auto F = eV / angstrom;\n"
    diagnostics = _run(tmp_path, code, {"unit_namespaces": ["::other"]})
    assert len(diagnostics) == 1
    assert "'W'" in diagnostics[0].message


def test_nested_unit_namespace(tmp_path: Path) -> None:
    """A namespace nested in a configured one is a unit namespace too."""
    diagnostics = _run(
        tmp_path, "constexpr auto L = m;", {"unit_namespaces": ["mp_units"]}
    )
    assert len(diagnostics) == 1
    assert _run(tmp_path, "constexpr auto L = m;", {"unit_namespaces": ["mp"]}) == []


def test_custom_quantity_types(tmp_path: Path) -> None:
    """Types listed in ``quantity_types`` are never unit aliases."""
    code = "constexpr auto F = eV / angstrom;"
    assert _run(tmp_path, code, {"quantity_types": ["derived_unit"]}) == []


def test_exclude_paths(tmp_path: Path) -> None:
    """``exclude_paths`` skips the header that defines the units."""
    (check,) = configure_checks(
        [NoUnitAlias()], {"noUnitAlias": {"exclude_paths": ["*units.hpp"]}}
    )
    content = _UNITS + "constexpr auto F = eV / angstrom;"
    for name, expected in (("units.hpp", 0), ("output.cpp", 1)):
        source = tmp_path / name
        source.write_text(content)
        diagnostics = run_ast_checks(source, content, ["-std=c++23"], checks=[check])
        assert len(diagnostics) == expected


@pytest.mark.parametrize(
    ("config", "key"),
    [
        ({"unit_namespaces": "mp_units"}, "unit_namespaces"),
        ({"unit_namespaces": [1]}, "unit_namespaces"),
        ({"unit_namespaces": [""]}, "unit_namespaces"),
        ({"quantity_types": "quantity"}, "quantity_types"),
        ({"quantity_types": [None]}, "quantity_types"),
    ],
)
def test_invalid_config(config: dict, key: str) -> None:
    """Malformed configuration raises ConfigError.

    Parameters
    ----------
    config: dict
        The invalid configuration.
    key: str
        The key named in the error message.

    """
    with pytest.raises(ConfigError, match=key):
        NoUnitAlias().configure(config)
