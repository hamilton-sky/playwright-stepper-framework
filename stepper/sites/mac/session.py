"""
sites/mac/session.py — The mac domain's SessionAdapter, and its preflight.

There is nothing to open: most mac actions shell out to `osascript` per step
(`mac_drag` drives CoreGraphics directly, `mac_screenshot` shells out to
`screencapture` — see below), so the session is a thin handle object rather
than a connection. It exists because the Domain contract requires a session
factory, and because it gives actions one shared place to run subprocesses
(timeout, error mapping) instead of each action reimplementing them.

`mac_drag` is the exception to the osascript rule: System Events has no drag
verb, so the gesture is synthesized with CoreGraphics mouse events posted from
a small stdlib-only Python child (ctypes — no pyobjc, no extra installs). Like
the other UI primitives it needs Accessibility permission.

`mac_screenshot` shells out to `screencapture` (all displays, PNG). It needs
Screen Recording permission — the first run makes macOS show the consent
dialog, same as the Accessibility one.

Preflight is honest about the platform: osascript only exists on macOS, so a
run on Linux fails here with a clear reason instead of failing at the first
mac step with "osascript: command not found".
"""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
import sys

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 30


# Child script for mac_drag: posts a press-drag-release gesture through
# CoreGraphics using only ctypes (stdlib). It runs under the same interpreter
# as the workflow (sys.executable), so there is nothing extra to install.
# Args: x1 y1 x2 y2 [steps].
_DRAG_PY = """
import ctypes
import sys
import time


def _fail(msg):
    sys.stderr.write("drag: " + msg + "\\n")
    sys.exit(4)


try:
    x1, y1, x2, y2 = (int(sys.argv[1]), int(sys.argv[2]),
                      int(sys.argv[3]), int(sys.argv[4]))
    steps = max(1, int(sys.argv[5])) if len(sys.argv) > 5 else 20
except (IndexError, ValueError):
    _fail("usage: drag x1 y1 x2 y2 [steps]")

try:
    cg = ctypes.CDLL(
        "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics")
except OSError as exc:
    _fail("CoreGraphics unavailable (macOS only): %s" % exc)

try:
    ax = ctypes.CDLL(
        "/System/Library/Frameworks/ApplicationServices.framework/"
        "ApplicationServices")
    ax.AXIsProcessTrusted.restype = ctypes.c_bool
    if not ax.AXIsProcessTrusted():
        _fail("Accessibility permission not granted to this Python "
              "(System Settings > Privacy & Security > Accessibility)")
except OSError:
    pass  # best-effort check only; the gesture itself is the real test


class CGPoint(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]


cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
cg.CGEventCreateMouseEvent.argtypes = [
    ctypes.c_void_p, ctypes.c_int, CGPoint, ctypes.c_int]
cg.CGEventPost.argtypes = [ctypes.c_int, ctypes.c_void_p]
cg.CFRelease.argtypes = [ctypes.c_void_p]

kCGHIDEventTap = 0
kCGMouseButtonLeft = 0
kCGEventLeftMouseDown = 1
kCGEventLeftMouseUp = 2
kCGEventMouseMoved = 5
kCGEventLeftMouseDragged = 6


def _post(etype, x, y):
    ev = cg.CGEventCreateMouseEvent(
        None, etype, CGPoint(x, y), kCGMouseButtonLeft)
    if not ev:
        _fail("CGEventCreateMouseEvent returned NULL")
    cg.CGEventPost(kCGHIDEventTap, ev)
    cg.CFRelease(ev)


_post(kCGEventMouseMoved, x1, y1)
time.sleep(0.05)
_post(kCGEventLeftMouseDown, x1, y1)
time.sleep(0.15)
for i in range(1, steps + 1):
    _post(kCGEventLeftMouseDragged,
          x1 + (x2 - x1) * i / steps,
          y1 + (y2 - y1) * i / steps)
    time.sleep(0.01)
_post(kCGEventLeftMouseUp, x2, y2)
print("dragged (%d,%d) -> (%d,%d)" % (x1, y1, x2, y2))
"""


class MacHandle:
    """What MacSession.open() hands to every mac action.

    The run_* methods are the only way actions touch the OS. They never
    raise: a non-zero exit or a timeout comes back as (ok=False, output=error
    text), and the action turns that into a failed StepResult.
    """

    def run_script(self, script: str, timeout_s: float = DEFAULT_TIMEOUT_S,
                   ) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except FileNotFoundError:
            return False, "osascript not found — this domain runs on macOS only"
        except subprocess.TimeoutExpired:
            return False, f"AppleScript timed out after {timeout_s}s"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return False, f"osascript exited {proc.returncode}: {err}"
        return True, (proc.stdout or "").strip()

    def run_drag(self, x1: int, y1: int, x2: int, y2: int,
                 steps: int = 20, timeout_s: float = DEFAULT_TIMEOUT_S,
                 ) -> tuple[bool, str]:
        try:
            proc = subprocess.run(
                [sys.executable, "-c", _DRAG_PY,
                 str(x1), str(y1), str(x2), str(y2), str(steps)],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except FileNotFoundError:
            return False, "python interpreter not found for mac_drag"
        except subprocess.TimeoutExpired:
            return False, f"drag timed out after {timeout_s}s"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return False, f"drag exited {proc.returncode}: {err}"
        return True, (proc.stdout or "").strip()

    def run_screenshot(self, path: str,
                       timeout_s: float = DEFAULT_TIMEOUT_S,
                       ) -> tuple[bool, str]:
        """Capture all displays to path as PNG. Needs Screen Recording
        permission — the first run makes macOS show the consent dialog."""
        try:
            proc = subprocess.run(
                ["screencapture", "-x", "-t", "png", path],
                capture_output=True, text=True, timeout=timeout_s,
            )
        except FileNotFoundError:
            return False, "screencapture not found — this domain runs on macOS only"
        except subprocess.TimeoutExpired:
            return False, f"screencapture timed out after {timeout_s}s"
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            return False, f"screencapture exited {proc.returncode}: {err}"
        return True, path


class MacSession:
    """SessionAdapter for the mac domain — see stepper/engine/session.py.

    `open()` returns a MacHandle; `close()` is a no-op because there is no
    process, connection, or window this session owns.
    """

    domain = "mac"

    def __init__(self, cfg=None, settings=None, test_reporter=None, *, shared=None):
        # Accepted-and-ignored, like the noop domain's session factory: the
        # composition root passes these to every domain, and this one needs
        # none of them.
        self._handle = MacHandle()

    async def open(self) -> MacHandle:
        return self._handle

    async def close(self) -> None:
        return None


def mac_preflight(cfg=None, settings=None) -> list[str]:
    """Plan-time check: are we on macOS with osascript available?"""
    if platform.system() != "Darwin":
        return ["mac domain needs macOS (osascript); "
                f"this machine reports platform.system()={platform.system()!r}"]
    if shutil.which("osascript") is None:
        return ["osascript not found on PATH — reinstall macOS command line tools"]
    return []
