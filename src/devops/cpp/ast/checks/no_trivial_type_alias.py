"""Forbid type aliases that only rename a builtin or standard library type.

``using Shape = std::vector<std::size_t>;`` adds a name but no meaning: the
reader still has to look it up, and nothing stops a ``Shape`` from being
mixed with any other ``std::vector<std::size_t>``. Such an alias is flagged
if it is a non-template ``using X = T;`` or ``typedef T X;`` (at namespace,
class or function scope) and its target ``T``, as written, is built only
from

- builtin types (``int``, ``double``, ``bool``, ``void``, ...),
- types declared in namespace ``std`` (``std::size_t``, ``std::string``,
  ``std::vector<...>``, ...), with every template argument again trivial,
- the C standard typedefs ``size_t``, ``ptrdiff_t``, ``intN_t``,
  ``uintN_t``, ``intptr_t``, ... from a system header,
- pointers, references, arrays and function types of the above.

Not flagged:

- alias templates (``template <typename T> using Vec = std::vector<T>;``),
- aliases whose target names a project type, another alias or a template
  parameter anywhere (``std::vector<Atom>``, ``std::vector<T>``, ``Shape``),
- class members named as the standard library requires (``value_type``,
  ``iterator_category``, ``type``, ...; see ``_PROTOCOL_NAMES``),
- aliases whose name comes from a macro expansion,
- names listed in ``allowed_names`` (unqualified or fully qualified).

Configure exemptions via the project TOML file::

    [cpp.ast_check_config.noTrivialTypeAlias]
    allowed_names = ["Real", "pq::Index"]
"""

from __future__ import annotations

import re
import typing

import clang.cindex as clang

from devops.config.base import ConfigError
from devops.cpp.ast.base import Check, Diagnostic

_ALIAS_KINDS = frozenset(
    (clang.CursorKind.TYPE_ALIAS_DECL, clang.CursorKind.TYPEDEF_DECL)
)

_BUILTIN_KIND_NAMES = frozenset(
    (
        "VOID",
        "BOOL",
        "CHAR_U",
        "UCHAR",
        "CHAR16",
        "CHAR32",
        "CHAR8",
        "USHORT",
        "UINT",
        "ULONG",
        "ULONGLONG",
        "UINT128",
        "CHAR_S",
        "SCHAR",
        "WCHAR",
        "SHORT",
        "INT",
        "LONG",
        "LONGLONG",
        "INT128",
        "FLOAT",
        "DOUBLE",
        "LONGDOUBLE",
        "NULLPTR",
        "FLOAT128",
        "HALF",
        "FLOAT16",
        "IBM128",
    )
)

_WRAPPER_KINDS = frozenset(
    (
        clang.TypeKind.POINTER,
        clang.TypeKind.LVALUEREFERENCE,
        clang.TypeKind.RVALUEREFERENCE,
    )
)

_ARRAY_KINDS = frozenset(
    (
        clang.TypeKind.CONSTANTARRAY,
        clang.TypeKind.INCOMPLETEARRAY,
    )
)

_CLASS_KINDS = frozenset(
    (
        clang.CursorKind.CLASS_DECL,
        clang.CursorKind.STRUCT_DECL,
        clang.CursorKind.UNION_DECL,
        clang.CursorKind.CLASS_TEMPLATE,
        clang.CursorKind.CLASS_TEMPLATE_PARTIAL_SPECIALIZATION,
    )
)

# Member aliases whose name the standard library expects (iterator, container,
# allocator and type-trait protocols), so they cannot be replaced by the type.
_PROTOCOL_NAMES = frozenset(
    (
        "type",
        "value_type",
        "element_type",
        "size_type",
        "difference_type",
        "pointer",
        "const_pointer",
        "reference",
        "const_reference",
        "iterator_category",
        "iterator_concept",
        "is_transparent",
        "propagate_on_container_move_assignment",
        "is_always_equal",
    )
)

_DECLARED_KINDS = frozenset(
    (
        clang.TypeKind.TYPEDEF,
        clang.TypeKind.RECORD,
        clang.TypeKind.ENUM,
        clang.TypeKind.UNEXPOSED,
    )
)

_C_TYPEDEF = re.compile(
    r"(u?int(_least|_fast)?(8|16|32|64)_t|u?int(max|ptr)_t"
    r"|s?size_t|ptrdiff_t|max_align_t|nullptr_t)"
)

