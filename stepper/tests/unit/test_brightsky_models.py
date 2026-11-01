"""
stepper.brightsky.config and stepper.brightsky.models: the trust boundary to
the BrightSky backend that does no I/O.

config: the bridge token is read from the environment and only ever travels
over https (or http to a loopback host); it appears in no message and no repr.

models: untrusted JSON is validated field by field before anything uses it,
and the bodies stepper sends are checked against the backend's DTO limits.
"""
from __future__ import annotations

import copy
import dataclasses

import pytest

from stepper.brightsky.config import BrightSkyConfigError, load_config
from stepper.brightsky.models import (
    SLUG_PATTERN,
    BrightSkyResponseError,
    Proposal,
    QueueItem,
    RunReport,
    RunStep,
    WorkflowDetail,
    new_idempotency_key,
)

TOKEN = "bst_unit_secret_token_9d1e4b"
URL = "https://bright-sky.example.com"


def _env(**overrides: str) -> dict[str, str]:
    environ = {"BRIGHTSKY_API_URL": URL, "BRIGHTSKY_BRIDGE_TOKEN": TOKEN}
    environ.update(overrides)
    return environ


# ── config ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"])
def test_a_missing_variable_is_named(name):
    environ = _env()
    del environ[name]

    with pytest.raises(BrightSkyConfigError, match=f"^{name} is not set$"):
        load_config(environ)


@pytest.mark.parametrize("name", ["BRIGHTSKY_API_URL", "BRIGHTSKY_BRIDGE_TOKEN"])
@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_blank_variable_is_named(name, blank):
    with pytest.raises(BrightSkyConfigError, match=f"^{name} is not set$"):
        load_config(_env(**{name: blank}))


@pytest.mark.parametrize("url", [
    "ftp://bright-sky.example.com",
    "file:///etc/passwd",
    "ws://localhost:3001",
    "bright-sky.example.com",
])
def test_a_scheme_that_is_not_http_or_https_is_refused(url):
    with pytest.raises(BrightSkyConfigError) as caught:
        load_config(_env(BRIGHTSKY_API_URL=url))

    message = str(caught.value)
    assert "BRIGHTSKY_API_URL" in message
    assert "only sent over https" in message
    assert TOKEN not in message


@pytest.mark.parametrize("url", [
    "http://bright-sky.example.com",
    "http://10.0.0.5:3001",
    "http://localhost.example.com",
    "http://127.0.0.2:3001",
])
def test_http_to_a_host_that_is_not_loopback_is_refused(url):
    with pytest.raises(BrightSkyConfigError) as caught:
        load_config(_env(BRIGHTSKY_API_URL=url))

    message = str(caught.value)
    assert "only sent over https" in message
    assert "localhost, 127.0.0.1 and ::1" in message
    assert TOKEN not in message


@pytest.mark.parametrize("url", [
    "http://localhost:3001",
    "http://LOCALHOST:3001",
    "http://127.0.0.1:3001",
    "http://[::1]:3001",
    "https://bright-sky.example.com",
])
def test_https_anywhere_and_http_to_loopback_are_accepted(url):
    config = load_config(_env(BRIGHTSKY_API_URL=url))

    assert config.api_url == url
    assert config.token == TOKEN


def test_a_trailing_slash_is_stripped():
    config = load_config(_env(BRIGHTSKY_API_URL="http://localhost:3001/"))

    assert config.api_url == "http://localhost:3001"


def test_the_config_is_frozen():
    config = load_config(_env())

    with pytest.raises(dataclasses.FrozenInstanceError):
        setattr(config, "token", "other")


def test_the_token_is_not_in_the_repr_or_str():
    config = load_config(_env())

    assert TOKEN not in repr(config)
    assert TOKEN not in str(config)
    assert URL in repr(config)


def test_a_url_with_no_host_is_refused_without_the_token():
    with pytest.raises(BrightSkyConfigError) as caught:
        load_config(_env(BRIGHTSKY_API_URL="https://"))

    assert "BRIGHTSKY_API_URL" in str(caught.value)
    assert TOKEN not in str(caught.value)


@pytest.mark.parametrize("token", [
    "abc\r\nX-Evil: 1",
    "abc\nX: y",
    "has space",
    "tab\there",
    "nul\x00byte",
    "del\x7fchar",
    "non-ascii-\u00e9",
])
def test_a_token_with_whitespace_or_control_characters_is_refused(token):
    with pytest.raises(BrightSkyConfigError) as caught:
        load_config(_env(BRIGHTSKY_BRIDGE_TOKEN=token))

    message = str(caught.value)
    assert message.startswith("BRIGHTSKY_BRIDGE_TOKEN ")
    for piece in ("abc", "Evil", "space", "tab", "nul", "del", "non-ascii"):
        assert piece not in message


