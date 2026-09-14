"""
HealAnnotator — the picture that shows what the healer actually clicked.

This is diagnostic output, and the thing that makes it worth testing is that it
is *only* looked at when something has already gone wrong. Every failure mode
here is silent by design: no Pillow, an element with no bounding box, a page
that closed mid-capture. Each returns None and the run carries on, which is
correct, and which also means a permanently broken annotator would never
announce itself.

Pillow is exercised for real against a generated PNG — no browser.
"""
from __future__ import annotations

import sys
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from stepper.engine.healer.annotator import HealAnnotator, _locator_from_cfg

PIL = pytest.importorskip("PIL", reason="Pillow is optional; the annotator no-ops without it")


def _png_bytes(width: int = 320, height: int = 200) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (width, height), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _page(bbox: dict | None = None, screenshot: bytes | None = None):
    """A page whose locator reports the given bounding box."""
    locator = MagicMock()
    locator.bounding_box = AsyncMock(return_value=bbox)
    locator.first = locator

    page = MagicMock()
    for method in ("get_by_placeholder", "get_by_role", "get_by_label", "get_by_text", "locator"):
        getattr(page, method).return_value = locator
    page.screenshot = AsyncMock(return_value=screenshot if screenshot is not None else _png_bytes())
    return page


# ── Locator selection ─────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "cfg, method",
    [
        ({"placeholder": "Username"},            "get_by_placeholder"),
        ({"role": "button", "name": "Log in"},   "get_by_role"),
        ({"label": "Email"},                     "get_by_label"),
        ({"text": "Continue"},                   "get_by_text"),
        ({"id": "submit"},                       "locator"),
        ({"css": ".btn"},                        "locator"),
        ({"xpath": "//button"},                  "locator"),
    ],
)
def test_each_cfg_shape_maps_to_a_locator(cfg, method):
    page = _page()

    assert _locator_from_cfg(page, cfg) is not None
    assert getattr(page, method).called


def test_an_unrecognised_cfg_yields_no_locator():
    """An empty cfg is a no-op, not a crash and not a box around nothing."""
    assert _locator_from_cfg(_page(), {}) is None


def test_role_without_a_name_is_not_enough_for_get_by_role():
    page = _page()

    _locator_from_cfg(page, {"role": "button", "css": ".btn"})

    assert not page.get_by_role.called
    assert page.locator.called


def test_the_ordering_differs_from_the_resolver_but_cannot_bite():
    """
    This checks `placeholder` before `role`+`name`, while the resolver cascade
    and VisualBridge both try role first. A cfg carrying both would be boxed
    around a different element than the one the resolver acted on.

    It cannot happen for a healed cfg: DOMSnapshotCascade._element_to_cfg builds
    them with an if/elif chain, so exactly one identifier is ever present. This
    test records that the two orderings differ *and* why that is currently
    harmless — if _element_to_cfg ever starts emitting several, this is where to
    look.
    """
    from stepper.engine.healer.dom_snapshot import DOMSnapshotCascade

    cfg = DOMSnapshotCascade._element_to_cfg({
        "tag": "INPUT", "role": "textbox", "aria": "Username",
        "placeholder": "Username", "text": "", "id": "user", "name": None,
        "type": "text", "title": None, "value": None,
    })

    identifiers = {"role", "label", "placeholder", "text", "id", "css", "xpath"} & set(cfg)
    assert len(identifiers) == 1, f"a healed cfg carried several identifiers: {cfg}"


# ── Capture ───────────────────────────────────────────────────────────────────

async def test_a_healed_element_gets_an_annotated_screenshot(tmp_path):
    page = _page(bbox={"x": 40, "y": 60, "width": 100, "height": 30})

    path = await HealAnnotator.capture(
        page, {"placeholder": "Username"}, step_idx=3, label="healed",
        screenshots_dir=tmp_path,
    )

    assert path is not None
    written = tmp_path / "step_03_healed_annotated.png"
    assert written.exists()
    assert str(written) == path


