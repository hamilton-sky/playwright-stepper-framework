"""
engine/session.py — What a domain hands the runner to act on.

StepRunner holds one opaque object and passes it to every action as the first
positional argument. For the web domain that object is a Playwright Page; for
an HTTP domain it would be a client, for AWS a boto3 session. The runner never
inspects it, so the contract is only about lifecycle: something opens it,
something closes it.

See docs/universal-runner-plan.md §5.1, ticket T2.

    class HttpSession:
        domain = "http"

        async def open(self):
            self._client = httpx.AsyncClient()
            return self._client

        async def close(self):
            await self._client.aclose()

The browser's adapter is deliberately not here yet — it is still built inline
in main.run(), which is leak L4 and ticket T3's job. This module carries the
contract and the null implementation only, so that T2 does not drag the
composition root along with it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SessionAdapter(Protocol):
    """
    Opens and closes whatever a domain's actions act on.

    `domain` is the name the workflow and the registry agree on — the same
    string that names the folder under stepper/sites/.
    """

    domain: str

    async def open(self) -> object:
        """Build the object actions receive. Called once per run."""
        ...

    async def close(self) -> None:
        """Release it. Called once per run, including when the run raised."""
        ...


class NullSession:
    """
    A session for domains that have nothing to open — and the one T8's noop
    domain uses to prove the runner needs no browser.

    `open()` returns a plain object rather than None so that actions can hold
    it, set attributes on it and compare identity without special-casing.
    """

    domain = "noop"

    def __init__(self, domain: str = "noop"):
        self.domain = domain

    async def open(self) -> object:
        return object()

    async def close(self) -> None:
        return None
