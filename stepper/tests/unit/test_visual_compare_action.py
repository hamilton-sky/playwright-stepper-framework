"""
VisualCompareAction — baseline lifecycle, the diff maths, and the noise floor.

The largest untested action in the engine: 171 lines and 22 branch points. It is
also the one whose failure mode is most annoying to debug by hand — a threshold
or noise-floor mistake shows up as a visual test that passes when it should fail,
which is indistinguishable from the UI being fine.

No browser and no image fixtures on disk: the page stub returns PNG bytes built
in-process by Pillow, so a test can state exactly how many pixels differ and by
how much.
"""
from __future__ import annotations

import asyncio
import io
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image

from engine.actions.strategies import VisualCompareAction
from engine.interfaces import ExecutionContext, StepConfig


# ── Image helpers ─────────────────────────────────────────────────────────────

SIZE = (10, 10)          # 100 pixels, so one pixel is exactly 1%


def png(colour=(0, 0, 0), size=SIZE) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="PNG")
    return buffer.getvalue()


def png_with(changed: int, colour=(0, 0, 0), changed_colour=(255, 255, 255),
             size=SIZE) -> bytes:
    """A solid image with exactly `changed` pixels set to another colour."""
    image = Image.new("RGB", size, colour)
    pixels = image.load()
    assert pixels is not None
    for i in range(changed):
        pixels[i % size[0], i // size[0]] = changed_colour
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def png_corner(size=(20, 20), corner=(10, 10),
               corner_colour=(0, 0, 0), rest_colour=(255, 255, 255)) -> bytes:
    """An image whose top-left `corner` is one colour and the rest another."""
    image = Image.new("RGB", size, rest_colour)
    for x in range(corner[0]):
        for y in range(corner[1]):
            image.putpixel((x, y), corner_colour)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def write_baseline(action, name: str, data: bytes) -> None:
    action._baselines_dir.mkdir(parents=True, exist_ok=True)
    (action._baselines_dir / f"{name}.png").write_bytes(data)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def action(tmp_path):
    """
    The action, with its baselines redirected into tmp_path.

    Reaching for the private attribute is deliberate: the directory is a
    constructor-time constant pointing at the repo, and a test must never write
    a baseline into stepper/artifacts/.
    """
    instance = VisualCompareAction()
    instance._baselines_dir = tmp_path / "baselines"
    return instance


def page_returning(data: bytes):
    page = MagicMock()
    page.screenshot = AsyncMock(return_value=data)
    return page


def compare(action, page, **extra):
    extra.setdefault("snapshot_name", "shot")
    step = StepConfig(action="visual_compare", description="compare", extra=extra)
    return asyncio.run(action.execute(page, step, MagicMock(), ExecutionContext()))


# ── Construction ──────────────────────────────────────────────────────────────

def test_constructing_the_action_creates_no_directories(tmp_path, monkeypatch):
    """
    build_default_registry() constructs every action, so a mkdir in __init__ made
    read-only commands like `list` create directories just to print a table.
    """
    import engine.actions.strategies as strategies

    monkeypatch.setattr(strategies, "_stepper_root", tmp_path)
    VisualCompareAction()

    assert not (tmp_path / "artifacts").exists()


# ── Required input ────────────────────────────────────────────────────────────

def test_a_missing_snapshot_name_fails_with_the_field_named(action):
    step = StepConfig(action="visual_compare", description="c", extra={})

    result = asyncio.run(action.execute(page_returning(png()), step,
                                        MagicMock(), ExecutionContext()))

    assert result.status == "failed"
    assert "extra.snapshot_name" in result.error


def test_a_missing_snapshot_name_does_not_take_a_screenshot(action):
    page = page_returning(png())
    step = StepConfig(action="visual_compare", description="c", extra={})

    asyncio.run(action.execute(page, step, MagicMock(), ExecutionContext()))

    page.screenshot.assert_not_awaited()


# ── First run bootstraps the baseline ─────────────────────────────────────────

def test_the_first_run_saves_the_baseline_and_passes(action):
    result = compare(action, page_returning(png((10, 20, 30))))

    assert result.status == "passed"
    assert result.output["mode"] == "baseline_created"
    assert (action._baselines_dir / "shot.png").exists()


def test_the_saved_baseline_is_the_screenshot_that_was_taken(action):
    compare(action, page_returning(png((10, 20, 30))))

    saved = Image.open(action._baselines_dir / "shot.png").convert("RGB")
    assert saved.getpixel((0, 0)) == (10, 20, 30)


def test_the_first_run_creates_the_baselines_directory(action):
    assert not action._baselines_dir.exists()

    compare(action, page_returning(png()))

    assert action._baselines_dir.is_dir()


# ── Update mode ───────────────────────────────────────────────────────────────

def test_update_overwrites_an_existing_baseline_and_passes(action):
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png((255, 255, 255))), update=True)

    assert result.status == "passed"
    assert result.output["mode"] == "updated"
    saved = Image.open(action._baselines_dir / "shot.png").convert("RGB")
    assert saved.getpixel((0, 0)) == (255, 255, 255)


def test_update_passes_however_different_the_screenshot_is(action):
    """An approved UI change should not have to squeeze under the threshold."""
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png((255, 255, 255))),
                     update=True, threshold=0.0)

    assert result.status == "passed"


# ── Comparison ────────────────────────────────────────────────────────────────

def test_an_identical_screenshot_passes(action):
    write_baseline(action, "shot", png((40, 50, 60)))

    result = compare(action, page_returning(png((40, 50, 60))))

    assert result.status == "passed"
    assert result.output["diff_ratio"] == 0.0