def test_a_token_of_printable_ascii_is_kept_as_is():
    token = "bst_A-z0.9~+/=!"
    config = load_config(_env(BRIGHTSKY_BRIDGE_TOKEN=token))

    assert config.token == token


@pytest.mark.parametrize("url", [
    "https://bright-sky.example.com/?a=1",
    "https://bright-sky.example.com?a=1",
    "https://bright-sky.example.com#frag",
    "https://bright-sky.example.com/api#",
    "https://bright-sky.example.com/api?",
    "http://user:pw@localhost",
    "https://user@bright-sky.example.com",
    "https://a b",
    "http://localhost:abc",
    "http://localhost:99999",
])
def test_a_url_with_a_query_fragment_userinfo_or_bad_host_or_port_is_refused(url):
    with pytest.raises(BrightSkyConfigError) as caught:
        load_config(_env(BRIGHTSKY_API_URL=url))

    message = str(caught.value)
    assert "BRIGHTSKY_API_URL" in message
    assert TOKEN not in message
    assert "pw" not in message


def test_a_base_url_with_a_path_is_accepted():
    config = load_config(_env(BRIGHTSKY_API_URL="https://bright-sky.example.com/api/"))

    assert config.api_url == "https://bright-sky.example.com/api"


# ── readers: QueueItem ────────────────────────────────────────────────────────

def _queue_item(**overrides: object) -> dict:
    item: dict = {
        "workflowId": "wf-1",
        "slug": "openlibrary-find-author",
        "site": "openlibrary.org",
        "versionId": "ver-1",
        "version": 2,
        "source": "claude",
        "createdAt": "2026-10-01T00:00:00.000Z",
        "stepperRuns": 1,
    }
    item.update(overrides)
    return item


def test_a_queue_item_is_read():
    item = QueueItem.from_json(_queue_item())

    assert item == QueueItem(slug="openlibrary-find-author", version=2,
                             stepper_runs=1, created_at="2026-10-01T00:00:00.000Z")


@pytest.mark.parametrize("slug", ["../x", "ab", "Upper-Case", "a/b/c", "x" * 101, 7, None])
def test_a_queue_item_with_a_bad_slug_is_refused(slug):
    with pytest.raises(BrightSkyResponseError, match="slug"):
        QueueItem.from_json(_queue_item(slug=slug))


@pytest.mark.parametrize("field, value", [
    ("version", 0), ("version", "1"), ("version", True), ("version", 1.5),
    ("stepperRuns", -1), ("stepperRuns", "0"), ("stepperRuns", None),
    ("createdAt", 123), ("createdAt", None),
])
def test_a_queue_item_with_a_bad_field_names_it(field, value):
    with pytest.raises(BrightSkyResponseError, match=field):
        QueueItem.from_json(_queue_item(**{field: value}))


@pytest.mark.parametrize("field", ["slug", "version", "stepperRuns", "createdAt"])
def test_a_queue_item_missing_a_field_names_it(field):
    raw = _queue_item()
    del raw[field]

    with pytest.raises(BrightSkyResponseError, match=field):
        QueueItem.from_json(raw)


def test_a_queue_item_that_is_not_an_object_is_refused():
    with pytest.raises(BrightSkyResponseError):
        QueueItem.from_json(["openlibrary-find-author", 1])


def test_the_slug_pattern_is_the_backend_one():
    assert SLUG_PATTERN.fullmatch("openlibrary-find-author")
    assert not SLUG_PATTERN.fullmatch("../x")
    assert not SLUG_PATTERN.fullmatch("abc\n")


@pytest.mark.parametrize("method", ["match", "search", "fullmatch"])
def test_the_slug_pattern_refuses_a_trailing_newline_with_any_method(method):
    assert getattr(SLUG_PATTERN, method)("abc\n") is None
    assert getattr(SLUG_PATTERN, method)("openlibrary-find-author") is not None


# ── readers: WorkflowDetail ───────────────────────────────────────────────────

def _step(title: object = "Search for 'The Hobbit'") -> dict:
    return {
        "title": title,
        "explanation": "Type it and press Enter.",
        "expectedUrl": "/",
        "target": {"role": "textbox", "accessibleName": "Search", "selectors": [],
                   "score": 0.8, "grounding": "current_page"},
        "expectedOutcome": {"kind": "url_change", "urlContains": "/search"},
    }


