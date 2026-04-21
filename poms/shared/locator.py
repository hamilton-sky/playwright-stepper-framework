"""
shared/locator.py — Locator value object.

One Locator = one page element, described by every known identifier.
Used by SharedBasePage._interact() to resolve elements via the full
resolver cascade or the driver CSS fallback.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class Locator:
    """
    Single element descriptor.

    Semantic fields (role/name, label, placeholder, text) are tried first by
    the ElementResolver cascade — they survive DOM restructuring and CSS renames.

    Structural fields (id, css, xpath) are used by the resolver as lower-priority
    strategies, and by the driver fallback when no resolver is injected.

    css_fallbacks: additional CSS selectors tried only in the driver-fallback
    path, in order, after the primary css fails.  Not sent to the resolver —
    the cascade handles ambiguity itself.

    description: plain-English label used for embedding (Phase 2) and logging.
    """

    # ── Semantic identifiers ──────────────────────────────────────────────────
    role:        str | None = None
    name:        str | None = None        # paired with role
    label:       str | None = None
    placeholder: str | None = None
    text:        str | None = None
    aria_label:  str | None = None

    # ── Structural identifiers ────────────────────────────────────────────────
    id:    str | None = None
    css:   str | None = None             # primary CSS selector
    xpath: str | None = None

    # ── Additional CSS fallbacks (driver-fallback path only) ─────────────────
    css_fallbacks: list[str] = field(default_factory=list)

    # ── Metadata ──────────────────────────────────────────────────────────────
    description: str = ""               # embedding + log messages

    # ── Resolver integration ──────────────────────────────────────────────────

    def to_cfg(self) -> dict:
        """
        Convert to the cfg dict the ElementResolver understands.
        css_fallbacks are excluded — the resolver's cascade handles ambiguity.
        """
        return {k: v for k, v in {
            "role":        self.role,
            "name":        self.name,
            "label":       self.label,
            "placeholder": self.placeholder,
            "text":        self.text,
            "id":          self.id,
            "css":         self.css,
            "xpath":       self.xpath,
        }.items() if v is not None}

    # ── Driver fallback integration ───────────────────────────────────────────

    def css_candidates(self) -> list[str]:
        """
        Ordered CSS-compatible selectors for the driver fallback path.
        Priority: id > css > css_fallbacks > xpath.
        Semantic fields are excluded — they require Playwright's semantic API.
        """
        result: list[str] = []
        if self.id:
            result.append(f"#{self.id}")
        if self.css:
            result.append(self.css)
        result.extend(self.css_fallbacks)
        if self.xpath:
            result.append(f"xpath={self.xpath}")
        return result
