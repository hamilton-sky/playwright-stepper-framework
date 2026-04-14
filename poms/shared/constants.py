"""
poms/shared/constants.py — Shared confidence thresholds.

Single source of truth for CONFIDENCE_AUTO and CONFIDENCE_WARN.
Both the POM resolver helpers (poms/shared/base_page.py) and the
Stepper engine (stepper/stepper/interfaces.py) import from here.

Do NOT declare these values anywhere else — edit only this file.
"""

CONFIDENCE_AUTO: float = 0.80  # act automatically, no warning
CONFIDENCE_WARN: float = 0.50  # warn and act
