noUnitAlias
===========

Flags ``const`` and ``constexpr`` variables that only give a unit a new
name. The reader has to look the name up to learn which unit it stands for;
writing the unit where it is used says the same thing in place.

A variable is flagged if its type is ``const`` (``constexpr`` included, not a
reference), its type after resolving ``auto`` and aliases is declared in one
of the ``unit_namespaces`` and is not one of the ``quantity_types``, and its
initializer only combines names and literals with ``*``, ``/``, parentheses
and the unit helpers ``pow``, ``sqrt``, ``cbrt``, ``square``, ``cubic`` and
``inverse``.

.. code-block:: cpp

   constexpr auto ASE_FORCE = eV / angstrom;          // Bad — unit alias.
   buffer.push_back(force.numerical_value_in(ASE_FORCE));

   buffer.push_back(force.numerical_value_in(eV / angstrom));   // Good.

   constexpr Distance CUTOFF = 9.0 * angstrom;        // Good — a quantity.

Quantities (a number times a unit), non-``const`` variables and variables of
other types are not flagged. Skip the header that defines a project's units
on purpose with ``exclude_paths``.

Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 25 35

   * - Key
     - Type
     - Default
     - Description
   * - ``unit_namespaces``
     - list of strings
     - ``["mp_units", "mstd::units"]``
     - Namespaces whose types are units. Nested namespaces count too.
   * - ``quantity_types``
     - list of strings
     - ``["quantity", "quantity_point", "derived_quantity_spec"]``
     - Type names in those namespaces that are values, not units.

.. code-block:: toml

   [cpp.ast_check_config.noUnitAlias]
   unit_namespaces = ["mp_units", "mstd::units"]
   exclude_paths = ["include/utilities/units.hpp"]

Disabling
---------

.. code-block:: toml

   [cpp]
   ast_check_disabled_ids = ["noUnitAlias"]