def _version(n: int, note: str | None = None) -> dict:
    return {"id": f"ver-{n}", "version": n, "status": "unverified", "source": "claude",
            "note": note, "createdAt": "2026-10-30T10:00:00.000Z", "createdBy": "seed"}


def _detail(**overrides: object) -> dict:
    detail: dict = {
        "id": "wf-1",
        "slug": "openlibrary-find-author",
        "site": "openlibrary.org",
        "title": "Find a book's author",
        "category": "research",
        "objective": "Find who wrote The Hobbit",
        "urlPatterns": [],
        "currentVersion": _version(2),
        "currentSteps": [_step(), _step("Open the book page")],
        "versions": [_version(1, "seed"), _version(2)],
    }
    detail.update(overrides)
    return detail


def test_a_workflow_detail_is_read():
    raw = _detail()
    detail = WorkflowDetail.from_json(raw)

    assert detail.slug == "openlibrary-find-author"
    assert detail.site == "openlibrary.org"
    assert detail.current_version == 2
    assert detail.versions == [(1, "seed"), (2, None)]
    assert detail.steps == raw["currentSteps"]


def test_the_steps_are_kept_as_received():
    raw = _detail()
    expected = copy.deepcopy(raw["currentSteps"])

    detail = WorkflowDetail.from_json(raw)

    assert detail.steps == expected
    assert detail.steps[0]["target"]["accessibleName"] == "Search"


def test_a_detail_with_no_current_version_names_it():
    raw = _detail()
    del raw["currentVersion"]

    with pytest.raises(BrightSkyResponseError, match="currentVersion"):
        WorkflowDetail.from_json(raw)


def test_a_detail_with_a_null_current_version_names_it():
    with pytest.raises(BrightSkyResponseError, match="currentVersion"):
        WorkflowDetail.from_json(_detail(currentVersion=None))


@pytest.mark.parametrize("version", [0, "2", None, True, 2.0])
def test_a_detail_with_a_non_int_version_names_it(version):
    current = _version(2)
    current["version"] = version

    with pytest.raises(BrightSkyResponseError, match=r"currentVersion\.version"):
        WorkflowDetail.from_json(_detail(currentVersion=current))


def test_a_detail_with_51_steps_names_the_steps():
    with pytest.raises(BrightSkyResponseError, match="currentSteps"):
        WorkflowDetail.from_json(_detail(currentSteps=[_step()] * 51))


def test_a_detail_with_50_steps_is_read():
    detail = WorkflowDetail.from_json(_detail(currentSteps=[_step()] * 50))

    assert len(detail.steps) == 50


def test_a_detail_with_no_steps_names_the_steps():
    with pytest.raises(BrightSkyResponseError, match="currentSteps"):
        WorkflowDetail.from_json(_detail(currentSteps=[]))


@pytest.mark.parametrize("steps", [None, {"title": "x"}, "steps"])
def test_a_detail_whose_steps_are_not_a_list_names_them(steps):
    with pytest.raises(BrightSkyResponseError, match="currentSteps"):
        WorkflowDetail.from_json(_detail(currentSteps=steps))


def test_a_step_that_is_not_an_object_names_its_index():
    with pytest.raises(BrightSkyResponseError, match=r"currentSteps\[1\]"):
        WorkflowDetail.from_json(_detail(currentSteps=[_step(), "click it"]))


@pytest.mark.parametrize("title", [42, None, ["a"]])
def test_a_step_with_a_non_str_title_names_the_field(title):
    with pytest.raises(BrightSkyResponseError, match=r"currentSteps\[1\]\.title"):
        WorkflowDetail.from_json(_detail(currentSteps=[_step(), _step(title)]))


def test_a_step_with_no_title_names_the_field():
    step = _step()
    del step["title"]

    with pytest.raises(BrightSkyResponseError, match=r"currentSteps\[0\]\.title"):
        WorkflowDetail.from_json(_detail(currentSteps=[step]))


@pytest.mark.parametrize("field, value", [("slug", "../x"), ("slug", None), ("site", 5),
                                          ("site", None)])
def test_a_detail_with_a_bad_slug_or_site_names_it(field, value):
    with pytest.raises(BrightSkyResponseError, match=field):
        WorkflowDetail.from_json(_detail(**{field: value}))


