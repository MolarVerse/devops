consistentGetterPrefix
======================

Flags a class whose getters mix the ``getX()`` and the plain ``x()``
naming style. One class should use one style for all its getters.

.. code-block:: cpp

   class Box {                     // Bad — mixes both styles.
     public:
       double getVolume() const;
       double length() const;
   };

   class Cell {                    // Good — all get-prefixed.
     public:
       double getVolume() const;
       double getLength() const;
       bool isEmpty() const;       // Exempt.
   };

A getter is a non-static ``const`` member function declared in the class
body that takes no parameters and does not return ``void``. Leading
underscores are ignored, so private ``_getX()`` and ``_x()`` count too.
Names that are ``get`` followed by an upper-case letter are get-prefixed;
all other names starting with a lower-case letter are plain.

Never counted as getters:

- predicates and verbs: names starting with ``is``, ``has``, ``can``,
  ``should``, ``was``, ``use``, ``allow``, ``supports``, ``any``, ``all``,
  ``calculate``, ``calc``, ``compute``, ``check``, ``clone``, ``copy``,
  ``create``, ``make``, ``build``, ``find``, ``count``, ``flatten``,
  ``sort``, ``determine``, ``convert``, ``to``, ``as``, ``print``,
  ``format``, ``validate`` or ``evaluate``, or with one of the configured
  ``exempt_prefixes``, followed by an upper-case letter or the end of the
  name (``calculateMass`` and ``clone`` are exempt, ``calculator`` is not),
- ``get``, ``size``, ``empty``, ``begin``/``end`` and their
  ``c``/``r``/``cr`` variants, and the configured ``exempt_names``,
- operators, conversion functions, deleted functions and overrides of a
  base-class virtual method,
- member function templates and methods whose name comes from a macro
  expansion.

Each class is reported once, at its name, with both groups listed. Nested
classes are checked on their own, and inherited getters are not counted.

Configuration
-------------

.. list-table::
   :header-rows: 1
   :widths: 25 15 15 45

   * - Key
     - Type
     - Default
     - Description
   * - ``exempt_names``
     - list of strings
     - ``[]``
     - Extra method names that are never counted as getters.
   * - ``exempt_prefixes``
     - list of strings
     - ``[]``
     - Extra verb prefixes, added to the built-in list, whose methods are
       never counted as getters.

.. code-block:: toml

   [cpp.ast_check_config.consistentGetterPrefix]
   exempt_names = ["data", "length"]
   exempt_prefixes = ["estimate", "render"]

Disabling
---------

.. code-block:: toml

   [cpp]
   ast_check_disabled_ids = ["consistentGetterPrefix"]
