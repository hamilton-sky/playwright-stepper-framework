"""
sites/openlibrary/pages/search_page.py — Stepper action module for OL search.

Wires the exam's BookSearchPage into the Stepper ActionRegistry.
This file is Stepper glue — it imports from both:
  - src/ (Stepper framework interfaces)
  - openlibrary_exam/ (exam POM)

Dependency direction: sites.openlibrary → stepper  (correct)
                      sites.openlibrary → openlibrary  (correct — exam is the dependency)
"""

from __future__ import annotations
import logging

from stepper.interfaces import StepConfig, StepResult, ExecutionContext
from stepper.pages.base_page_module import PageModule
from stepper.pages.glue_action import GlueAction

logger = logging.getLogger(__name__)


class OLSearchPage(PageModule):
    site = "ol"

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
        ) -> StepResult:
            try:
                from poms.openLibrary.config import load_settings
                from poms.openLibrary.pages.book_search_page import BookSearchPage

                settings    = load_settings()
                driver      = self._driver(page)
                search_page = self._build_pom(BookSearchPage, driver, settings.base_url,
                                             settings.delays, page=page, resolver=resolver)

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
        action = cls.OLCollectBooksAction()
        registry.register(action)
        # Also register under the ol_ alias used by ol_search_and_add.json
        registry._registry["ol_collect_books"] = action
        logger.debug("Registered OLSearchPage action: collect_items / ol_collect_books")
