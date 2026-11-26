"""Forbid ``const``/``constexpr`` variables that only give a unit a new name.

A line like ``constexpr auto ASE_FORCE = eV / angstrom;`` hides the unit
behind a name the reader has to look up; ``force.numerical_value_in(eV /
angstrom)`` says the same thing in place. A variable is flagged if

- its type is ``const`` (``constexpr`` included) and not a reference,
- its type, after resolving ``auto`` and aliases, is declared in one of the
  ``unit_namespaces`` (default ``mp_units`` and ``mstd::units``) and is not
  one of the ``quantity_types`` (``quantity``, ``quantity_point``,
  ``derived_quantity_spec``), so ``9.0 * angstrom`` stays allowed,
- and its initializer only combines names and literals with ``*``, ``/``,
  parentheses and the unit helpers ``pow``, ``sqrt``, ``cbrt``, ``square``,
  ``cubic`` and ``inverse``.

The header that defines a project's units on purpose (PQ's
``utilities/units.hpp``) is skipped with ``exclude_paths``.

Configure via the project TOML file::

    [cpp.ast_check_config.noUnitAlias]
    unit_namespaces = ["mp_units", "mstd::units"]
    quantity_types = ["quantity", "quantity_point", "derived_quantity_spec"]
    exclude_paths = ["include/utilities/units.hpp"]
"""

from __future__ import annotations

import clang.cindex as clang

from devops.config.base import ConfigError
from devops.cpp.ast.base import Check, Diagnostic

_DEFAULT_UNIT_NAMESPACES = ("mp_units", "mstd::units")
_DEFAULT_QUANTITY_TYPES = ("quantity", "quantity_point", "derived_quantity_spec")

_UNIT_CALLS = frozenset(
    ("operator*", "operator/", "pow", "sqrt", "cbrt", "square", "cubic", "inverse")
)

_LEAF_KINDS = frozenset(
    (
        clang.CursorKind.DECL_REF_EXPR,
        clang.CursorKind.INTEGER_LITERAL,
        clang.CursorKind.FLOATING_LITERAL,
    )
)

_WRAPPER_KINDS = frozenset(
    (clang.CursorKind.UNEXPOSED_EXPR, clang.CursorKind.PAREN_EXPR)
)

_ARITHMETIC_TOKENS = frozenset(("*", "/"))


def _binary_operator(cursor: clang.Cursor, lhs: clang.Cursor) -> str | None:
    """Return the spelling of the builtin binary operator after `lhs`."""
    end = lhs.extent.end.offset
    for token in cursor.get_tokens():
        if token.extent.start.offset >= end:
            return token.spelling
    return None


def _combines_units(cursor: clang.Cursor, children: list[clang.Cursor]) -> bool:
    """Return whether `cursor` combines its operands the way units combine."""
    if cursor.kind in _WRAPPER_KINDS:
        return True
    if cursor.kind == clang.CursorKind.BINARY_OPERATOR:
        return _binary_operator(cursor, children[0]) in _ARITHMETIC_TOKENS
    if cursor.kind == clang.CursorKind.CALL_EXPR:
        referenced = cursor.referenced
        is_copy = (
            referenced is not None
            and referenced.kind == clang.CursorKind.CONSTRUCTOR
            and len(children) == 1
        )
        return is_copy or cursor.spelling in _UNIT_CALLS
    return False


def _is_unit_expression(cursor: clang.Cursor) -> bool:
    """Return whether `cursor` only combines names and literals like a unit.

    Parameters
    ----------
    cursor: clang.Cursor
        An expression cursor.

    Returns
    -------
    bool
        True if the expression is built from names and literals with ``*``,
        ``/``, parentheses, copies and the unit helper calls only.

    """
    if cursor.kind in _LEAF_KINDS:
        return True
    children = list(cursor.get_children())
    return (
        bool(children)
        and _combines_units(cursor, children)
        and all(_is_unit_expression(child) for child in children)
    )


def _namespace_of(decl: clang.Cursor) -> str:
    """Return the ``::``-joined namespace that encloses `decl`."""
    names: list[str] = []
    parent = decl.semantic_parent
    while parent is not None and parent.kind != clang.CursorKind.TRANSLATION_UNIT:
        if parent.kind == clang.CursorKind.NAMESPACE:
            names.append(parent.spelling)
        parent = parent.semantic_parent
    return "::".join(reversed(names))


def _in_namespaces(namespace: str, namespaces: tuple[str, ...]) -> bool:
    """Return whether `namespace` is one of `namespaces` or nested in one."""
    return any(
        namespace == name or namespace.startswith(f"{name}::") for name in namespaces
    )


def _initializer(cursor: clang.Cursor) -> clang.Cursor | None:
    """Return the initializer expression of a variable, if it has one."""
    expressions = [c for c in cursor.get_children() if c.kind.is_expression()]
    return expressions[-1] if expressions else None


def _string_list(check_id: str, config: dict, key: str, default: tuple) -> tuple:
    """Read the list of strings `key` from `config`.

    Raises
    ------
    ConfigError
        If the value is not a list of non-empty strings.

    """
    value = config.get(key, list(default))
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        msg = f"{check_id}: '{key}' must be a list of non-empty strings, got {value!r}"
        raise ConfigError(msg)
    return tuple(value)


class NoUnitAlias(Check):
    """Flag ``const``/``constexpr`` variables that only alias a unit."""

    id = "noUnitAlias"

    def __init__(self) -> None:
        """Initialise with the default unit namespaces and quantity types."""
        self.unit_namespaces = _DEFAULT_UNIT_NAMESPACES
        self.quantity_types = _DEFAULT_QUANTITY_TYPES

    def configure(self, config: dict) -> None:
        """Load ``unit_namespaces`` and ``quantity_types`` from the TOML block.

        Parameters
        ----------
        config: dict
            Expected shape: ``{"unit_namespaces": [str], "quantity_types":
            [str]}``; both keys are optional.

        """
        self.unit_namespaces = tuple(
            name.removeprefix("::")
            for name in _string_list(
                self.id, config, "unit_namespaces", _DEFAULT_UNIT_NAMESPACES
            )
        )
        self.quantity_types = _string_list(
            self.id, config, "quantity_types", _DEFAULT_QUANTITY_TYPES
        )

    def _is_unit_type(self, ty: clang.Type) -> bool:
        """Return whether `ty` is a unit type from one of the unit namespaces."""
        decl = ty.get_canonical().get_declaration()
        if decl.kind == clang.CursorKind.NO_DECL_FOUND:
            return False
        if decl.spelling in self.quantity_types:
            return False
        return _in_namespaces(_namespace_of(decl), self.unit_namespaces)

    def visit(self, cursor: clang.Cursor, filename: str) -> list[Diagnostic]:
        """Flag `cursor` if it is a ``const`` variable that only names a unit.

        Parameters
        ----------
        cursor: clang.Cursor
            The AST node currently being visited.
        filename: str
            Path of the file being checked.

        Returns
        -------
        list[Diagnostic]
            A single diagnostic at the variable's name if it is a unit
            alias, otherwise an empty list.

        """
        if cursor.kind != clang.CursorKind.VAR_DECL:
            return []
        ty = cursor.type
        if not ty.is_const_qualified() or not self._is_unit_type(ty):
            return []
        init = _initializer(cursor)
        if init is None or not _is_unit_expression(init):
            return []
        return [
            Diagnostic(
                file=filename,
                line=cursor.location.line,
                column=cursor.location.column,
                message=(
                    f"variable '{cursor.spelling}' only gives a unit a new name; "
                    "write the unit where it is used instead"
                ),
                check_id=self.id,
            )
        ]