def test_a_difference_under_the_threshold_passes(action):
    """2 of 100 pixels changed = 2%, under a 5% threshold."""
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png_with(2)), threshold=0.05)

    assert result.status == "passed"
    assert result.output["diff_ratio"] == pytest.approx(0.02)


def test_a_difference_over_the_threshold_fails(action):
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png_with(10)), threshold=0.05)

    assert result.status == "failed"
    assert result.output["diff_ratio"] == pytest.approx(0.10)


def test_the_threshold_is_exclusive(action):
    """Exactly at the threshold passes; the check is `>`, not `>=`."""
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png_with(5)), threshold=0.05)

    assert result.status == "passed"


def test_the_default_threshold_is_one_percent(action):
    write_baseline(action, "shot", png((0, 0, 0)))

    assert compare(action, page_returning(png_with(1))).status == "passed"
    assert compare(action, page_returning(png_with(2))).status == "failed"


# ── The noise floor ───────────────────────────────────────────────────────────

def test_a_difference_of_eight_is_below_the_noise_floor(action):
    """
    Anti-aliasing and compression jitter a channel by a few units. The action
    only counts a pixel when a channel differs by MORE than 8, so a uniform
    8-unit shift must read as no change at all — even at a zero threshold.
    """
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png((8, 8, 8))), threshold=0.0)

    assert result.status == "passed"
    assert result.output["diff_ratio"] == 0.0


def test_a_difference_of_nine_is_counted(action):
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png((9, 9, 9))), threshold=0.0)

    assert result.status == "failed"
    assert result.output["diff_ratio"] == 1.0


def test_one_channel_over_the_floor_is_enough(action):
    """The test is max(r, g, b) — a single channel drifting counts the pixel."""
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png((0, 0, 20))), threshold=0.0)

    assert result.status == "failed"


# ── The diff image ────────────────────────────────────────────────────────────

def test_a_failure_writes_a_diff_image_next_to_the_baseline(action):
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png_with(50)), threshold=0.01)

    diff_path = action._baselines_dir / "shot.diff.png"
    assert diff_path.exists()
    assert result.output["diff_image"] == str(diff_path)


def test_the_diff_image_is_attached_as_the_result_screenshot(action):
    """So the reporter surfaces it the same way it surfaces any step capture."""
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png_with(50)), threshold=0.01)

    assert result.screenshot == str(action._baselines_dir / "shot.diff.png")


def test_a_pass_writes_no_diff_image(action):
    write_baseline(action, "shot", png((0, 0, 0)))

    compare(action, page_returning(png((0, 0, 0))))

    assert not (action._baselines_dir / "shot.diff.png").exists()


def test_the_failure_message_carries_both_percentages(action):
    write_baseline(action, "shot", png((0, 0, 0)))

    result = compare(action, page_returning(png_with(10)), threshold=0.05)

    assert "10.00%" in result.error and "5.00%" in result.error
    assert "shot" in result.error


# ── Size mismatch ─────────────────────────────────────────────────────────────

def test_a_differently_sized_screenshot_is_scaled_not_cropped(action):
    """
    ImageChops.difference does not raise on mismatched sizes — it silently crops
    to the smaller one. Without the resize, a screenshot twice the baseline's
    size would be judged on its top-left quarter alone and the other 75% would
    go unexamined.

    The current shot here is black exactly where the baseline is, and white
    everywhere else. Cropped, it looks identical; scaled, it plainly is not.
    """
    write_baseline(action, "shot", png((0, 0, 0), size=(10, 10)))

    result = compare(action, page_returning(png_corner()))

    assert result.status == "failed", "the white three-quarters were ignored"
    assert result.output["diff_ratio"] > 0.5


def test_a_differently_sized_but_matching_screenshot_still_passes(action):
    """Scaling must not manufacture a difference where there is none."""
    write_baseline(action, "shot", png((0, 0, 0), size=(10, 10)))

    result = compare(action, page_returning(png((0, 0, 0), size=(20, 20))))

    assert result.status == "passed"
    assert result.output["diff_ratio"] == 0.0


# ── Screenshot options ────────────────────────────────────────────────────────

@pytest.mark.parametrize("full_page", [True, False])
def test_full_page_is_forwarded_to_the_screenshot(full_page, action):
    page = page_returning(png())

    compare(action, page, full_page=full_page)

    page.screenshot.assert_awaited_once_with(full_page=full_page)


def test_full_page_defaults_to_false(action):
    page = page_returning(png())

    compare(action, page)

    page.screenshot.assert_awaited_once_with(full_page=False)


# ── Snapshot naming ───────────────────────────────────────────────────────────

def test_each_snapshot_name_gets_its_own_baseline(action):
    compare(action, page_returning(png((10, 10, 10))), snapshot_name="one")
    compare(action, page_returning(png((20, 20, 20))), snapshot_name="two")

    assert (action._baselines_dir / "one.png").exists()
    assert (action._baselines_dir / "two.png").exists()
    assert Image.open(action._baselines_dir / "one.png").convert("RGB").getpixel((0, 0)) \
        == (10, 10, 10)


def test_the_snapshot_name_is_echoed_in_the_output(action):
    result = compare(action, page_returning(png()), snapshot_name="shelf-after-add")

    assert result.output["snapshot"] == "shelf-after-add"


# ── Declared contract ─────────────────────────────────────────────────────────

def test_visual_compare_is_read_only():
    """It only screenshots, so it is safe inside a parallel step."""
    assert VisualCompareAction().read_only is True
