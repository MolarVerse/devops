"""Forbid plain floating-point data members that hold physical quantities.

A data member such as ``double potentialEnergy`` loses its unit: nothing
stops it from being added to a force or read in the wrong unit. Such values
should use a typed quantity (e.g. PQ's ``Energy``) instead.

A non-static data member (field) of a class, struct or union is flagged if

* its name matches one of the case-insensitive regular expressions in
  ``name_patterns`` (searched anywhere in the name), and
* its type is ``float``, ``double`` or ``long double`` (also through
  typedefs, aliases, references and arrays), or a container named in
  ``container_templates`` (e.g. ``std::vector<double>``,
  ``std::array<double, 3>``, ``linalg::Vector3D<double>``) with such a
  type among its template arguments, at any depth.

Other templates are not looked into: ``mstd::quantity<units::kcal,
double>`` is typed, and handles such as ``std::unique_ptr<T>`` or I/O
buffers are not values. Members listed in ``allowed_names`` are skipped.
Members of a dependent template type and static data members are not
checked.

Configure the check via the project TOML file::

    [cpp.ast_check_config.noPlainDoubleQuantity]
    name_patterns = ["energy", "force"]
    allowed_names = ["energyTolerance"]
"""

from __future__ import annotations

import re

import clang.cindex as clang

from devops.config.base import ConfigError
from devops.cpp.ast.base import Check, Diagnostic

DEFAULT_NAME_PATTERNS = (
    "energy",
    "force",
    "mass",
    "time",
    "temperature",
    "pressure",
    "velocit",
    "momentum",
    "charge",
    "virial",
    "stress",
    "volume",
    "distance",
    "frequency",
    "compressibility",
)

DEFAULT_CONTAINER_TEMPLATES = (
    "array",
    "deque",
    "forward_list",
    "list",
    "map",
    "multimap",
    "optional",
    "pair",
    "span",
    "tuple",
    "unordered_map",
    "unordered_multimap",
    "valarray",
    "vector",
    "Matrix",
    "StaticMatrix3x3",
    "Vector3D",
)

_KNOWN_KEYS = frozenset(
    ("name_patterns", "allowed_names", "container_templates", "exclude_paths")
)

_FLOATING_KINDS = frozenset(
    (
        clang.TypeKind.FLOAT,
        clang.TypeKind.DOUBLE,
        clang.TypeKind.LONGDOUBLE,
    )
)

_ARRAY_KINDS = frozenset(
    (
        clang.TypeKind.CONSTANTARRAY,
        clang.TypeKind.INCOMPLETEARRAY,
        clang.TypeKind.VARIABLEARRAY,
        clang.TypeKind.DEPENDENTSIZEDARRAY,
    )
)

_REFERENCE_KINDS = frozenset(
    (clang.TypeKind.LVALUEREFERENCE, clang.TypeKind.RVALUEREFERENCE)
)


def _has_plain_floating(ty: clang.Type, containers: frozenset[str]) -> bool:
    """Return whether `ty` is or contains a plain floating-point type.

    Parameters
    ----------
    ty: clang.Type
        The member's type.
    containers: frozenset[str]
        Names (without namespace) of the templates whose template arguments
        are searched.

    Returns
    -------
    bool
        True for ``double``, ``float``, ``long double``, references and
        arrays of those, and specializations of `containers` with such a
        type argument (recursively).

    """
    ty = ty.get_canonical()
    if ty.kind in _REFERENCE_KINDS:
        ty = ty.get_pointee().get_canonical()
    while ty.kind in _ARRAY_KINDS:
        ty = ty.element_type.get_canonical()
    if ty.kind in _FLOATING_KINDS:
        return True
    if ty.kind != clang.TypeKind.RECORD:
        return False
    if ty.get_declaration().spelling not in containers:
        return False
    for i in range(max(ty.get_num_template_arguments(), 0)):
        arg = ty.get_template_argument_type(i)
        if arg.kind != clang.TypeKind.INVALID and _has_plain_floating(arg, containers):
            return True
    return False


