"""
stepper — the automation engine.

Everything the engine ships lives under this namespace: ``stepper.engine``,
``stepper.sites``, ``stepper.bootstrap``, plus the ``stepper.main`` pipeline and
the ``stepper.cli`` front end.

The page objects are deliberately *not* here. ``poms`` stays a top-level package
because it is a peer of the engine, not a child of it: the dependency runs
Flow → Glue → POM and never back, and ``examples/plain_pom/`` imports ``poms``
with no engine present at all. Nesting it under ``stepper`` would say the
opposite of what the architecture means.
"""
