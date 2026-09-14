"""
actions/data.py — get structured data in and out of a run.

extract_data scrapes rows off the page into the context; load_test_data reads
rows from disk into it. Both deal in lists of dicts, which is what for_each_item
and the data-driven runner consume.
"""

from __future__ import annotations
import asyncio
import json
import logging
from pathlib import Path

from stepper.engine.interfaces import (
    ActionStrategy, StepConfig, StepResult, ExecutionContext,
)
from stepper.engine.actions._common import _fetch_attr

logger = logging.getLogger(__name__)


class ExtractDataAction(ActionStrategy):
    """
    Extract data from DOM elements on the current page.
    
    Returns a list of extracted values (text, URLs, attributes) that can be
    used by follow-up actions like PaginateAction or for_each_item.
    
    Step config expected:
        action: "extract_data"
        extra:
            selector: "CSS selector"  (required)
            attrs: ["href", "innerText"]  (optional — default: ["innerText"])
            limit: 100  (optional — max items to extract)
    
    Stores result in context["extracted_data"] = [list of values]
    """
    action_name = "extract_data"
    read_only   = True

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        try:
            selector = step.extra.get("selector")
            if not selector:
                return StepResult(
                    step=step,
                    status="failed",
                    error="Missing required field: extra.selector"
                )
            
            attrs = step.extra.get("attrs", ["innerText"])
            limit = step.extra.get("limit", 1000)
            wait_state = step.extra.get("wait_for_state", "visible")
            context_key = step.extra.get("context_key", "extracted_data")
            url_prefix = step.extra.get("url_prefix", "")
            dedupe = bool(step.extra.get("dedupe", False))
            allow_empty = step.extra.get("allow_empty", False)
            
            # Wait for selector to be present
            try:
                await page.wait_for_selector(selector, timeout=10_000, state=wait_state)
            except Exception as e:
                if allow_empty:
                    # Store empty result in typed context field
                    if context_key in ("collected_items", "collected_books"):
                        context.collected_items = []
                    else:
                        context.extracted_data = []
                    logger.info(f"✓ extract_data: 0 items (allow_empty) from '{selector}'")
                    return StepResult(step=step, status="passed")
                raise e
            
            # Query all matching elements
            locators = await page.locator(selector).all()
            extracted: list = []
            
            async def _fetch_element(loc):
                if len(attrs) == 1:
                    return await _fetch_attr(loc, attrs[0])
                values = await asyncio.gather(*[_fetch_attr(loc, attr) for attr in attrs])
                return dict(zip(attrs, values))

            extracted = list(await asyncio.gather(
                *[_fetch_element(loc) for loc in locators[:limit]]
            ))
            
            # Apply URL prefix if needed (converts relative hrefs to absolute URLs)
            if url_prefix:
                base = url_prefix.rstrip("/")
                extracted = [
                    base + v if isinstance(v, str) and v.startswith("/") else v
                    for v in extracted
                ]

            # Optional de-duplication (for scalar lists like hrefs)
            if dedupe and extracted and all(isinstance(v, str) for v in extracted):
                seen = set()
                deduped: list[str] = []
                for v in extracted:
                    if v in seen:
                        continue
                    seen.add(v)
                    deduped.append(v)
                if len(deduped) != len(extracted):
                    logger.info(
                        f"extract_data: deduped {len(extracted)} -> {len(deduped)} items"
                    )
                extracted = deduped

            # Store in context — route to the typed field matching context_key
            if context_key in ("collected_items", "collected_books"):
                context.collected_items = extracted
            else:
                context.extracted_data = extracted

            logger.info(f"✓ extract_data: {len(extracted)} items from '{selector}'")
            return StepResult(
                step=step,
                status="passed",
                
            )
        
        except Exception as e:
            return StepResult(
                step=step,
                status="failed",
                error=f"extract_data: {str(e)}"
            )


class LoadTestDataAction(ActionStrategy):
    """
    Load a JSON array from disk into context.collected_items.

    Expected step.extra:
      path: str   # path to a JSON file containing a list of dicts
    """
    action_name = "load_test_data"

    async def _execute(self, page, step: StepConfig, resolver,
                       context: ExecutionContext, behaviour=None) -> StepResult:
        path_str = (step.extra or {}).get("path")
        if not path_str:
            return StepResult(step=step, status="failed",
                              error="load_test_data: missing extra.path")

        path = Path(path_str)
        if not path.is_absolute():
            logger.warning(
                "load_test_data: resolving relative path '%s' from cwd %s",
                path_str, Path.cwd()
            )
            path = (Path.cwd() / path).resolve()

        if not path.exists():
            return StepResult(step=step, status="failed",
                              error=f"load_test_data: file not found: {path}")

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, list):
            return StepResult(step=step, status="failed",
                              error="load_test_data: expected a JSON array")

        context.collected_items = data
        logger.info("load_test_data: loaded %d rows from %s", len(data), path)
        return StepResult(step=step, status="passed")