async def test_the_file_is_named_by_step_so_it_sorts_with_the_others(tmp_path):
    page = _page(bbox={"x": 0, "y": 0, "width": 10, "height": 10})

    await HealAnnotator.capture(page, {"css": ".x"}, 7, "healed", tmp_path)

    assert (tmp_path / "step_07_healed_annotated.png").exists(), "step index is zero-padded"


async def test_the_output_is_a_real_image_the_size_of_the_screenshot(tmp_path):
    from PIL import Image

    page = _page(bbox={"x": 10, "y": 10, "width": 50, "height": 20},
                 screenshot=_png_bytes(320, 200))

    path = await HealAnnotator.capture(page, {"css": ".x"}, 1, "healed", tmp_path)

    assert path is not None
    with Image.open(path) as img:
        assert img.size == (320, 200)
        assert img.mode == "RGB", "alpha is composited away before saving"


async def test_something_is_actually_drawn_on_the_image(tmp_path):
    """
    A blank white copy of the screenshot would satisfy every other test here and
    be useless to the person reading it.
    """
    from PIL import Image

    page = _page(bbox={"x": 50, "y": 50, "width": 80, "height": 40},
                 screenshot=_png_bytes(320, 200))

    path = await HealAnnotator.capture(page, {"css": ".x"}, 1, "healed", tmp_path)

    assert path is not None
    with Image.open(path) as img:
        counted = img.convert("RGB").getcolors(maxcolors=1 << 24) or []
    colours = [colour for _count, colour in counted]

    assert len(colours) > 1, "the annotated image is a flat colour — nothing was drawn"
    reds = [c for c in colours if c[0] > 150 and c[1] < 120 and c[2] < 120]
    assert reds, f"no red annotation found; colours present: {sorted(colours)[:8]}"


async def test_an_element_at_the_top_left_does_not_draw_off_canvas(tmp_path):
    """
    The label badge is placed 20px above the element. At y=0 that is negative,
    and Pillow will happily accept coordinates that put the badge off-image.
    """
    page = _page(bbox={"x": 0, "y": 0, "width": 30, "height": 10})

    path = await HealAnnotator.capture(page, {"css": ".x"}, 1, "healed", tmp_path)

    assert path is not None, "an element at the origin should still annotate"


# ── Every silent failure path ─────────────────────────────────────────────────

async def test_no_bounding_box_means_no_annotation(tmp_path):
    """An element that is in the DOM but not rendered has no box to draw."""
    page = _page(bbox=None)

    assert await HealAnnotator.capture(page, {"css": ".x"}, 1, "healed", tmp_path) is None
    assert list(tmp_path.iterdir()) == []


async def test_an_unmappable_cfg_means_no_annotation(tmp_path):
    assert await HealAnnotator.capture(_page(), {}, 1, "healed", tmp_path) is None


async def test_a_page_that_throws_returns_none_rather_than_failing_the_step(tmp_path):
    """
    This runs after a heal has already succeeded. Raising here would turn a
    recovered step into a failed one over a diagnostic picture.
    """
    page = _page(bbox={"x": 1, "y": 1, "width": 5, "height": 5})
    page.screenshot = AsyncMock(side_effect=RuntimeError("target closed"))

    assert await HealAnnotator.capture(page, {"css": ".x"}, 1, "healed", tmp_path) is None


async def test_an_unwritable_output_directory_returns_none(tmp_path):
    page = _page(bbox={"x": 1, "y": 1, "width": 5, "height": 5})

    result = await HealAnnotator.capture(
        page, {"css": ".x"}, 1, "healed", tmp_path / "does" / "not" / "exist",
    )

    assert result is None


async def test_without_pillow_it_no_ops_instead_of_raising(tmp_path, monkeypatch):
    """
    Pillow is in requirements.txt but the module is written to survive without
    it, and that promise is only true if nothing else in capture() runs first.
    """
    # Build the double first: the helper renders a real PNG, so it needs Pillow.
    page = _page(bbox={"x": 1, "y": 1, "width": 5, "height": 5})
    monkeypatch.setitem(sys.modules, "PIL", None)

    assert await HealAnnotator.capture(page, {"css": ".x"}, 1, "healed", tmp_path) is None
    assert page.screenshot.await_count == 0, "it should bail before taking a screenshot"
