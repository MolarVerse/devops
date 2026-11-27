"""Flag namespace-scope ``constexpr`` variables that are used only once.

A global such as ``constexpr int NO_ELEMENT = 0;`` that is referenced a
single time adds a name without adding meaning: the value can be written
where it is used (or as a local constant). A ``constexpr`` variable is
flagged when

- it is declared at namespace scope (the global namespace, a named or an
  anonymous namespace) of a source file (``.cpp``, ``.cc``, ``.cxx``,
  ``.c++``), and
- it is referenced at most ``max_uses`` times in that file.

AST checks see one translation unit at a time, so only references in the
file being checked are counted. Variables declared in headers are never
flagged because they may be used by other files. Class members, local
variables and variables whose name comes from a macro expansion are not
checked.

Configure the limit via the project TOML file::

    [cpp.ast_check_config.noSingleUseConstexpr]
    max_uses = 1
"""

from __future__ import annotations

import typing
from pathlib import Path

import clang.cindex as clang

from devops.config.base import ConfigError
from devops.cpp.ast.base import Check, Diagnostic

_DEFAULT_MAX_USES = 1

_SOURCE_SUFFIXES = frozenset((".cpp", ".cc", ".cxx", ".c++"))

_SCOPE_KINDS = frozenset(
    (clang.CursorKind.NAMESPACE, clang.CursorKind.TRANSLATION_UNIT)
)


def _is_constexpr(cursor: clang.Cursor) -> bool:
    """Return whether the variable at `cursor` is declared ``constexpr``.

    libclang does not expose the specifier, so the tokens in front of the
    variable's name are searched for the ``constexpr`` keyword.
    """
    name = cursor.location
    for token in cursor.get_tokens():
        loc = token.location
        if (loc.line, loc.column) >= (name.line, name.column):
            return False
        if token.kind == clang.TokenKind.KEYWORD and token.spelling == "constexpr":
            return True
    return False


def _key(cursor: clang.Cursor) -> str | tuple[int, int]:
    """Return an identity for `cursor` shared by its redeclarations."""
    return cursor.get_usr() or (cursor.location.line, cursor.location.column)


class _Candidate(typing.NamedTuple):
    """A namespace-scope ``constexpr`` variable found in the checked file."""

    name: str
    line: int
    column: int


def _in_ranges(line: int, column: int, ranges: list[tuple[int, int, int, int]]) -> bool:
    """Return whether ``line:column`` lies inside one of `ranges`."""
    return any(
        (start_line, start_col) <= (line, column) <= (end_line, end_col)
        for start_line, start_col, end_line, end_col in ranges
    )


class NoSingleUseConstexpr(Check):
    """Flag namespace-scope ``constexpr`` variables used at most ``max_uses`` times.

    Candidates and references are collected during the walk and compared in
    `finalize()`, once every reference in the file is known.
    """

    id = "noSingleUseConstexpr"

    def __init__(self) -> None:
        """Initialise with the default limit and empty per-file buffers."""
        self.max_uses = _DEFAULT_MAX_USES
        self._candidates: dict[str, dict[str | tuple[int, int], _Candidate]] = {}
        self._uses: dict[str, dict[str | tuple[int, int], int]] = {}
        self._macro_ranges: dict[str, list[tuple[int, int, int, int]]] = {}

    def configure(self, config: dict) -> None:
        """Load ``max_uses`` from the check's TOML config block.

        Parameters
        ----------
        config: dict
            Expected shape: ``{"max_uses": int}``; the key is optional.

        Raises
        ------
        ConfigError
            If ``max_uses`` is not a non-negative integer.

        """
        value = config.get("max_uses", _DEFAULT_MAX_USES)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            msg = f"{self.id}: 'max_uses' must be a non-negative integer, got {value!r}"
            raise ConfigError(msg)
        self.max_uses = value

    def visit(self, cursor: clang.Cursor, filename: str) -> list[Diagnostic]:
        """Record macro expansions, candidate variables and their references.

        Parameters
        ----------
        cursor: clang.Cursor
            The AST node currently being visited.
        filename: str
            Path of the file being checked.

        Returns
        -------
        list[Diagnostic]
            Always empty; diagnostics are emitted from `finalize()`.

        """
        if Path(filename).suffix.lower() not in _SOURCE_SUFFIXES:
            return []
        if cursor.kind == clang.CursorKind.MACRO_INSTANTIATION:
            start, end = cursor.extent.start, cursor.extent.end
            self._macro_ranges.setdefault(filename, []).append(
                (start.line, start.column, end.line, end.column)
            )
        elif cursor.kind == clang.CursorKind.DECL_REF_EXPR:
            referenced = cursor.referenced
            if referenced is not None and referenced.kind == clang.CursorKind.VAR_DECL:
                uses = self._uses.setdefault(filename, {})
                key = _key(referenced)
                uses[key] = uses.get(key, 0) + 1
        elif (
            cursor.kind == clang.CursorKind.VAR_DECL
            and cursor.semantic_parent is not None
            and cursor.semantic_parent.kind in _SCOPE_KINDS
            and _is_constexpr(cursor)
        ):
            candidates = self._candidates.setdefault(filename, {})
            candidates.setdefault(
                _key(cursor),
                _Candidate(
                    cursor.spelling, cursor.location.line, cursor.location.column
                ),
            )
        return []

    def finalize(self, filename: str) -> list[Diagnostic]:
        """Emit diagnostics for candidates with too few references.

        Parameters
        ----------
        filename: str
            Path of the file being checked.

        Returns
        -------
        list[Diagnostic]
            One diagnostic per ``constexpr`` variable used at most
            ``max_uses`` times in the file.

        """
        ranges = self._macro_ranges.pop(filename, [])
        uses = self._uses.pop(filename, {})
        diagnostics = []
        for key, item in self._candidates.pop(filename, {}).items():
            count = uses.get(key, 0)
            if count > self.max_uses or _in_ranges(item.line, item.column, ranges):
                continue
            diagnostics.append(
                Diagnostic(
                    file=filename,
                    line=item.line,
                    column=item.column,
                    message=(
                        f"constexpr variable '{item.name}' is used {count} "
                        f"time(s) in this file (needs more than {self.max_uses}); "
                        "write the value where it is used instead"
                    ),
                    check_id=self.id,
                )
            )
        return diagnostics
