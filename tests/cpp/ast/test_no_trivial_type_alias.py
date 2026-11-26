"""Tests for the NoTrivialTypeAlias AST check via the shared engine."""

from __future__ import annotations

import typing

import pytest

from devops.config.base import ConfigError
from devops.cpp.ast.checks.no_trivial_type_alias import NoTrivialTypeAlias
from devops.cpp.ast.engine import run_ast_checks
from devops.cpp.ast.registry import configure_checks

if typing.TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("clang.cindex")

# A small stand-in for the standard library keeps each parse fast; the
# real headers are covered once in `test_real_standard_headers`.
_STD = (
    "#pragma once\n"
    "namespace std {\n"
    "using size_t = decltype(sizeof 0);\n"
    "using uint64_t = unsigned long long;\n"
    "using ptrdiff_t = long;\n"
    "class string {};\n"
    "struct input_iterator_tag {};\n"
    "template <typename T> class vector {};\n"
    "template <typename T, size_t N> struct array {};\n"
    "template <typename K, typename V> class map {};\n"
    "template <typename F> class function {};\n"
    "template <typename T> class unique_ptr {};\n"
    "}\n"
    "struct Atom {};\n"
)


def _run(
    tmp_path: Path,
    code: str,
    config: dict | None = None,
    name: str = "example.cpp",
) -> list:
    check = NoTrivialTypeAlias()
    check.configure(config or {})
    (tmp_path / "std_stub.hpp").write_text(_STD)
    source = tmp_path / name
    content = '#include "std_stub.hpp"\n' + code
    source.write_text(content)
    diagnostics = run_ast_checks(source, content, ["-std=c++23"], checks=[check])
    return [d for d in diagnostics if d.check_id == "noTrivialTypeAlias"]


@pytest.mark.parametrize(
    "code",
    [
        "using Shape = std::vector<std::size_t>;",
        "typedef std::vector<std::size_t> Shape;",
        "using Real = double;",
        "typedef int Index;",
        "using Index = std::size_t;",
        "using Id = std::uint64_t;",
        "using Name = std::string;",
        "using Vec3 = std::array<double, 3>;",
        "using Table = std::map<int, std::string>;",
        "using Grid = std::vector<std::vector<double>>;",
        "using Cb = std::function<void(int)>;",
        "using Cb = void (*)(double);",
        "using Ptr = const double *;",
        "using Buf = char[16];",
        "using Owner = std::unique_ptr<int>;",
        "namespace pq { using Shape = std::vector<std::size_t>; }",
        "struct S { using Shape = std::vector<std::size_t>; };",
        "using value_type = double;",
        "void f() { using type = int; }",
        "template <typename T> struct S { using Count = std::size_t; };",
        "void f() { using L = int; }",
        "void f() { typedef double L; }",
    ],
)
def test_flagged(tmp_path: Path, code: str) -> None:
    """Aliases of builtin and std types are flagged exactly once.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    diagnostics = _run(tmp_path, code)
    assert len(diagnostics) == 1


@pytest.mark.parametrize(
    "code",
    [
        "using A = Atom;",
        "using Atoms = std::vector<Atom>;",
        "using AtomPtr = std::unique_ptr<Atom>;",
        "using ById = std::map<int, Atom>;",
        "using Cb = std::function<void(const Atom &)>;",
        "using Cb = void (*)(Atom *);",
        "using M = int Atom::*;",
        "template <typename T> using Vec = std::vector<T>;",
        "template <typename T> using Count = std::size_t;",
        "template <typename T> struct S { using V = T; };",
        "template <typename T> struct S { using W = std::vector<T>; };",
        "template <typename T> struct S { typedef T *P; };",
        "typedef struct { int a; } Pod;",
        "struct It { using iterator_category = std::input_iterator_tag; };",
        "template <typename T> struct Tr { using type = std::ptrdiff_t; };",
        "template <typename T> struct Tr<T *> { using type = std::ptrdiff_t; };",
        "struct V { using value_type = double; using size_type = std::size_t; };",
        "enum class E { a }; using F = E;",
        "#define ALIAS(name) using name = int;\nALIAS(Generated)",
    ],
)
def test_allowed(tmp_path: Path, code: str) -> None:
    """Project types, templates, alias templates and macros are not flagged.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    assert _run(tmp_path, code) == []


