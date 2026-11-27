noSingleUseConstexpr
====================

Flags namespace-scope ``constexpr`` variables in a source file that are used
at most ``max_uses`` times (default once). A global like ``NO_ELEMENT = 0``
that is read in a single place adds a name but no meaning; write the value
where it is used, or as a local constant.

.. code-block:: cpp

   // atoms.cpp
   namespace {
   constexpr int NO_ELEMENT  = 0;    // Bad — used once.
   constexpr int MAX_ELEMENT = 118;  // Bad — used once.
   constexpr double TOL      = 1e-8; // Good — used twice.
   }

   bool valid(int z) { return z > NO_ELEMENT && z <= MAX_ELEMENT; }
   bool same(double a, double b) { return a - b < TOL && b - a < TOL; }

A variable is checked when it is declared ``constexpr`` (also ``static``
or ``inline constexpr``) directly in the global namespace, a named namespace
or an anonymous namespace of a ``.cpp``, ``.cc``, ``.cxx`` or ``.c++``
file. Every expression naming the variable counts as one use, including
array bounds, template arguments, ``static_assert`` and uses inside macro
arguments. A variable that is never used is flagged too.

Per-file limit
--------------

AST checks see one translation unit at a time, so only uses in the file
being checked are counted. For that reason:

- variables declared in headers (``.h``, ``.hpp``, ``.tpp``, ...) are never
  flagged, because other files may use them,
- a ``constexpr`` variable in a ``.cpp`` file that is also declared
  ``extern`` and used from another file still counts only the uses in its
  own file.

Never flagged:

- ``const``, ``constinit`` and non-constant variables,
- ``static constexpr`` class members and local ``constexpr`` variables,
- ``constexpr`` functions,
- variables whose name comes from a macro expansion.

Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 15 45

   * - Key
     - Type
     - Default
     - Description
   * - ``max_uses``
     - integer
     - ``1``
     - Highest number of uses in the file that is still flagged. ``0`` only
       flags unused variables. Must be ``>= 0``.

.. code-block:: toml

   [cpp.ast_check_config.noSingleUseConstexpr]
   max_uses = 1
   exclude_paths = ["src/generated/"]

Disabling
---------

.. code-block:: toml

   [cpp]
   ast_check_disabled_ids = ["noSingleUseConstexpr"]
