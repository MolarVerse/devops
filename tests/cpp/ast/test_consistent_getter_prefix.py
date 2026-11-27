"""Tests for the ConsistentGetterPrefix AST check via the shared engine."""

from __future__ import annotations

import typing

import pytest

from devops.config.base import ConfigError
from devops.cpp.ast.checks.consistent_getter_prefix import ConsistentGetterPrefix
from devops.cpp.ast.engine import run_ast_checks
from devops.cpp.ast.registry import configure_checks

if typing.TYPE_CHECKING:
    from pathlib import Path

pytest.importorskip("clang.cindex")


def _run(
    tmp_path: Path, code: str, config: dict | None = None, name: str = "example.cpp"
) -> list:
    check = ConsistentGetterPrefix()
    checks = configure_checks([check], {check.id: config}) if config else [check]
    source = tmp_path / name
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(code)
    return run_ast_checks(source, code, ["-std=c++23"], checks=checks)


@pytest.mark.parametrize(
    "code",
    [
        "class C { public: int getA() const; int b() const; };",
        "struct S { int getA() const; double b() const; };",
        "struct S { int _getA() const; int _b() const; };",
        "struct S { int getA() const; int maxLength() const; };",
        "struct S { int getA() const; int calculator() const; };",
        "class C { public: int getA() const; private: int _b() const; };",
        "struct S { const int &getA() const; int *b() const; };",
        "struct S { auto getA() const { return 1; } auto b() const { return 2; } };",
        "template <typename T> struct S { T getA() const; T b() const; };",
        (
            "template <typename T> struct S {}; template <typename T> struct S<T *> "
            "{ T getA() const; T b() const; };"
        ),
        "struct S { int getA() const noexcept; int b() const &; };",
        "union U { int getA() const; int b() const; int i; };",
        (
            "struct Base { virtual int a() const; }; "
            "struct D : Base { int getB() const; int c() const; };"
        ),
        "struct S { int getA() const; int b() const; struct In { int c() const; }; };",
        (
            "#define DECL(n) int n() const;\nstruct S { int getA() const; "
            "int b() const; DECL(c) };"
        ),
    ],
)
def test_flagged(tmp_path: Path, code: str) -> None:
    """A class mixing ``getX()`` and ``x()`` getters is flagged once.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    diagnostics = _run(tmp_path, code)
    assert len(diagnostics) == 1
    assert diagnostics[0].check_id == "consistentGetterPrefix"


@pytest.mark.parametrize(
    "code",
    [
        "struct S { int getA() const; int getB() const; };",
        "struct S { int a() const; int b() const; };",
        # Not const, has parameters, returns void or is static: not a getter.
        "struct S { int getA() const; int b(); };",
        "struct S { int getA() const; int b(int i) const; };",
        "struct S { int getA() const; void b() const; };",
        "struct S { int getA() const; static int b(); };",
        # Exempt names and prefixes.
        (
            "struct S { int getA() const; bool isB() const; bool hasC() const; "
            "bool canD() const; bool shouldE() const; };"
        ),
        (
            "struct S { int getA() const; int size() const; bool empty() const; "
            "int *begin() const; int *end() const; int *cbegin() const; "
            "int *crend() const; };"
        ),
        "struct S { int getA() const; int *get() const; };",
        (
            "struct S { int getA() const; S *clone() const; "
            "double calculateB() const; bool useC() const; int toInt() const; "
            "bool _anyD() const; bool wasE() const; int computeF() const; };"
        ),
        (
            "struct S { int getA() const; explicit operator bool() const; "
            "bool operator==(const S &) const; int operator*() const; };"
        ),
        "struct S { int getA() const; int _B() const; };",
        "struct S { int getA() const; int b() const = delete; };",
        (
            "struct Base { virtual int b() const; }; "
            "struct D : Base { int getA() const; int b() const override; };"
        ),
        "struct S { int getA() const; template <typename T> T as() const; };",
        # `getter` and `issue` are not the `get`/`is` prefix.
        "struct S { int getter() const; int issue() const; };",
        # Nested classes are separate.
        "struct S { int getA() const; struct In { int b() const; }; };",
        # Getters from a macro do not count.
        "#define DECL(n) int n() const;\nstruct S { int getA() const; DECL(b) };",
        # Out-of-line definitions are not class-body declarations.
        "struct S { int getA() const; }; int S::getA() const { return 1; }",
        "struct S; int f();",
    ],
)
def test_not_flagged(tmp_path: Path, code: str) -> None:
    """Consistent classes and non-getters are not flagged.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.
    code: str
        The C++ code under test.

    """
    assert _run(tmp_path, code) == []


def test_message_and_location(tmp_path: Path) -> None:
    """The diagnostic sits at the class name and lists both groups.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = (
        "namespace ns {\n"
        "class Box {\n"
        "  public:\n"
        "    int getA() const;\n"
        "    int b() const;\n"
        "    int getC() const;\n"
        "    bool isD() const;\n"
        "};\n"
        "}\n"
    )
    (diagnostic,) = _run(tmp_path, code)
    assert (diagnostic.line, diagnostic.column) == (2, 7)
    assert diagnostic.message == (
        "class 'Box' mixes getter styles: get-prefixed 'getA', 'getC' and "
        "plain 'b'; use one style for all getters"
    )


def test_header(tmp_path: Path) -> None:
    """Classes in headers are checked too.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = "#pragma once\nstruct S { int getA() const; int b() const; };\n"
    assert len(_run(tmp_path, code, name="example.hpp")) == 1


def test_exempt_names(tmp_path: Path) -> None:
    """Configured ``exempt_names`` are added to the defaults.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = "struct S { int getA() const; int *data() const; int size() const; };"
    assert len(_run(tmp_path, code)) == 1
    assert _run(tmp_path, code, {"exempt_names": ["data"]}) == []


def test_exempt_prefixes(tmp_path: Path) -> None:
    """Configured ``exempt_prefixes`` are added to the defaults.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = "struct S { int getA() const; int estimateB() const; bool isB() const; };"
    assert len(_run(tmp_path, code)) == 1
    assert _run(tmp_path, code, {"exempt_prefixes": ["estimate"]}) == []


def test_exclude_paths(tmp_path: Path) -> None:
    """Files matching ``exclude_paths`` are skipped.

    Parameters
    ----------
    tmp_path: Path
        Temporary path for creating test files.

    """
    code = "struct S { int getA() const; int b() const; };"
    config = {"exclude_paths": ["legacy/"]}
    assert _run(tmp_path, code, config, name="legacy/a.cpp") == []
    assert len(_run(tmp_path, code, config, name="src/a.cpp")) == 1


@pytest.mark.parametrize(
    "config",
    [
        {"exempt_names": "data"},
        {"exempt_names": [1]},
        {"exempt_prefixes": "to"},
        {"exempt_prefixes": [None]},
    ],
)
def test_invalid_config(config: dict) -> None:
    """Non-list or non-string options raise a ConfigError.

    Parameters
    ----------
    config: dict
        The invalid config table.

    """
    with pytest.raises(ConfigError):
        ConsistentGetterPrefix().configure(config)
