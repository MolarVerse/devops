noTrivialTypeAlias
==================

Flags type aliases that only rename a builtin or standard library type. Such
an alias adds a name but no meaning: the reader still has to look it up, and
a ``Shape`` can be mixed freely with any other ``std::vector<std::size_t>``.
Use the type directly, or a dedicated type if the distinction matters.

.. code-block:: cpp

   using Shape = std::vector<std::size_t>;      // Bad — flagged.
   typedef double Real;                         // Bad — flagged.
   using Atoms = std::vector<Atom>;             // Good — names a project type.
   template <typename T> using Vec = std::vector<T>;  // Good — alias template.

Every non-template ``using X = T;`` and ``typedef T X;`` is checked, at
namespace, class and function scope. It is flagged when the target ``T``, as
written in the source, is built only from

- builtin types (``int``, ``double``, ``bool``, ``char``, ``void``, ...),
- types declared in namespace ``std`` (``std::size_t``, ``std::string``,
  ``std::vector<...>``, ``std::array<double, 3>``, ...), where every template
  argument must again be trivial,
- the C standard typedefs ``size_t``, ``ssize_t``, ``ptrdiff_t``,
  ``max_align_t``, ``intN_t``/``uintN_t`` (also the ``_least``/``_fast``
  variants), ``intmax_t``/``uintmax_t`` and ``intptr_t``/``uintptr_t``
  declared at global scope in a system header,
- pointers, references, arrays and function types of the above
  (``const double *``, ``std::function<void(int)>``).

Never flagged:

- alias templates (``template <typename T> using ...``),
- aliases whose target names a project type, a project alias or a template
  parameter anywhere, e.g. ``std::vector<Atom>``, ``std::unique_ptr<Atom>``,
  ``std::vector<T>`` or ``Shape`` (an alias of an alias is reported only at
  the first alias),
- class members whose name the standard library protocols require:
  ``type``, ``value_type``, ``element_type``, ``size_type``,
  ``difference_type``, ``pointer``, ``const_pointer``, ``reference``,
  ``const_reference``, ``iterator_category``, ``iterator_concept``,
  ``is_transparent``, ``propagate_on_container_move_assignment`` and
  ``is_always_equal`` (the same names at namespace or function scope are
  checked),
- member pointer types (``int Atom::*``) and types libclang cannot resolve,
- aliases whose name comes from a macro expansion,
- names listed in ``allowed_names``.

The check looks at the target as written, not its canonical type, so a
project alias such as ``using Dims = Shape;`` is not flagged even though
``Shape`` is ``std::vector<std::size_t>``.

Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 15 45

   * - Key
     - Type
     - Default
     - Description
   * - ``allowed_names``
     - list of strings
     - ``[]``
     - Alias names that are never flagged. An entry matches the unqualified
       name (``Real``) or the fully qualified one (``pq::Real``,
       ``Parser::Callback``); a leading ``::`` is ignored.

.. code-block:: toml

   [cpp.ast_check_config.noTrivialTypeAlias]
   allowed_names = ["Real", "Parser::Callback"]

Disabling
---------

.. code-block:: toml

   [cpp]
   ast_check_disabled_ids = ["noTrivialTypeAlias"]
