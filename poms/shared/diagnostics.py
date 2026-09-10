"""
diagnostics.py — make swallowed exceptions visible on demand.

The framework swallows exceptions deliberately in a lot of places, and it is
right to: a resolver strategy that cannot help returns ``[]``, a POM
interaction that fails returns ``False``, a screenshot that cannot be written
is not worth failing a run over. The cascade depends on it — every strategy
must be allowed to shrug so the next one gets a turn.

The cost is that a genuine code defect becomes indistinguishable from the
innocuous case it is impersonating. ``AttributeError`` inside a ``try`` that
returns ``False`` reads exactly like "the selector did not match".

That is not hypothetical. ``BookDetailPage`` dereferenced a ``None`` behaviour
eight times. Every call sat inside a ``try/except`` that returned ``False``, so
driver-only mode silently could not shelf a book, and the log said the strategy
had failed. Nothing crashed. Nothing looked wrong.

``log_swallowed`` gives every swallow a name:

    try:
        ...
    except Exception as exc:
        log_swallowed("TextResolver.collect", exc)
        return []

Three levels of visibility, so normal runs stay readable and a bug still gets
out:

  * quiet by default — DEBUG, invisible at the usual INFO console level
  * ``STEPPER_DEBUG=1`` — every swallow at WARNING with a full traceback
  * bug-shaped exceptions — always WARNING, env var or not

That last rule is the point of the module. ``AttributeError``, ``NameError``,
``TypeError`` and ``ImportError`` mean the code is wrong, not that the page was
slow; they are never a legitimate "this strategy cannot help". Requiring an
opt-in flag to see them means you only find them once you already suspect them,
which is precisely how the behaviour bug survived.

Adapted from the same idea in codeintel (``log_swallowed`` there), with two
deliberate differences: the environment is read per call rather than at import,
so tests can toggle it; and bug-shaped types are promoted without the flag.

Lives in ``poms/shared`` rather than ``stepper/engine`` because POMs must not
import from ``stepper/`` — the dependency runs Flow → Glue → POM and never back.
The engine already reaches the other way for ``poms.shared.constants``.
"""

from __future__ import annotations

import logging
import os
import traceback

_logger = logging.getLogger("stepper.swallowed")

#: Exception types that mean "this code is wrong", not "the page was not ready".
#: A resolver legitimately raises TimeoutError or a Playwright error when an
#: element is missing; it never legitimately raises AttributeError.
_BUG_SHAPED: tuple[type[BaseException], ...] = (
    AttributeError,
    NameError,
    TypeError,
    ImportError,
)

_TRUTHY = frozenset({"1", "true", "yes", "y", "on"})


def debug_enabled() -> bool:
    """
    True when STEPPER_DEBUG asks for every swallow to be surfaced.

    Read per call rather than cached at import so a test — or a developer in a
    REPL — can turn it on without reimporting the module.
    """
    return os.environ.get("STEPPER_DEBUG", "").strip().lower() in _TRUTHY


def log_swallowed(where: str, exc: BaseException, logger: logging.Logger | None = None) -> None:
    """
    Record an exception that the caller is about to swallow on purpose.

    Args:
        where:  Where it happened, precisely enough to grep for —
                ``"TextResolver.collect"``, ``"BookDetailPage.add_to_shelf"``.
        exc:    The exception being swallowed.
        logger: Log through this logger instead of ``stepper.swallowed``, to
                keep a module's own logger name in the output.

    Never raises. A diagnostic that can break the code it is diagnosing is
    worse than no diagnostic.
    """
    try:
        log = logger or _logger
        kind = type(exc).__name__

        if debug_enabled():
            log.warning("swallowed in %s: %s: %s\n%s", where, kind, exc, traceback.format_exc())
        elif isinstance(exc, _BUG_SHAPED):
            log.warning(
                "swallowed in %s: %s: %s — this is a code defect, not a page "
                "condition; the caller is about to report an ordinary failure. "
                "Set STEPPER_DEBUG=1 for the traceback.",
                where, kind, exc,
            )
        else:
            log.debug("swallowed in %s: %s: %s", where, kind, exc)
    except Exception:
        pass
