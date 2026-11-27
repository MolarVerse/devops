"""Use one naming style for all getters of a class.

A class should name its getters either ``getX()`` or ``x()``, not both. A
getter is a non-static ``const`` member function declared in the class
body that takes no parameters and returns something other than ``void``.
Leading underscores are ignored, so private ``_getX()`` and ``_x()`` count
as well.

Each getter falls into one of two groups:

- *get-prefixed*: the name is ``get`` followed by an upper-case letter
  (``getName``, ``_getBox``);
- *plain*: any other name starting with a lower-case letter (``name``,
  ``box``).

Exempt, and therefore in neither group, are

- predicates and verbs: names starting with one of the built-in prefixes
  (``is``, ``has``, ``can``, ``should``, ``was``, ``use``, ``allow``,
  ``supports``, ``any``, ``all``, ``calculate``, ``calc``, ``compute``,
  ``check``, ``clone``, ``copy``, ``create``, ``make``, ``build``,
  ``find``, ``count``, ``flatten``, ``sort``, ``determine``, ``convert``,
  ``to``, ``as``, ``print``, ``format``, ``validate``, ``evaluate``) or a
  configured ``exempt_prefixes`` entry, followed by an upper-case letter
  or the end of the name,
- ``size``, ``empty``, ``begin``/``end`` and their ``c``/``r``/``cr``
  variants, ``get`` itself, plus any configured ``exempt_names``,
- operators and conversion functions, deleted functions and methods
  overriding a base-class virtual method (their name is fixed elsewhere),
- member function templates and methods whose name comes from a macro
  expansion.

A class with at least one getter in each group is reported once, at the
class name, listing both groups. Getters inherited from a base class or
nested classes are not part of the class's own groups.

Configure extra exemptions via the project TOML file::

    [cpp.ast_check_config.consistentGetterPrefix]
    exempt_names = ["data", "length"]
    exempt_prefixes = ["estimate", "render"]
"""

from __future__ import annotations

import typing

import clang.cindex as clang

from devops.config.base import ConfigError
from devops.cpp.ast.base import Check, Diagnostic
from devops.cpp.ast.checks.enforce_no_public_leading_underscore import (
    _overrides_base_method,
)

_RECORD_KINDS = frozenset(
    (
        clang.CursorKind.CLASS_DECL,
        clang.CursorKind.STRUCT_DECL,
        clang.CursorKind.UNION_DECL,
        clang.CursorKind.CLASS_TEMPLATE,
        clang.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
    )
)

_DEFAULT_EXEMPT_PREFIXES = (
    "is",
    "has",
    "can",
    "should",
    "was",
    "use",
    "allow",
    "supports",
    "any",
    "all",
    "calculate",
    "calc",
    "compute",
    "check",
    "clone",
    "copy",
    "create",
    "make",
    "build",
    "find",
    "count",
    "flatten",
    "sort",
    "determine",
    "convert",
    "to",
    "as",
    "print",
    "format",
    "validate",
    "evaluate",
)

_DEFAULT_EXEMPT_NAMES = frozenset(
    (
        "get",
        "size",
        "empty",
        "begin",
        "end",
        "cbegin",
        "cend",
        "rbegin",
        "rend",
        "crbegin",
        "crend",
    )
)

_GET_PREFIX = "get"


def _starts_with_word(name: str, prefix: str) -> bool:
    """Return whether `name` is `prefix`, alone or followed by an upper-case letter."""
    if not name.startswith(prefix):
        return False
    rest = name[len(prefix) :]
    return not rest or rest[0].isupper()


def _is_getter(cursor: clang.Cursor) -> bool:
    """Return whether `cursor` is a const, parameterless, non-void method.

    Parameters
    ----------
    cursor: clang.Cursor
        A direct child of a class definition.

    Returns
    -------
    bool
        True for a ``const`` member function with no parameters and a
        non-``void`` return type that is not deleted, not an operator and
        does not override a base-class method.

    """
    if cursor.kind != clang.CursorKind.CXX_METHOD:
        return False
    if not cursor.is_const_method() or cursor.spelling.startswith("operator"):
        return False
    if any(True for _ in cursor.get_arguments()):
        return False
    if cursor.result_type.kind == clang.TypeKind.VOID:
        return False
    if cursor.availability == clang.AvailabilityKind.NOT_AVAILABLE:
        return False
    return not _overrides_base_method(cursor)


class _Getter(typing.NamedTuple):
    """A getter of a class, buffered until all macro expansions are known."""

    name: str
    prefixed: bool
    line: int
    column: int


class _PendingClass(typing.NamedTuple):
    """A class with getters in both groups, before macro filtering."""

    name: str
    line: int
    column: int
    getters: list[_Getter]


