from engine.resolvers.shadow_runner import _compute_drift, ShadowResult
from engine.resolvers.element_resolver import CONFIDENCE_MAP


def _sr(strategy, agrees, found=True):
    return ShadowResult(
        strategy=strategy,
        found=found,
        agrees=agrees,
        confidence=CONFIDENCE_MAP.get(strategy, 0.70),
    )


def test_empty_returns_zero():
    assert _compute_drift([]) == 0.0


def test_all_agree_returns_zero():
    results = [_sr("role", True), _sr("css", True), _sr("xpath", True)]
    assert _compute_drift(results) == 0.0


def test_all_disagree_returns_one():
    # Single strategy disagreeing → 100%
    results = [_sr("css", False)]
    assert _compute_drift(results) == 1.0


def test_mixed_weighted():
    # role agrees (weight=0.95), css disagrees (weight=0.75)
    results = [_sr("role", True), _sr("css", False)]
    expected = 0.75 / (0.95 + 0.75)
    assert abs(_compute_drift(results) - expected) < 1e-9


def test_unknown_strategy_uses_fallback():
    # Unknown strategy → fallback weight 0.70, disagrees → drift == 1.0
    results = [ShadowResult(strategy="nonexistent", found=False, agrees=False, confidence=0.70)]
    assert _compute_drift(results) == 1.0


def test_single_disagree_is_one():
    results = [_sr("xpath", False)]
    assert _compute_drift(results) == 1.0
