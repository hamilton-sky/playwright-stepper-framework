"""
sites/db/conditions.py — the db domain's `when` vocabulary.

    { "db_row_exists": { "sql": "SELECT 1 FROM sightings WHERE name = ?",
                         "params": ["Dune"] } }

M3 made conditions domain-tagged and routed: `ConditionRegistry` stores the
domain beside each evaluator and `evaluate()` looks the matching session up in
the run's SessionSet. Until M6 the only tagged conditions were the browser's,
so nothing ever exercised a *second* domain's — which is how the composition
bug this condition found survived M3, M4 and M5. See docs/mixed-domain-plan.md.

Fails closed, for the same reason `element_exists` does: a condition that
cannot be established should answer "no" rather than take a step's guard away.
"""

from __future__ import annotations

import logging

from poms.shared.diagnostics import log_swallowed

from stepper.engine.runner.when_eval import ConditionRegistry, core_conditions
from stepper.sites.db.params import resolve_params

logger = logging.getLogger(__name__)


async def db_row_exists(session, spec, context) -> bool:
    """
    True when the query returns at least one row.

    `params` go through the same context resolution the actions use, so a
    clause can be guarded on a value an earlier step scraped. An unresolved
    reference answers False rather than failing the run — a condition that
    cannot be established is a "no", which is what element_exists does and what
    workflows have been written against. The actions are the ones that refuse,
    because they are the ones that would otherwise write the token into a row.
    """
    if isinstance(spec, str):
        spec = {"sql": spec}
    sql = str((spec or {}).get("sql", "")).strip()
    if not sql:
        logger.debug("when.db_row_exists: no sql given → False")
        return False

    params, bad = resolve_params((spec or {}).get("params", []), context)
    if bad:
        logger.debug(f"when.db_row_exists: {bad} → False")
        return False
    try:
        result = session.execute(sql, params).fetchone() is not None
    except Exception as exc:
        log_swallowed(f"when.db_row_exists[{sql!r}]", exc, logger)
        result = False
    logger.debug(f"when.db_row_exists({sql!r}) → {result}")
    return result


def db_conditions() -> ConditionRegistry:
    """Core plus the one that needs a connection."""
    return core_conditions().register("db_row_exists", db_row_exists, domain="db")