_CV = re.compile(r"\b(const|volatile)\b")

_MAX_DEPTH = 32


def _in_std(decl: clang.Cursor) -> bool:
    """Return whether `decl` is declared (at any depth) inside namespace ``std``."""
    outermost = None
    parent = decl.semantic_parent
    while parent is not None and parent.kind != clang.CursorKind.TRANSLATION_UNIT:
        if parent.kind == clang.CursorKind.NAMESPACE:
            outermost = parent
        parent = parent.semantic_parent
    return outermost is not None and outermost.spelling == "std"


def _is_c_typedef(decl: clang.Cursor) -> bool:
    """Return whether `decl` is a global C standard typedef such as ``size_t``."""
    parent = decl.semantic_parent
    while parent is not None and parent.kind == clang.CursorKind.LINKAGE_SPEC:
        parent = parent.semantic_parent
    return (
        decl.kind == clang.CursorKind.TYPEDEF_DECL
        and parent is not None
        and parent.kind == clang.CursorKind.TRANSLATION_UNIT
        and decl.location.is_in_system_header
        and _C_TYPEDEF.fullmatch(decl.spelling) is not None
    )


def _template_args_trivial(ty: clang.Type, depth: int) -> bool:
    """Return whether every template argument of `ty` is trivial."""
    count = ty.get_num_template_arguments()
    for index in range(max(count, 0)):
        arg = ty.get_template_argument_type(index)
        # Non-type arguments (e.g. the 3 in std::array<double, 3>) are INVALID.
        if arg.kind != clang.TypeKind.INVALID and not _is_trivial(arg, depth + 1):
            return False
    return True


def _is_trivial_spelled(ty: clang.Type) -> bool:
    """Classify a type without declaration (e.g. a ``using std::uint64_t``)."""
    canonical = ty.get_canonical()
    if canonical.kind.name not in _BUILTIN_KIND_NAMES:
        return False
    name = _CV.sub("", ty.spelling).strip()
    return name.startswith("std::") or _C_TYPEDEF.fullmatch(name) is not None


def _is_trivial_declared(ty: clang.Type, depth: int) -> bool:
    """Classify a typedef, record, enum or template specialization type."""
    decl = ty.get_declaration()
    if decl.kind == clang.CursorKind.NO_DECL_FOUND:
        return _is_trivial_spelled(ty)
    if _is_c_typedef(decl):
        return True
    return _in_std(decl) and _template_args_trivial(ty, depth)


def _is_trivial_elaborated(ty: clang.Type, depth: int) -> bool:
    """Classify a qualified type such as ``std::vector<int>``."""
    named = ty.get_named_type()
    if named.get_declaration().kind != clang.CursorKind.NO_DECL_FOUND:
        return _is_trivial(named, depth + 1)
    return named.kind.name in _BUILTIN_KIND_NAMES or _is_trivial_spelled(ty)


def _is_trivial(ty: clang.Type, depth: int = 0) -> bool:
    """Return whether `ty`, as written, is built only from builtin and std types.

    Parameters
    ----------
    ty: clang.Type
        The (sugared) type to classify.
    depth: int
        Current recursion depth; deeper types are treated as non-trivial.

    Returns
    -------
    bool
        True if `ty` names only builtin types, ``std`` types and C standard
        typedefs; False if any part names a project type, another
        non-standard alias, a template parameter or an unknown type.

    """
    kind = ty.kind
    result = False
    if depth > _MAX_DEPTH:
        result = False
    elif kind.name in _BUILTIN_KIND_NAMES:
        result = True
    elif kind in _WRAPPER_KINDS:
        result = _is_trivial(ty.get_pointee(), depth + 1)
    elif kind in _ARRAY_KINDS:
        result = _is_trivial(ty.element_type, depth + 1)
    elif kind == clang.TypeKind.FUNCTIONPROTO:
        result = _is_trivial(ty.get_result(), depth + 1) and all(
            _is_trivial(arg, depth + 1) for arg in ty.argument_types()
        )
    elif kind == clang.TypeKind.ELABORATED:
        result = _is_trivial_elaborated(ty, depth)
    elif kind in _DECLARED_KINDS:
        result = _is_trivial_declared(ty, depth)
    return result


