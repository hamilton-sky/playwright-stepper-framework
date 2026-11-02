"""
Acceptance tests for brightsky-verify, written from plans/brightsky-verify/spec.md.

Every test here is offline: the BrightSky backend is a recording fake
`client.Transport`, the browser is a page double handed to
`executor.EngineExecutor`, and the two heal-loop page probes are monkeypatched,
exactly as the spec's "Heal and propose" story and its Interfaces describe.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_here = Path(__file__).resolve().parent
_repo_root = _here.parent.parent.parent
for entry in (str(_here), str(_repo_root)):
    if entry not in sys.path:
        sys.path.insert(0, entry)


_ENV_TO_CLEAR = (
    "BRIGHTSKY_API_URL",
    "BRIGHTSKY_BRIDGE_TOKEN",
    "ANTHROPIC_API_KEY",
    "GROQ_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolated_environment(monkeypatch, tmp_path):
    """No real keys, no .env, no human pauses, no files written into the repo."""
    for name in _ENV_TO_CLEAR:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("INTER_STEP_DELAY_MS", "0")
    monkeypatch.setenv("HOVER_MS", "0")
    # load_env() reads .env through python-dotenv; a developer's .env must not
    # leak a real token or URL into a test.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **kw: False)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _no_embedding_model_loads(monkeypatch):
    """Same guard as the unit suite: nothing here may load an embedding model."""
    def _refuse(self, *a, **kw):
        raise AssertionError("an acceptance test loaded a real SemanticResolver model")

    monkeypatch.setattr(
        "stepper.engine.resolvers.strategies.SemanticResolver._load", _refuse
    )