def test_real_standard_headers(tmp_path: Path) -> None:
    """Real std and C typedefs are trivial, project arguments are not.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = (
        "#include <cstddef>\n"
        "#include <cstdint>\n"
        "#include <string>\n"
        "#include <vector>\n"
        "struct Atom {};\n"
        "using A = size_t;\n"
        "using B = uint64_t;\n"
        "using C = std::uint64_t;\n"
        "using D = std::vector<std::size_t>;\n"
        "using E = std::string;\n"
        "using F = std::vector<Atom>;\n"
        "template <typename T> struct S { using G = std::vector<T>; };\n"
    )
    source = tmp_path / "real.cpp"
    source.write_text(code)
    diagnostics = run_ast_checks(
        source, code, ["-std=c++23"], checks=[NoTrivialTypeAlias()]
    )
    names = [d.message.split("'")[1] for d in diagnostics]
    assert names == ["A", "B", "C", "D", "E"]


def test_alias_of_alias_is_not_reported(tmp_path: Path) -> None:
    """An alias of an alias is not reported, the original one is.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = "using Shape = std::vector<std::size_t>;\nusing Dims = Shape;\n"
    diagnostics = _run(tmp_path, code)
    assert [d.line for d in diagnostics] == [2]


def test_message(tmp_path: Path) -> None:
    """The message names the keyword, the alias and its target.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    (diagnostic,) = _run(tmp_path, "typedef std::vector<std::size_t> Shape;")
    assert "typedef alias 'Shape'" in diagnostic.message
    assert "'std::vector<std::size_t>'" in diagnostic.message
    (diagnostic,) = _run(tmp_path, "using Real = double;")
    assert "using alias 'Real' only renames 'double'" in diagnostic.message


@pytest.mark.parametrize(
    ("code", "allowed"),
    [
        ("using Real = double;", ["Real"]),
        ("namespace pq { using Real = double; }", ["Real"]),
        ("namespace pq { using Real = double; }", ["pq::Real"]),
        ("namespace pq { using Real = double; }", ["::pq::Real"]),
        ("struct S { using Count = std::size_t; };", ["S::Count"]),
    ],
)
def test_allowed_names(tmp_path: Path, code: str, allowed: list[str]) -> None:
    """Names in ``allowed_names`` are exempt, unqualified or qualified.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.
    allowed: list[str]
        The configured ``allowed_names``.

    """
    assert _run(tmp_path, code) != []
    assert _run(tmp_path, code, {"allowed_names": allowed}) == []


def test_allowed_names_do_not_exempt_others(tmp_path: Path) -> None:
    """Only the listed names are exempt.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = "namespace pq { using Real = double; using Index = int; }"
    diagnostics = _run(tmp_path, code, {"allowed_names": ["other::Real", "Real"]})
    assert ["'Index'" in d.message for d in diagnostics] == [True]


def test_header_is_checked(tmp_path: Path) -> None:
    """Headers are checked like source files.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    diagnostics = _run(tmp_path, "using Real = double;\n", name="a.hpp")
    assert len(diagnostics) == 1


def test_included_header_is_not_reported(tmp_path: Path) -> None:
    """Aliases from an included header are not reported for the main file.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    (tmp_path / "api.hpp").write_text("#pragma once\nusing Real = double;\n")
    assert _run(tmp_path, '#include "api.hpp"\nusing A = Atom;\n') == []


def test_exclude_paths(tmp_path: Path) -> None:
    """The shared ``exclude_paths`` key skips matching files.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    source = legacy / "a.cpp"
    code = "using Real = double;\n"
    source.write_text(code)
    (check,) = configure_checks(
        [NoTrivialTypeAlias()],
        {"noTrivialTypeAlias": {"exclude_paths": ["legacy/"]}},
    )
    assert run_ast_checks(source, code, ["-std=c++23"], checks=[check]) == []


def test_default_config() -> None:
    """No names are allowed by default."""
    assert NoTrivialTypeAlias().allowed_names == frozenset()


@pytest.mark.parametrize(
    "config",
    [
        {"allowed_names": "Real"},
        {"allowed_names": [1]},
        {"allowed_names": None},
    ],
)
def test_invalid_config(config: dict) -> None:
    """Malformed configuration raises ConfigError.

    Parameters
    ----------
    config: dict
        The invalid configuration.

    """
    with pytest.raises(ConfigError, match="allowed_names"):
        NoTrivialTypeAlias().configure(config)
