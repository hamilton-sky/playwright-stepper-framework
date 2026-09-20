"""
sites/openlibrary/pages/search_page.py — Stepper action module for OL search.

Wires BookSearchPage into the Stepper ActionRegistry.
This file is Stepper glue — it imports from both:
  - stepper/engine/ (framework interfaces)
  - poms/openLibrary/ (the page objects)

Dependency direction: stepper.sites → stepper.engine  (correct)
                      stepper.sites → poms           (correct — glue depends on POM)
"""

from __future__ import annotations
import logging

from stepper.engine.browser.human_behaviour import HumanBehaviour
from stepper.engine.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.engine.pages.base_page_module import PageModule
from stepper.engine.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class OLSearchPage(PageModule):
    site = "ol"

    #: `collect_items` predates the f"{site}_" convention and the shipped
    #: workflows reach it through the `ol_collect_books` alias bound below.
    #: Renaming it would break any workflow still using the old spelling, so
    #: the name is kept and the exemption is declared here rather than left
    #: as an unexplained hole in the rule. See .claude/rules/glue-layer.md.
    unprefixed_actions = frozenset({"collect_items"})

    class OLCollectBooksAction(GlueAction):
        """
        Collect book URLs from OpenLibrary search results.
        Navigates to the search page, submits the query, filters by max
        publication year, and paginates automatically via BookSearchPage (POM).

        Registered as both 'collect_items' (workflow compat) and 'ol_collect_books'.
        Uses BookSearchPage so all selector/delay/retry knowledge stays in the POM,
        not duplicated in this glue layer.

        JSON usage:
          { "action": "collect_items",
            "extra": { "query": "Dune", "filter": { "year_max": 1980 }, "limit": 5 } }
        """
        action_name = "collect_items"
        read_only   = True

        async def _execute(
            self, page, step: StepConfig,
            resolver, context: ExecutionContext,
            behaviour: HumanBehaviour | None = None,
        ) -> StepResult:
            try:
                from poms.openLibrary.config import load_settings
                from poms.openLibrary.pages.book_search_page import BookSearchPage

                settings    = load_settings()
                driver      = self._driver(page)
                search_page = self._build_pom(BookSearchPage, driver, settings.base_url,
                                             settings.delays, page=page, resolver=resolver, behaviour=behaviour)

                query    = step.extra.get("query", "")
                max_year = step.extra.get("filter", {}).get("year_max", 9999)
                limit    = step.extra.get("limit", 5)

                await search_page.open()
                await search_page.search(query)
                urls = await search_page.collect_books_under_year(max_year=max_year, limit=limit)

                context.collected_items = urls
                logger.info(f"collect_items → {len(urls)} books")
                return StepResult(step=step, status="passed", output={"items": urls})

            except Exception as e:
                logger.error(f"collect_items failed: {e}")
                return StepResult(step=step, status="failed", error=str(e))

    @classmethod
    def register(cls, registry) -> None:
        action, = cls.register_actions(registry, cls.OLCollectBooksAction())
        # Also register under the ol_ alias used by ol_search_and_add.json
        registry.alias("ol_collect_books", action.action_name)
