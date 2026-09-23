"""
A local stand-in for the-internet.herokuapp.com, for the `ti` workflows.

Why this exists
---------------
`ti` was generated from a crawl of the-internet.herokuapp.com, and eight
workflows were written against it. Six of them had never been run: this
environment's egress policy denies that host, so there was nothing to run them
against and "the wiring is valid" was all `validate` could say. The checkboxes
flow, the one that *was* run, is where the `role=checkbox name="checkbox 1"`
bug turned up — 0 matches, because the-internet's label text is a sibling text
node rather than a <label>. Structural correctness and behavioural correctness
are different things, and only running finds the gap.

So: serve the same paths on loopback. 127.0.0.1 is in the proxy's noProxy list,
so nothing here touches the network.

    python stepper/sites/ti/fixtures/server.py --port 8099
    TI_BASE_URL=http://127.0.0.1:8099 python stepper/main.py run <workflow>

What it is and is not
---------------------
The markup is a reconstruction of the-internet's pages, not a capture — the
host is unreachable from here, so it could not be fetched. It reproduces the
structures the POMs actually select on: element ids, the login form's
action/labels, the hover CSS that hides .figcaption until :hover, HTML5
drag-and-drop that swaps the two columns, target=_blank, and the three native
dialogs. Two fixtures deliberately differ from the real site and say so at the
point they differ: avatars are inline data: URIs rather than /img/*.jpg, and
the session is a plain cookie rather than Rack's signed one.

A flow passing here proves the selector matches *this* markup and that the
engine path behind it works end to end. It does not prove the selector still
matches the live site. That distinction is the whole reason this docstring is
longer than the code.
"""
from __future__ import annotations

import argparse
import re
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_HERE = Path(__file__).resolve().parent

#: the-internet publishes these on its own login page; they gate nothing.
VALID_USER = "tomsmith"
VALID_PASS = "SuperSecretPassword!"

#: path → fixture file, for everything that is a plain page.
STATIC = {
    "/checkboxes":        "checkboxes.html",
    "/dropdown":          "dropdown.html",
    "/drag_and_drop":     "drag_and_drop.html",
    "/hovers":            "hovers.html",
    "/javascript_alerts": "javascript_alerts.html",
    "/windows":           "windows.html",
    "/windows/new":       "windows_new.html",
}

FLASH = ('<div class="flash {kind}" id="flash">\n  {message}\n</div>')


def _render(name: str, flash: str = "") -> bytes:
    """The fixture file with its <!--FLASH--> marker filled in, or removed."""
    return (_HERE / name).read_text(encoding="utf-8").replace("<!--FLASH-->", flash).encode()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _send(self, body: bytes, status: int = 200, headers: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, to: str, cookie: str | None = None):
        headers = {"Location": to}
        if cookie:
            headers["Set-Cookie"] = cookie
        self._send(b"", status=302, headers=headers)

    def _logged_in(self) -> bool:
        # A plain cookie where the real site uses a signed Rack session. The
        # POMs never read it; it exists so /secure can 302 the way the real
        # one does rather than being reachable by typing the URL.
        raw = self.headers.get("Cookie", "")
        return SimpleCookie(raw).get("ti_session", None) is not None and \
            SimpleCookie(raw)["ti_session"].value == "1"

    def log_message(self, fmt, *args):      # quiet; the stepper's log is the record
        pass

    # ── routes ───────────────────────────────────────────────────────────────

    def do_GET(self):
        path = urlparse(self.path).path

        if path in STATIC:
            return self._send(_render(STATIC[path]))

        if path == "/login":
            flash = ""
            if urlparse(self.path).query and "error" in parse_qs(urlparse(self.path).query):
                flash = FLASH.format(kind="error",
                                     message="Your username is invalid!")
            elif urlparse(self.path).query and "out" in parse_qs(urlparse(self.path).query):
                flash = FLASH.format(kind="success",
                                     message="You logged out of the secure area!")
            return self._send(_render("login.html", flash))

        if path == "/secure":
            if not self._logged_in():
                return self._redirect("/login?error=1")
            return self._send(_render(
                "secure.html",
                FLASH.format(kind="success", message="You logged into a secure area!"),
            ))

        if path == "/logout":
            return self._redirect("/login?out=1", cookie="ti_session=; Max-Age=0; Path=/")

        if re.fullmatch(r"/users/\d+", path):
            # 404 on the real site too — "View profile" leads nowhere, which is
            # what makes the hover flow's click observable at all.
            return self._send(_render("users_1.html"), status=404)

        return self._send(b"<h1>Not Found</h1>", status=404)

    def do_POST(self):
        if urlparse(self.path).path != "/authenticate":
            return self._send(b"<h1>Not Found</h1>", status=404)

        length = int(self.headers.get("Content-Length", 0))
        form = parse_qs(self.rfile.read(length).decode())
        user = (form.get("username") or [""])[0]
        password = (form.get("password") or [""])[0]

        if user == VALID_USER and password == VALID_PASS:
            return self._redirect("/secure", cookie="ti_session=1; Path=/")
        return self._redirect("/login?error=1")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8099)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    # Threading, not the plain HTTPServer. With HTTP/1.1 keep-alive a browser
    # holds its connection open, and a single-threaded server then blocks every
    # other request behind it — including the second page ti_open_new_window
    # opens, whose goto() simply timed out. It happened to work while each flow
    # used one page at a time, which is the kind of luck a fixture should not
    # depend on.
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"the-internet fixtures on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