@pytest.mark.parametrize("versions, field", [
    (None, "versions"),
    ([_version(1), "v2"], r"versions\[1\]"),
    ([{**_version(1), "version": "1"}], r"versions\[0\]\.version"),
    ([{**_version(1), "note": 7}], r"versions\[0\]\.note"),
])
def test_a_detail_with_bad_versions_names_the_field(versions, field):
    with pytest.raises(BrightSkyResponseError, match=field):
        WorkflowDetail.from_json(_detail(versions=versions))


def test_a_detail_that_is_not_an_object_is_refused():
    with pytest.raises(BrightSkyResponseError):
        WorkflowDetail.from_json([_detail()])


def test_a_response_error_carries_no_token_by_construction():
    """The readers echo field names, not values, so a body cannot smuggle text out."""
    with pytest.raises(BrightSkyResponseError) as caught:
        QueueItem.from_json(_queue_item(slug=TOKEN.upper()))

    assert TOKEN.upper() not in str(caught.value)


# ── writers: RunStep, RunReport, Proposal ─────────────────────────────────────

def test_a_run_report_has_the_dto_keys():
    report = RunReport(
        version=3,
        steps=[RunStep(step_number=1, matched=True, tier="role", outcome="passed"),
               RunStep(step_number=2, matched=False, tier=None, outcome="failed"),
               RunStep(step_number=3, matched=False, tier=None, outcome="unchecked")],
        result="failed",
        idempotency_key="stepper-abc",
    )

    assert report.to_json() == {
        "version": 3,
        "steps": [
            {"stepNumber": 1, "matched": True, "tier": "role", "outcome": "passed"},
            {"stepNumber": 2, "matched": False, "tier": None, "outcome": "failed"},
            {"stepNumber": 3, "matched": False, "tier": None, "outcome": "unchecked"},
        ],
        "result": "failed",
        "client": "stepper",
        "idempotencyKey": "stepper-abc",
    }


def test_a_duplicate_step_number_raises():
    steps = [RunStep(step_number=1, matched=True, tier="role", outcome="passed"),
             RunStep(step_number=1, matched=True, tier="role", outcome="passed")]

    with pytest.raises(ValueError, match="step"):
        RunReport(version=1, steps=steps, result="passed", idempotency_key="k")


def test_more_than_50_steps_raises():
    steps = [RunStep(step_number=n, matched=True, tier="role", outcome="passed")
             for n in range(1, 52)]

    with pytest.raises(ValueError, match="50"):
        RunReport(version=1, steps=steps, result="passed", idempotency_key="k")


@pytest.mark.parametrize("result", ["healed", "PASSED", ""])
def test_an_unknown_result_raises(result):
    with pytest.raises(ValueError, match="result"):
        RunReport(version=1, steps=[], result=result, idempotency_key="k")


@pytest.mark.parametrize("key", ["", "k" * 101])
def test_an_idempotency_key_out_of_bounds_raises(key):
    with pytest.raises(ValueError, match="idempotency"):
        RunReport(version=1, steps=[], result="passed", idempotency_key=key)


def test_an_idempotency_key_of_100_characters_is_accepted():
    report = RunReport(version=1, steps=[], result="passed", idempotency_key="k" * 100)

    assert report.to_json()["idempotencyKey"] == "k" * 100


@pytest.mark.parametrize("outcome", ["healed", "skipped", ""])
def test_an_unknown_outcome_raises(outcome):
    with pytest.raises(ValueError, match="outcome"):
        RunStep(step_number=1, matched=True, tier=None, outcome=outcome)


def test_a_tier_over_100_characters_raises():
    with pytest.raises(ValueError, match="tier"):
        RunStep(step_number=1, matched=True, tier="t" * 101, outcome="passed")


def test_a_tier_of_100_characters_is_accepted():
    step = RunStep(step_number=1, matched=True, tier="t" * 100, outcome="passed")

    assert step.to_json()["tier"] == "t" * 100


@pytest.mark.parametrize("version", [0, -1, True, "1", 1.0, None, 2_147_483_648])
def test_a_run_report_with_a_bad_version_raises(version):
    with pytest.raises(ValueError, match="version"):
        RunReport(version=version, steps=[], result="passed", idempotency_key="k")


def test_a_run_report_of_the_largest_version_is_accepted():
    report = RunReport(version=2_147_483_647, steps=[], result="passed",
                       idempotency_key="k")

    assert report.to_json()["version"] == 2_147_483_647


@pytest.mark.parametrize("steps", [None, ("not", "a list"), [{"stepNumber": 1}]])
def test_a_run_report_whose_steps_are_not_run_steps_raises(steps):
    with pytest.raises(ValueError, match="steps"):
        RunReport(version=1, steps=steps, result="passed", idempotency_key="k")


