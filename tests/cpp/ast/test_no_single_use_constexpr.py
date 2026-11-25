"""Tests for the NoSingleUseConstexpr AST check via the shared engine."""

from __future__ import annotations

import typing

import pytest

from devops.config.base import ConfigError
from devops.cpp.ast.checks.no_single_use_constexpr import NoSingleUseConstexpr
from devops.cpp.ast.engine import run_ast_checks
from devops.cpp.ast.registry import configure_checks

if typing.TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("clang.cindex")


def _run(
    tmp_path: Path,
    code: str,
    name: str = "example.cpp",
    config: dict | None = None,
) -> list:
    check = NoSingleUseConstexpr()
    check.configure(config or {})
    source = tmp_path / name
    source.write_text(code)
    diagnostics = run_ast_checks(source, code, ["-std=c++23"], checks=[check])
    return [d for d in diagnostics if d.check_id == "noSingleUseConstexpr"]


@pytest.mark.parametrize(
    "code",
    [
        "constexpr int N = 3;",
        "constexpr int N = 3; int f() { return N; }",
        "namespace ns { constexpr int N = 3; int f() { return N; } }",
        "namespace { constexpr int N = 3; int f() { return N; } }",
        "namespace a::b { constexpr double PI = 3.14; double f() { return PI; } }",
        "static constexpr int N = 3; int f() { return N; }",
        "inline constexpr int N = 3; int f() { return N; }",
        "[[maybe_unused]] constexpr int N = 3;",
        'constexpr auto NAME = "x"; const char *f() { return NAME; }',
        "constexpr int N = 3; int a[N];",
        "constexpr int N = 3; template <int I> struct S {}; S<N> s;",
        "constexpr int N = 3; static_assert(N == 3);",
        "constexpr int N = 3; template <typename T> T f() { return T(N); }",
        "#define GET(x) (x)\nconstexpr int N = 3; int f() { return GET(N); }",
    ],
)
def test_flagged(tmp_path: Path, code: str) -> None:
    """A namespace-scope constexpr used at most once is flagged once.

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
        "constexpr int N = 3; int f() { return N + N; }",
        "constexpr int N = 3; int f() { return N; } int g() { return N; }",
        "namespace { constexpr int N = 3; int f(int x = N) { return x * N; } }",
        "constexpr int N = 3; int a[N]; int b[N];",
        "const int N = 3; int f() { return N; }",
        "int N = 3; int f() { return N; }",
        "constinit int N = 3; int f() { return N; }",
        "struct S { static constexpr int N = 3; }; int f() { return S::N; }",
        "int f() { constexpr int N = 3; return N; }",
        "constexpr int f() { return 3; } int g() { return f(); }",
        "#define DEF(name) constexpr int name = 3;\nDEF(N)",
        "#define DEF constexpr int N = 3;\nDEF",
    ],
)
def test_allowed(tmp_path: Path, code: str) -> None:
    """Variables used twice, non-constexpr, non-namespace and macro cases pass.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    assert _run(tmp_path, code) == []


def test_diagnostic_location_and_message(tmp_path: Path) -> None:
    """The diagnostic sits at the variable name and states the use count.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = "namespace ns {\nconstexpr int MAX_ELEMENT = 118;\n}\n"
    diagnostics = _run(tmp_path, code)
    assert [(d.line, d.column) for d in diagnostics] == [(2, 15)]
    assert "'MAX_ELEMENT'" in diagnostics[0].message
    assert "used 0 time(s)" in diagnostics[0].message


def test_each_variable_reported(tmp_path: Path) -> None:
    """Every offending variable in a file gets its own diagnostic.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = (
        "constexpr int NO_ELEMENT = 0;\n"
        "constexpr int MAX_ELEMENT = 118;\n"
        "constexpr int KEEP = 1;\n"
        "bool valid(int z) { return z > NO_ELEMENT && z <= MAX_ELEMENT; }\n"
        "int twice() { return KEEP + KEEP; }\n"
    )
    assert [d.line for d in _run(tmp_path, code)] == [1, 2]


@pytest.mark.parametrize("name", ["example.hpp", "example.h", "example.tpp"])
def test_header_is_skipped(tmp_path: Path, name: str) -> None:
    """Variables declared in a header are never flagged.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    name: str
        The header file name.

    """
    assert _run(tmp_path, "#pragma once\nconstexpr int N = 3;\n", name) == []


@pytest.mark.parametrize("name", ["example.cc", "example.cxx"])
def test_other_source_suffixes(tmp_path: Path, name: str) -> None:
    """Other source file suffixes are checked like ``.cpp``.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    name: str
        The source file name.

    """
    assert len(_run(tmp_path, "constexpr int N = 3;\n", name)) == 1


def test_included_header_variable_not_reported(tmp_path: Path) -> None:
    """A constexpr from an included header is not reported for the source file.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    (tmp_path / "consts.hpp").write_text("#pragma once\nconstexpr int N = 3;\n")
    code = '#include "consts.hpp"\nint f() { return N; }\n'
    assert _run(tmp_path, code) == []


@pytest.mark.parametrize(
    ("max_uses", "flagged"),
    [(0, [1]), (1, [1, 2]), (2, [1, 2, 3])],
)
def test_max_uses(tmp_path: Path, max_uses: int, flagged: list[int]) -> None:
    """``max_uses`` sets the highest use count that is still flagged.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    max_uses: int
        The configured limit.
    flagged: list[int]
        Lines expected to be flagged.

    """
    code = (
        "constexpr int A = 0;\n"
        "constexpr int B = 1;\n"
        "constexpr int C = 2;\n"
        "int f() { return B + C + C; }\n"
    )
    diagnostics = _run(tmp_path, code, config={"max_uses": max_uses})
    assert [d.line for d in diagnostics] == flagged


@pytest.mark.parametrize("value", [-1, "1", 1.5, True, None])
def test_invalid_max_uses(value: object) -> None:
    """A non-integer or negative ``max_uses`` is rejected.

    Parameters
    ----------
    value: object
        The invalid configured value.

    """
    with pytest.raises(ConfigError, match="max_uses"):
        NoSingleUseConstexpr().configure({"max_uses": value})


def test_exclude_paths(tmp_path: Path) -> None:
    """Files matched by ``exclude_paths`` are not checked.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    (tmp_path / "gen").mkdir()
    source = tmp_path / "gen" / "table.cpp"
    code = "constexpr int N = 3;\n"
    source.write_text(code)
    checks = configure_checks(
        [NoSingleUseConstexpr()],
        {"noSingleUseConstexpr": {"exclude_paths": ["gen/"]}},
    )
    assert run_ast_checks(source, code, ["-std=c++23"], checks=checks) == []
    assert len(_run(tmp_path, code)) == 1
