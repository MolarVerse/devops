noPlainDoubleQuantity
=====================

Flags data members that hold a physical quantity as a plain floating-point
number. A ``double potentialEnergy`` carries no unit, so nothing stops it
from being mixed up with a force or read in the wrong unit; use a typed
quantity (e.g. ``Energy``) instead.

A non-static data member of a class, struct or union is flagged if its name
matches one of the ``name_patterns`` (case-insensitive regular expressions,
searched anywhere in the name) and its type is ``float``, ``double`` or
``long double``. Typedefs, aliases, references and arrays are resolved, and
the templates in ``container_templates`` are searched through their template
arguments, so ``std::vector<double>``, ``std::array<double, 3>`` and
``Vector3D<double>`` are flagged too.

.. code-block:: cpp

   struct Frame {
       double potentialEnergy;          // Bad.
       std::vector<double> masses;      // Bad.
       Vector3D<double> force;          // Bad.

       Energy potentialEnergy;          // Good.
       std::vector<Mass> masses;        // Good.
       double tolerance;                // Good, name is not a quantity.
       int energyIndex;                 // Good, not floating-point.
   };

Other templates are not searched: ``mstd::quantity<units::kcal, double>``
is typed, and handles such as ``std::unique_ptr<T>`` or I/O buffers are not
values. Static data members, members of a dependent template type,
pointers, local variables, globals and parameters are not checked.

Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 20 15 25 40

   * - Key
     - Type
     - Default
     - Description
   * - ``name_patterns``
     - list of strings
     - ``energy``, ``force``, ``mass``, ``time``, ``temperature``,
       ``pressure``, ``velocit``, ``momentum``, ``charge``, ``virial``,
       ``stress``, ``volume``, ``distance``, ``frequency``,
       ``compressibility``
     - Regular expressions matched case-insensitively against the member
       name. A given list replaces the default.
   * - ``allowed_names``
     - list of strings
     - ``[]``
     - Member names that are never flagged (exact match).
   * - ``container_templates``
     - list of strings
     - ``array``, ``deque``, ``forward_list``, ``list``, ``map``,
       ``multimap``, ``optional``, ``pair``, ``span``, ``tuple``,
       ``unordered_map``, ``unordered_multimap``, ``valarray``,
       ``vector``, ``Matrix``, ``StaticMatrix3x3``, ``Vector3D``
     - Template names (without namespace) whose template arguments are
       searched for floating-point types. A given list replaces the
       default.

.. code-block:: toml

   [cpp.ast_check_config.noPlainDoubleQuantity]
   allowed_names = ["energyTolerance"]
   exclude_paths = ["include/legacy/"]
