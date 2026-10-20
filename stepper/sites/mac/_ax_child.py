"""
sites/mac/_ax_child.py — Accessibility lookups for the mac domain, run as a child.

MacHandle.run_ax() runs this file under the workflow's interpreter, the same
way mac_click and mac_drag run their CoreGraphics child: stdlib ctypes only,
no pyobjc. It talks to the Accessibility API directly (AXUIElement), which is
much faster than System Events walking `entire contents` one Apple Event per
attribute, and it is what lets a step aim at a window or an element instead of
at screen coordinates that go stale as soon as a window moves.

Modes (one JSON object on stdout, exit 0 even when nothing is found):

    front                         the frontmost app and its focused window
    frame [--app NAME] [--raise]  that app's front window: x, y, w, h, title
    find  [--app NAME] [--raise] --text T [--match exact|contains] [--role R]
          [--wait S]              the first element whose title, description or
                                  value matches T: its centre and frame

The pure parts (matching, choosing the best candidate) are importable without
touching the OS, so the unit suite can test them on any platform.
"""

from __future__ import annotations

import json
import sys
import time
from collections import deque

MAX_NODES = 20000


# ── Pure helpers (no OS access) ──────────────────────────────────────────────

def normalise(text) -> str:
    return " ".join(str(text or "").split()).casefold()


def label_matches(labels, text: str, match: str = "exact") -> bool:
    want = normalise(text)
    if not want:
        return False
    for label in labels:
        got = normalise(label)
        if not got:
            continue
        if got == want or (match == "contains" and want in got):
            return True
    return False


def pick(candidates: list, text: str, match: str = "exact", role: str | None = None):
    """Best candidate: an exact label beats a contained one; on-screen size wins ties."""
    best, best_rank = None, None
    for c in candidates:
        if role and c.get("role") != role:
            continue
        if c.get("w", 0) <= 0 or c.get("h", 0) <= 0:
            continue
        labels = c.get("labels", [])
        if label_matches(labels, text, "exact"):
            rank = 0
        elif match == "contains" and label_matches(labels, text, "contains"):
            rank = 1
        else:
            continue
        if best_rank is None or rank < best_rank:
            best, best_rank = c, rank
            if rank == 0:
                break
    return best


def parse_args(argv: list) -> dict:
    if not argv or argv[0] not in ("front", "frame", "find"):
        raise ValueError("usage: front | frame [--app NAME] [--raise] | "
                         "find [--app NAME] [--raise] --text T [--match M] [--role R] [--wait S]")
    opts = {"mode": argv[0], "app": None, "raise": False, "text": None,
            "match": "exact", "role": None, "wait": 0.0}
    i = 1
    while i < len(argv):
        flag = argv[i]
        if flag == "--raise":
            opts["raise"] = True
            i += 1
            continue
        if flag not in ("--app", "--text", "--match", "--role", "--wait") or i + 1 >= len(argv):
            raise ValueError(f"bad argument {flag!r}")
        value = argv[i + 1]
        key = flag[2:]
        opts[key] = float(value) if key == "wait" else value
        i += 2
    if opts["mode"] == "find" and not opts["text"]:
        raise ValueError("find needs --text")
    if opts["match"] not in ("exact", "contains"):
        raise ValueError("--match must be exact or contains")
    return opts


# ── The OS side ──────────────────────────────────────────────────────────────