def _qualified_name(cursor: clang.Cursor) -> str:
    """Return the ``::``-joined name of `cursor` and its named scopes."""
    parts = [cursor.spelling]
    parent = cursor.semantic_parent
    while parent is not None and parent.kind != clang.CursorKind.TRANSLATION_UNIT:
        if parent.spelling:
            parts.append(parent.spelling)
        parent = parent.semantic_parent
    return "::".join(reversed(parts))


def _in_ranges(line: int, column: int, ranges: list[tuple[int, int, int, int]]) -> bool:
    """Return whether ``line:column`` lies inside one of `ranges`."""
    return any(
        (start_line, start_col) <= (line, column) <= (end_line, end_col)
        for start_line, start_col, end_line, end_col in ranges
    )


class _Pending(typing.NamedTuple):
    """A candidate diagnostic buffered until all macro expansions are known."""

    name: str
    target: str
    keyword: str
    line: int
    column: int


class NoTrivialTypeAlias(Check):
    """Flag type aliases that only rename builtin or ``std`` types.

    Reporting is deferred to `finalize()` so that aliases whose name comes
    from a macro expansion can be skipped once every
    ``MACRO_INSTANTIATION`` of the file is known.
    """

    id = "noTrivialTypeAlias"

    def __init__(self) -> None:
        """Initialise with no allowed names and empty per-file buffers."""
        self.allowed_names: frozenset[str] = frozenset()
        self._macro_ranges: dict[str, list[tuple[int, int, int, int]]] = {}
        self._template_aliases: dict[str, set[tuple[int, int]]] = {}
        self._pending: dict[str, list[_Pending]] = {}

    def configure(self, config: dict) -> None:
        """Load ``allowed_names`` from the check's TOML config block.

        Parameters
        ----------
        config: dict
            Expected shape: ``{"allowed_names": list[str]}``; the key is
            optional.

        Raises
        ------
        ConfigError
            If ``allowed_names`` is not a list of strings.

        """
        value = config.get("allowed_names", [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            msg = f"{self.id}: 'allowed_names' must be a list of strings, got {value!r}"
            raise ConfigError(msg)
        self.allowed_names = frozenset(name.removeprefix("::") for name in value)

    def visit(self, cursor: clang.Cursor, filename: str) -> list[Diagnostic]:
        """Record macro expansions, alias templates and trivial aliases.

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
        elif cursor.kind == clang.CursorKind.TYPE_ALIAS_TEMPLATE_DECL:
            skip = self._template_aliases.setdefault(filename, set())
            skip.update(
                (child.location.line, child.location.column)
                for child in cursor.get_children()
                if child.kind == clang.CursorKind.TYPE_ALIAS_DECL
            )
        elif cursor.kind in _ALIAS_KINDS and self._is_candidate(cursor, filename):
            keyword = (
                "typedef" if cursor.kind == clang.CursorKind.TYPEDEF_DECL else "using"
            )
            self._pending.setdefault(filename, []).append(
                _Pending(
                    cursor.spelling,
                    cursor.underlying_typedef_type.spelling,
                    keyword,
                    cursor.location.line,
                    cursor.location.column,
                )
            )
        return []

    def _is_candidate(self, cursor: clang.Cursor, filename: str) -> bool:
        """Return whether the alias at `cursor` is trivial and not exempt."""
        loc = cursor.location
        if (loc.line, loc.column) in self._template_aliases.get(filename, set()):
            return False
        if (
            cursor.spelling in self.allowed_names
            or _qualified_name(cursor) in self.allowed_names
        ):
            return False
        parent = cursor.semantic_parent
        if (
            cursor.spelling in _PROTOCOL_NAMES
            and parent is not None
            and parent.kind in _CLASS_KINDS
        ):
            return False
        return _is_trivial(cursor.underlying_typedef_type)

    def finalize(self, filename: str) -> list[Diagnostic]:
        """Emit diagnostics for buffered aliases not named by a macro.

        Parameters
        ----------
        filename: str
            Path of the file being checked.

        Returns
        -------
        list[Diagnostic]
            One diagnostic per trivial alias.

        """
        ranges = self._macro_ranges.pop(filename, [])
        self._template_aliases.pop(filename, None)
        return [
            Diagnostic(
                file=filename,
                line=item.line,
                column=item.column,
                message=(
                    f"{item.keyword} alias '{item.name}' only renames "
                    f"'{item.target}'; use the type directly or a dedicated type"
                ),
                check_id=self.id,
            )
            for item in self._pending.pop(filename, [])
            if not _in_ranges(item.line, item.column, ranges)
        ]
