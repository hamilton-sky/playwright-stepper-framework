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

The browser's own adapter is not here: it is WebSession in
stepper/bootstrap/session.py, alongside the domain registry that main.py asks
for it. This module carries the contract and the null implementation only —
putting a Playwright-shaped class in the engine is exactly what the plan is
undoing.
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


# ── Many sessions, one run ────────────────────────────────────────────────────

class UnknownDomainError(ValueError):
    """A step's action names a domain this run has no session for."""


_UNSET = object()


class SessionSet:
    """
    The run's sessions, keyed by domain and opened on first use.

    StepRunner holds one of these instead of one session. Per step it asks the
    action which domain it acts on and looks that up here — so the runner routes
    without knowing what any domain is. See docs/mixed-domain-plan.md, M2.

    Opening is lazy on purpose: a workflow that never runs a db step never opens
    a connection, and a workflow with no web steps never launches a browser.
    Closing is the reverse of opening, and every session still closes when an
    earlier one raises — the same shape WebSession.close already uses.

    Three ways to build one:

        SessionSet({"web": web_adapter, "db": db_adapter}, primary="web")
        SessionSet.of("web", adapter)        # one domain, still lazy
        SessionSet.single(already_open)      # legacy: answers every domain
    """

    def __init__(self, adapters: dict[str, Any] | None = None, *,
                 primary: str | None = None):
        self._adapters: dict[str, Any] = dict(adapters or {})
        self._opened: dict[str, Any] = {}
        self._order: list[str] = []
        self._primary = primary
        self._single = _UNSET

    # ── Construction ─────────────────────────────────────────────────────────

    @classmethod
    def of(cls, domain: str, adapter) -> "SessionSet":
        """A set holding one domain's adapter, opened on first use."""
        return cls({domain: adapter}, primary=domain)

    @classmethod
    def single(cls, session) -> "SessionSet":
        """
        Wrap one already-open session so it answers *every* domain lookup.

        This is what a caller passing `page=` or `session=` to StepRunner gets,
        and it is deliberately permissive: before this existed every action
        received that one object whatever it declared, and a test double or a
        sub-runner must keep behaving exactly that way. It owns nothing, so
        close_all() on it is a no-op — whoever opened the session closes it.
        """
        instance = cls()
        instance._single = session
        return instance

    # ── Reading ──────────────────────────────────────────────────────────────

    @property
    def is_single(self) -> bool:
        return self._single is not _UNSET

    @property
    def primary(self):
        """
        The run's main session, for the few callers that still need one — the
        heal loop's DOM snapshots and, until M3, the `when` evaluator.
        """
        if self.is_single:
            return self._single
        if self._primary is not None:
            return self._opened.get(self._primary)
        return next(iter(self._opened.values()), None)

    def opened_domains(self) -> list[str]:
        """Domains opened so far, in the order they were opened."""
        return list(self._order)

    def domains(self) -> list[str]:
        return sorted(self._adapters)

    async def get(self, domain: str | None):
        """
        The session for `domain`, opening it if this is its first use.

        `None` means the action declared itself session-agnostic and is handed
        nothing — an action that said it needs no session must not quietly come
        to depend on whichever one happened to open first.
        """
        if domain is None:
            return None
        if self.is_single:
            return self._single
        if domain in self._opened:
            return self._opened[domain]

        adapter = self._adapters.get(domain)
        if adapter is None:
            raise UnknownDomainError(
                f"No session for domain '{domain}'. This run has: "
                f"{self.domains() or '(none)'}. A workflow step names an action "
                f"whose domain was never registered — see bootstrap/session.py."
            )
        opened = await adapter.open()
        self._opened[domain] = opened
        self._order.append(domain)
        return opened

    def adopt(self, domain: str, adapter, opened) -> None:
        """
        Record a session someone else already opened, so this set closes it.

        build_pipeline opens the primary domain eagerly — the browser launches
        at the same moment it always did — and hands the result here rather than
        leaving two owners for one session.
        """
        self._adapters[domain] = adapter
        self._opened[domain] = opened
        if domain not in self._order:
            self._order.append(domain)
        if self._primary is None:
            self._primary = domain

    # ── Teardown ─────────────────────────────────────────────────────────────

    async def close_all(self) -> None:
        """
        Close every session this set opened, newest first.

        A set built by `single()` opened nothing and closes nothing. Otherwise
        the nested finallys mean a failure closing one session does not strand
        the rest, while the first failure still propagates — closing a browser
        context is what flushes a recorded video, and a browser left running
        outlives the process.
        """
        if self.is_single:
            return
        pending = list(reversed(self._order))
        self._order.clear()
        await self._close_chain(pending)

    async def _close_chain(self, pending: list[str]) -> None:
        if not pending:
            return
        head, rest = pending[0], pending[1:]
        try:
            adapter = self._adapters.get(head)
            if adapter is not None:
                await adapter.close()
        finally:
            self._opened.pop(head, None)
            await self._close_chain(rest)