def _in_ranges(line: int, column: int, ranges: list[tuple[int, int, int, int]]) -> bool:
    """Return whether ``line:column`` lies inside one of `ranges`."""
    return any(
        (start_line, start_col) <= (line, column) <= (end_line, end_col)
        for start_line, start_col, end_line, end_col in ranges
    )


def _string_list(check_id: str, config: dict, key: str) -> tuple[str, ...]:
    """Read `key` from `config` as a list of strings.

    Raises
    ------
    ConfigError
        If the value is present but is not a list of strings.

    """
    raw = config.get(key, [])
    if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
        msg = (
            f"{check_id}: '{key}' in [cpp.ast_check_config.{check_id}] "
            "must be a list of strings"
        )
        raise ConfigError(msg)
    return tuple(raw)


class ConsistentGetterPrefix(Check):
    """Flag classes mixing ``getX()`` and ``x()`` getters.

    Reporting is deferred to `finalize()` so that getters whose name comes
    from a macro expansion can be skipped once every ``MACRO_INSTANTIATION``
    of the file is known.
    """

    id = "consistentGetterPrefix"

    def __init__(self) -> None:
        """Initialise with the default exemptions and empty per-file buffers."""
        self.exempt_names: frozenset[str] = _DEFAULT_EXEMPT_NAMES
        self.exempt_prefixes: tuple[str, ...] = _DEFAULT_EXEMPT_PREFIXES
        self._macro_ranges: dict[str, list[tuple[int, int, int, int]]] = {}
        self._pending: dict[str, list[_PendingClass]] = {}

    def configure(self, config: dict) -> None:
        """Load extra ``exempt_names`` and ``exempt_prefixes`` from the TOML block.

        Parameters
        ----------
        config: dict
            Expected shape: ``{"exempt_names": ["data"],
            "exempt_prefixes": ["to"]}``; both keys are optional and extend
            the built-in defaults.

        Raises
        ------
        ConfigError
            If either key is present but is not a list of strings.

        """
        names = _string_list(self.id, config, "exempt_names")
        prefixes = _string_list(self.id, config, "exempt_prefixes")
        self.exempt_names = _DEFAULT_EXEMPT_NAMES | frozenset(names)
        self.exempt_prefixes = (*_DEFAULT_EXEMPT_PREFIXES, *prefixes)

    def _classify(self, name: str) -> bool | None:
        """Return True for a get-prefixed name, False for plain, None if exempt."""
        name = name.lstrip("_")
        if not name or not name[0].islower() or name in self.exempt_names:
            return None
        if _starts_with_word(name, _GET_PREFIX):
            return True
        if any(_starts_with_word(name, p) for p in self.exempt_prefixes):
            return None
        return False

    def visit(self, cursor: clang.Cursor, filename: str) -> list[Diagnostic]:
        """Record macro expansions and the getter groups of a class definition.

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
        if cursor.kind == clang.CursorKind.MACRO_INSTANTIATION:
            start, end = cursor.extent.start, cursor.extent.end
            self._macro_ranges.setdefault(filename, []).append(
                (start.line, start.column, end.line, end.column)
            )
            return []
        if cursor.kind not in _RECORD_KINDS or not cursor.is_definition():
            return []

        getters = []
        for child in cursor.get_children():
            if not _is_getter(child):
                continue
            prefixed = self._classify(child.spelling)
            if prefixed is None:
                continue
            loc = child.location
            getters.append(_Getter(child.spelling, prefixed, loc.line, loc.column))
        groups = {g.prefixed for g in getters}
        if True not in groups or False not in groups:
            return []

        loc = cursor.location
        self._pending.setdefault(filename, []).append(
            _PendingClass(
                cursor.spelling or "<anonymous>", loc.line, loc.column, getters
            )
        )
        return []

    def finalize(self, filename: str) -> list[Diagnostic]:
        """Emit one diagnostic per class still mixing both getter styles.

        Parameters
        ----------
        filename: str
            Path of the file being checked.

        Returns
        -------
        list[Diagnostic]
            One diagnostic per offending class, at the class name.

        """
        ranges = self._macro_ranges.pop(filename, [])
        diagnostics = []
        for record in self._pending.pop(filename, []):
            getters = [
                g for g in record.getters if not _in_ranges(g.line, g.column, ranges)
            ]
            prefixed = [f"'{g.name}'" for g in getters if g.prefixed]
            plain = [f"'{g.name}'" for g in getters if not g.prefixed]
            if not prefixed or not plain:
                continue
            diagnostics.append(
                Diagnostic(
                    file=filename,
                    line=record.line,
                    column=record.column,
                    message=(
                        f"class '{record.name}' mixes getter styles: "
                        f"get-prefixed {', '.join(prefixed)} and plain "
                        f"{', '.join(plain)}; use one style for all getters"
                    ),
                    check_id=self.id,
                )
            )
        return diagnostics
