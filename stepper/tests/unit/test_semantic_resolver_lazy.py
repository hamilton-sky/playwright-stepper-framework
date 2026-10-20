"""SemanticResolver loads its embedding model on the first score(), not when built."""
from __future__ import annotations

from stepper.engine.resolvers.strategies import SemanticResolver


def test_building_one_loads_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(SemanticResolver, "_load", lambda self: calls.append(self))
    SemanticResolver()
    assert calls == []


def test_the_first_score_loads_once_and_falls_back_to_jaccard(monkeypatch):
    calls = []

    def fake_load(self):
        calls.append(self)
        self._loaded = True          # as the real one does; no model, so Jaccard

    monkeypatch.setattr(SemanticResolver, "_load", fake_load)
    sem = SemanticResolver()
    assert sem.score("add to cart", "add to cart") == 1.0
    assert sem.score("add to cart", "remove") == 0.0
    assert len(calls) == 1


def test_empty_input_scores_zero_without_loading(monkeypatch):
    calls = []
    monkeypatch.setattr(SemanticResolver, "_load", lambda self: calls.append(self))
    assert SemanticResolver().score("", "x") == 0.0
    assert calls == []