def _bind():
    import ctypes

    ax = ctypes.CDLL("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    ref = ctypes.c_void_p

    cf.CFStringCreateWithCString.restype = ref
    cf.CFStringCreateWithCString.argtypes = [ref, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFStringGetLength.restype = ctypes.c_long
    cf.CFStringGetLength.argtypes = [ref]
    cf.CFStringGetCString.restype = ctypes.c_bool
    cf.CFStringGetCString.argtypes = [ref, ctypes.c_char_p, ctypes.c_long, ctypes.c_uint32]
    cf.CFGetTypeID.restype = ctypes.c_ulong
    cf.CFGetTypeID.argtypes = [ref]
    cf.CFStringGetTypeID.restype = ctypes.c_ulong
    cf.CFArrayGetTypeID.restype = ctypes.c_ulong
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ref]
    cf.CFArrayGetValueAtIndex.restype = ref
    cf.CFArrayGetValueAtIndex.argtypes = [ref, ctypes.c_long]

    ax.AXIsProcessTrusted.restype = ctypes.c_bool
    ax.AXUIElementCreateApplication.restype = ref
    ax.AXUIElementCreateApplication.argtypes = [ctypes.c_int]
    ax.AXUIElementCreateSystemWide.restype = ref
    ax.AXUIElementCopyAttributeValue.restype = ctypes.c_int
    ax.AXUIElementCopyAttributeValue.argtypes = [ref, ref, ctypes.POINTER(ref)]
    ax.AXUIElementSetAttributeValue.restype = ctypes.c_int
    ax.AXUIElementSetAttributeValue.argtypes = [ref, ref, ref]
    ax.AXUIElementPerformAction.restype = ctypes.c_int
    ax.AXUIElementPerformAction.argtypes = [ref, ref]
    ax.AXUIElementGetPid.restype = ctypes.c_int
    ax.AXUIElementGetPid.argtypes = [ref, ctypes.POINTER(ctypes.c_int)]
    ax.AXValueGetValue.restype = ctypes.c_bool
    ax.AXValueGetValue.argtypes = [ref, ctypes.c_int, ref]
    true = ref.in_dll(cf, "kCFBooleanTrue")
    return ctypes, ax, cf, true


class _AX:
    UTF8 = 0x08000100

    def __init__(self):
        self.ctypes, self.ax, self.cf, self.true = _bind()
        self._strings = {}

    def s(self, text: str):
        if text not in self._strings:
            self._strings[text] = self.cf.CFStringCreateWithCString(None, text.encode(), self.UTF8)
        return self._strings[text]

    def text(self, value):
        if not value or self.cf.CFGetTypeID(value) != self.cf.CFStringGetTypeID():
            return None
        size = self.cf.CFStringGetLength(value) * 4 + 1
        buf = self.ctypes.create_string_buffer(size)
        if self.cf.CFStringGetCString(value, buf, size, self.UTF8):
            return buf.value.decode("utf-8", "replace")
        return None

    def get(self, elem, attr):
        out = self.ctypes.c_void_p()
        if self.ax.AXUIElementCopyAttributeValue(elem, self.s(attr), self.ctypes.byref(out)) != 0:
            return None
        return out.value

    def children(self, elem):
        arr = self.get(elem, "AXChildren")
        if not arr or self.cf.CFGetTypeID(arr) != self.cf.CFArrayGetTypeID():
            return []
        return [self.cf.CFArrayGetValueAtIndex(arr, i) for i in range(self.cf.CFArrayGetCount(arr))]

    def point(self, elem, attr, kind):
        value = self.get(elem, attr)
        if not value:
            return None
        pair = (self.ctypes.c_double * 2)()
        if not self.ax.AXValueGetValue(value, kind, self.ctypes.cast(pair, self.ctypes.c_void_p)):
            return None
        return float(pair[0]), float(pair[1])

    def frame(self, elem):
        pos = self.point(elem, "AXPosition", 1)   # kAXValueCGPointType
        size = self.point(elem, "AXSize", 2)      # kAXValueCGSizeType
        if not pos or not size:
            return None
        return {"x": pos[0], "y": pos[1], "w": size[0], "h": size[1]}

    def front_app(self):
        app = self.get(self.ax.AXUIElementCreateSystemWide(), "AXFocusedApplication")
        if app:
            return app
        # The system-wide element cannot always answer (Electron apps in front);
        # Launch Services always knows which app is frontmost.
        import re
        import subprocess
        asn = subprocess.run(["/usr/bin/lsappinfo", "front"], capture_output=True, text=True).stdout.strip()
        info = subprocess.run(["/usr/bin/lsappinfo", "info", "-only", "pid", asn],
                              capture_output=True, text=True).stdout
        m = re.search(r"pid\"?\s*=\s*(\d+)", info)
        return self.ax.AXUIElementCreateApplication(int(m.group(1))) if m else None

    def app(self, name):
        if not name:
            return self.front_app()
        import subprocess
        proc = subprocess.run(["/usr/bin/pgrep", "-x", name], capture_output=True, text=True)
        pids = [int(p) for p in proc.stdout.split()]
        return self.ax.AXUIElementCreateApplication(pids[0]) if pids else None

    def window(self, app):
        for attr in ("AXFocusedWindow", "AXMainWindow"):
            win = self.get(app, attr)
            if win:
                return win
        wins = self.children(app)
        for w in wins:
            if self.text(self.get(w, "AXRole")) == "AXWindow":
                return w
        return None

    def raise_(self, app, win):
        self.ax.AXUIElementSetAttributeValue(app, self.s("AXFrontmost"), self.true)
        if win:
            self.ax.AXUIElementPerformAction(win, self.s("AXRaise"))

    def enable_web_tree(self, app):
        """Ask the app to build its web accessibility tree; returns an undo callable.

        Chrome builds the tree for a page only once an assistive client asks:
        AXEnhancedUserInterface does it for Chrome (the first time takes a few
        seconds), AXManualAccessibility for Electron apps. Both report an error
        code even when they work, so success is judged by the tree appearing.
        The previous AXEnhancedUserInterface value is restored afterwards,
        because leaving it on makes some apps animate and resize differently.
        """
        before = self.get(app, "AXEnhancedUserInterface")
        was_on = before == self.true.value
        self.ax.AXUIElementSetAttributeValue(app, self.s("AXManualAccessibility"), self.true)
        self.ax.AXUIElementSetAttributeValue(app, self.s("AXEnhancedUserInterface"), self.true)
        false = self.ctypes.c_void_p.in_dll(self.cf, "kCFBooleanFalse")

        def undo():
            if not was_on:
                self.ax.AXUIElementSetAttributeValue(app, self.s("AXEnhancedUserInterface"), false)
        return undo

    def candidates(self, root):
        out, queue, seen = [], deque([root]), 0
        while queue and seen < MAX_NODES:
            elem = queue.popleft()
            seen += 1
            labels = [self.text(self.get(elem, a)) for a in ("AXTitle", "AXDescription", "AXValue")]
            labels = [l for l in labels if l]
            if labels:
                fr = self.frame(elem)
                if fr:
                    out.append({"role": self.text(self.get(elem, "AXRole")), "labels": labels, **fr})
            queue.extend(self.children(elem))
        return out


def main(argv) -> int:
    try:
        opts = parse_args(argv)
    except ValueError as exc:
        sys.stderr.write(f"ax: {exc}\n")
        return 4
    try:
        a = _AX()
    except OSError as exc:
        print(json.dumps({"ok": False, "error": f"Accessibility API unavailable (macOS only): {exc}"}))
        return 0
    if not a.ax.AXIsProcessTrusted():
        print(json.dumps({"ok": False, "error": "Accessibility permission not granted to this Python "
                          "(System Settings > Privacy & Security > Accessibility)"}))
        return 0

    app = a.app(opts["app"])
    if not app:
        print(json.dumps({"ok": False, "error": f"no running app named {opts['app']!r}"
                          if opts["app"] else "no frontmost app"}))
        return 0
    app_name = a.text(a.get(app, "AXTitle"))

    if opts["mode"] == "front":
        win = a.window(app)
        title = a.text(a.get(win, "AXTitle")) if win else None
        print(json.dumps({"ok": True, "app": app_name, "window_title": title}))
        return 0

    win = a.window(app)
    if opts["raise"]:
        a.raise_(app, win)
        time.sleep(0.2)
        win = a.window(app) or win
    if not win:
        print(json.dumps({"ok": False, "error": f"{app_name or opts['app']} has no window"}))
        return 0
    wframe = a.frame(win)
    title = a.text(a.get(win, "AXTitle"))

    if opts["mode"] == "frame":
        if not wframe:
            print(json.dumps({"ok": False, "error": "could not read the window's position"}))
            return 0
        print(json.dumps({"ok": True, "app": app_name, "window_title": title, **wframe}))
        return 0

    hit = pick(a.candidates(win), opts["text"], opts["match"], opts["role"])
    if not hit:
        undo = a.enable_web_tree(app)
        try:
            deadline = time.monotonic() + max(0.0, opts["wait"])
            while not hit and time.monotonic() < deadline:
                time.sleep(0.5)
                hit = pick(a.candidates(a.window(app) or win), opts["text"], opts["match"], opts["role"])
        finally:
            undo()
    if not hit:
        print(json.dumps({"ok": False, "error": f"no element labelled {opts['text']!r} in "
                          f"{app_name}'s window {title!r}"}))
        return 0
    cx, cy = hit["x"] + hit["w"] / 2, hit["y"] + hit["h"] / 2
    visible = bool(wframe) and (wframe["x"] <= cx <= wframe["x"] + wframe["w"]
                                and wframe["y"] <= cy <= wframe["y"] + wframe["h"])
    print(json.dumps({"ok": True, "app": app_name, "window_title": title, "role": hit["role"],
                      "label": hit["labels"][0], "cx": round(cx), "cy": round(cy),
                      "visible": visible, "frame": {k: hit[k] for k in ("x", "y", "w", "h")}}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