class NoPlainDoubleQuantity(Check):
    """Flag ``double``/``float`` data members named like physical quantities.

    A member of a struct defined inside another member's declaration is
    visited twice by the walk, so reported locations are remembered per file
    until `finalize()`.
    """

    id = "noPlainDoubleQuantity"

    def __init__(self) -> None:
        """Initialise with the default name patterns and containers."""
        self._reported: dict[str, set[tuple[int, int]]] = {}
        self.name_patterns: tuple[re.Pattern[str], ...] = tuple(
            re.compile(p, re.IGNORECASE) for p in DEFAULT_NAME_PATTERNS
        )
        self.allowed_names: frozenset[str] = frozenset()
        self.container_templates: frozenset[str] = frozenset(
            DEFAULT_CONTAINER_TEMPLATES
        )

    def configure(self, config: dict) -> None:
        """Load the name patterns and exceptions from the TOML config block.

        Parameters
        ----------
        config: dict
            Expected shape: ``{"name_patterns": ["energy"], "allowed_names":
            ["energyTolerance"], "container_templates": ["vector"]}``. All keys
            are optional; a given list replaces the default.

        Raises
        ------
        ConfigError
            If a key is not a list of strings, a pattern is not a valid
            regular expression, or the table contains an unknown key.

        """
        unknown = sorted(set(config) - _KNOWN_KEYS)
        if unknown:
            msg = (
                f"{self.id}: unknown key(s) {unknown} in "
                f"[cpp.ast_check_config.{self.id}]; expected "
                f"{sorted(_KNOWN_KEYS)}"
            )
            raise ConfigError(msg)
        patterns = self._parse_str_list(config, "name_patterns", DEFAULT_NAME_PATTERNS)
        compiled = []
        for pattern in patterns:
            try:
                compiled.append(re.compile(pattern, re.IGNORECASE))
            except re.error as error:
                msg = (
                    f"{self.id}: invalid regular expression {pattern!r} in "
                    f"'name_patterns': {error}"
                )
                raise ConfigError(msg) from error
        self.name_patterns = tuple(compiled)
        self.allowed_names = frozenset(
            self._parse_str_list(config, "allowed_names", ())
        )
        self.container_templates = frozenset(
            self._parse_str_list(
                config, "container_templates", DEFAULT_CONTAINER_TEMPLATES
            )
        )

    def _parse_str_list(
        self, config: dict, key: str, default: tuple[str, ...]
    ) -> tuple[str, ...]:
        raw = config.get(key, list(default))
        if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
            msg = (
                f"{self.id}: '{key}' in [cpp.ast_check_config.{self.id}] must be "
                "a list of strings"
            )
            raise ConfigError(msg)
        return tuple(raw)

    def _matching_pattern(self, name: str) -> str | None:
        """Return the first name pattern found in `name`, if any."""
        for pattern in self.name_patterns:
            if pattern.search(name):
                return pattern.pattern
        return None

    def visit(self, cursor: clang.Cursor, filename: str) -> list[Diagnostic]:
        """Flag `cursor` if it is a quantity-named plain floating member.

        Parameters
        ----------
        cursor: clang.Cursor
            The AST node currently being visited.
        filename: str
            Path of the file being checked.

        Returns
        -------
        list[Diagnostic]
            A single diagnostic at the member's name, otherwise an empty
            list.

        """
        if cursor.kind != clang.CursorKind.FIELD_DECL:
            return []
        name = cursor.spelling
        if not name or name in self.allowed_names:
            return []
        pattern = self._matching_pattern(name)
        if pattern is None or not _has_plain_floating(
            cursor.type, self.container_templates
        ):
            return []
        location = (cursor.location.line, cursor.location.column)
        reported = self._reported.setdefault(filename, set())
        if location in reported:
            return []
        reported.add(location)
        owner = cursor.semantic_parent.spelling or "<unnamed>"
        return [
            Diagnostic(
                file=filename,
                line=cursor.location.line,
                column=cursor.location.column,
                message=(
                    f"member '{name}' of '{owner}' has plain type "
                    f"'{cursor.type.spelling}' but its name matches "
                    f"'{pattern}'; use a typed quantity instead"
                ),
                check_id=self.id,
            )
        ]

    def finalize(self, filename: str) -> list[Diagnostic]:
        """Forget the members reported in `filename`.

        Parameters
        ----------
        filename: str
            Path of the file being checked.

        Returns
        -------
        list[Diagnostic]
            Always empty; diagnostics are emitted from `visit()`.

        """
        self._reported.pop(filename, None)
        return []