@pytest.mark.parametrize("result", [None, 1, ["passed"]])
def test_a_result_that_is_not_a_string_raises_value_error(result):
    with pytest.raises(ValueError, match="result"):
        RunReport(version=1, steps=[], result=result, idempotency_key="k")


@pytest.mark.parametrize("key", [None, 5, b"stepper-abc"])
def test_an_idempotency_key_that_is_not_a_string_raises_value_error(key):
    with pytest.raises(ValueError, match="idempotency"):
        RunReport(version=1, steps=[], result="passed", idempotency_key=key)


@pytest.mark.parametrize("number", [0, -1, 51, True, "1", 1.0, None])
def test_a_bad_step_number_raises(number):
    with pytest.raises(ValueError, match="step number"):
        RunStep(step_number=number, matched=True, tier=None, outcome="passed")


def test_step_number_50_is_accepted():
    assert RunStep(step_number=50, matched=True, tier=None,
                   outcome="passed").to_json()["stepNumber"] == 50


@pytest.mark.parametrize("matched", ["yes", 1, 0, None])
def test_matched_that_is_not_a_bool_raises(matched):
    with pytest.raises(ValueError, match="matched"):
        RunStep(step_number=1, matched=matched, tier=None, outcome="passed")


@pytest.mark.parametrize("tier", [5, ["role"], b"role"])
def test_a_tier_that_is_not_a_string_or_none_raises_value_error(tier):
    with pytest.raises(ValueError, match="tier"):
        RunStep(step_number=1, matched=True, tier=tier, outcome="passed")


@pytest.mark.parametrize("outcome", [None, 1, ["passed"]])
def test_an_outcome_that_is_not_a_string_raises_value_error(outcome):
    with pytest.raises(ValueError, match="outcome"):
        RunStep(step_number=1, matched=True, tier=None, outcome=outcome)


def test_a_proposal_has_the_dto_keys():
    steps = [_step(), _step("Open the book page")]
    proposal = Proposal(steps=steps, source="haiku", note="healed by stepper-abc")

    assert proposal.to_json() == {"steps": steps, "source": "haiku",
                                  "note": "healed by stepper-abc"}


@pytest.mark.parametrize("source", ["claude", "human", "seed", ""])
def test_a_proposal_source_other_than_stepper_or_haiku_raises(source):
    with pytest.raises(ValueError, match="source"):
        Proposal(steps=[_step()], source=source, note="n")


def test_a_long_note_is_cut_to_1000_characters():
    proposal = Proposal(steps=[_step()], source="stepper", note="n" * 1500)

    note = proposal.to_json()["note"]
    assert len(note) == 1000
    assert note.endswith("…")
    assert note[:999] == "n" * 999


def test_a_note_of_1000_characters_is_kept():
    proposal = Proposal(steps=[_step()], source="stepper", note="n" * 1000)

    assert proposal.note == "n" * 1000


@pytest.mark.parametrize("steps", [[], None, "steps", {"title": "x"}])
def test_a_proposal_without_a_list_of_1_to_50_steps_raises(steps):
    with pytest.raises(ValueError, match="steps"):
        Proposal(steps=steps, source="stepper", note="n")


def test_a_proposal_with_51_steps_raises():
    with pytest.raises(ValueError, match="50"):
        Proposal(steps=[_step() for _ in range(51)], source="stepper", note="n")


def test_a_proposal_with_50_steps_is_accepted():
    steps = [_step() for _ in range(50)]

    assert Proposal(steps=steps, source="stepper", note="n").to_json()["steps"] == steps


def test_a_proposal_step_that_is_not_an_object_raises():
    with pytest.raises(ValueError, match="steps"):
        Proposal(steps=[_step(), "step"], source="stepper", note="n")


@pytest.mark.parametrize("source", [None, 1, ["stepper"]])
def test_a_source_that_is_not_a_string_raises_value_error(source):
    with pytest.raises(ValueError, match="source"):
        Proposal(steps=[_step()], source=source, note="n")


@pytest.mark.parametrize("note", [None, 5, b"note"])
def test_a_note_that_is_not_a_string_raises_value_error(note):
    with pytest.raises(ValueError, match="note"):
        Proposal(steps=[_step()], source="stepper", note=note)


def test_an_idempotency_key_is_stepper_and_a_uuid4_hex():
    key = new_idempotency_key()

    assert key.startswith("stepper-")
    hex_part = key[len("stepper-"):]
    assert len(hex_part) == 32
    int(hex_part, 16)
    assert new_idempotency_key() != key
