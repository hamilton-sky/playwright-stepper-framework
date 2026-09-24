"""
A local stand-in for phpTravels, for the `pt_*` workflows.

Why this exists
---------------
phpTravels shipped one workflow and four actions, and none of them had ever
run. This environment's egress policy denies the host, and there is no CI step
for the site, so "validate says the wiring is sound" was the whole of what was
known about it. The `ti` fixtures (stepper/sites/ti/fixtures/) exist for the
same reason and found two real bugs the moment they let the flows run.

Serving the same paths on loopback costs nothing: 127.0.0.1 is in the proxy's
noProxy list, so this touches no network.

    python stepper/sites/phptravels/fixtures/server.py --port 8098
    PHPTRAVELS_BASE_URL=http://127.0.0.1:8098 \
    PHPTRAVELS_EMAIL=user@phptravels.com PHPTRAVELS_PASSWORD=demouser \
        python stepper/main.py run hotel_booking

`PHPTRAVELS_BASE_URL` is the site's existing knob — no production code changes
to point the whole site here.

What it is and is not
---------------------
The markup is a reconstruction of what the POMs select on, not a capture: the
host is unreachable from here, so it could not be fetched. It reproduces the
structures that matter — the `.tt-menu` typeahead the search flow waits on, the
`#hotels` / `#flights` tabs that give two buttons both named "Search" (so the
role strategy is genuinely ambiguous and the cascade has to fall through to
CSS, exactly as on the real site), the `.col-md-12.hotel-listing` result cards
the results POM parses for name, price and stars, and a booking form that
answers with a confirmation the detail POM can read back.

A flow passing here proves the selector matches *this* markup and that the
engine path behind it works end to end. It does not prove the selector still
matches the live site. When the host becomes reachable, run the same workflow
with `PHPTRAVELS_BASE_URL` unset; any disagreement is a fixture that has
drifted, and the fixture is what should change.
"""
from __future__ import annotations

import argparse
import re
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

_HERE = Path(__file__).resolve().parent

#: phpTravels publishes these on its own demo; they gate nothing. Override with
#: PHPTRAVELS_EMAIL / PHPTRAVELS_PASSWORD, which is where a real one would go.
VALID_EMAIL = "user@phptravels.com"
VALID_PASSWORD = "demouser"

#: Enough rows that "the first hotel" is a real choice rather than the only one.
HOTELS = [
    {"slug": "dubai-grand", "name": "Dubai Grand Hotel", "price": "120", "stars": 5,
     "address": "Sheikh Zayed Road, Dubai",
     "description": "A tall building with a pool on the roof."},
    {"slug": "marina-suites", "name": "Marina Suites", "price": "95", "stars": 4,
     "address": "Dubai Marina, Dubai",
     "description": "Suites overlooking the marina."},
    {"slug": "desert-lodge", "name": "Desert Lodge", "price": "70", "stars": 3,
     "address": "Al Qudra, Dubai",
     "description": "Quiet, and a long way from anything."},
]

STAR = '<i class="fa fa-star"></i>'
AVATAR = (
    '<a class="dropdown-toggle" href="/account">'
    '<img class="rounded-circle" width="32" height="32" alt="avatar" '
    'src="data:image/gif;base64,R0lGODlhAQABAIAAAMLCwgAAACH5BAAAAAAALAAAAAABAAEAAAICRAEAOw=="></a>'
)
FLASH_ERROR = '<div class="alert alert-danger">These credentials do not match our records.</div>'


def _read(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def _hotel_cards() -> str:
    tpl = _read("hotel_card.html")
    return "".join(
        tpl.replace("{slug}", h["slug"]).replace("{name}", h["name"])
           .replace("{price}", h["price"]).replace("{stars}", STAR * h["stars"])
        for h in HOTELS
    )


def _find(slug: str) -> dict | None:
    return next((h for h in HOTELS if h["slug"] == slug), None)


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
        raw = SimpleCookie(self.headers.get("Cookie", ""))
        return "pt_session" in raw and raw["pt_session"].value == "1"

    def _avatar(self) -> str:
        """The signal is_logged_in() counts — only present once authenticated."""
        return AVATAR if self._logged_in() else ""

    def _form(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return parse_qs(self.rfile.read(length).decode())

    def log_message(self, fmt, *args):
        pass

    # ── routes ───────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)
        path, query = parsed.path, parse_qs(parsed.query)

        if path == "/":
            return self._send(_read("home.html").encode())

        if path == "/account/login":
            flash = FLASH_ERROR if "error" in query else ""
            return self._send(_read("login.html").replace("<!--FLASH-->", flash).encode())

        if path == "/account":
            if not self._logged_in():
                return self._redirect("/account/login")
            return self._send(_read("account.html").encode())

        if path == "/hotels":
            destination = (query.get("destination") or [""])[0]
            body = (_read("hotels.html")
                    .replace("<!--AVATAR-->", self._avatar())
                    .replace("<!--DESTINATION-->", destination or "anywhere")
                    .replace("<!--CARDS-->", _hotel_cards()))
            return self._send(body.encode())

        m = re.fullmatch(r"/hotels/([a-z0-9-]+)", path)
        if m:
            hotel = _find(m.group(1))
            if not hotel:
                return self._send(b"<h1>Not Found</h1>", status=404)
            body = _read("hotel_detail.html")
            for key, value in hotel.items():
                body = body.replace("{" + key + "}", STAR * value if key == "stars" else str(value))
            return self._send(body.replace("<!--AVATAR-->", self._avatar()).encode())

        return self._send(b"<h1>Not Found</h1>", status=404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/account/login":
            form = self._form()
            email = (form.get("username") or [""])[0]
            password = (form.get("password") or [""])[0]
            if email == VALID_EMAIL and password == VALID_PASSWORD:
                return self._redirect("/account", cookie="pt_session=1; Path=/")
            return self._redirect("/account/login?error=1")

        m = re.fullmatch(r"/hotels/([a-z0-9-]+)/book", path)
        if m:
            hotel = _find(m.group(1))
            if not hotel:
                return self._send(b"<h1>Not Found</h1>", status=404)
            form = self._form()
            body = (_read("booking_confirmed.html")
                    .replace("{name}", hotel["name"])
                    .replace("{ref}", f"PT-{hotel['slug'][:3].upper()}-40191")
                    .replace("{checkin}", (form.get("checkin") or [""])[0])
                    .replace("{checkout}", (form.get("checkout") or [""])[0])
                    .replace("{adults}", (form.get("adults") or [""])[0])
                    .replace("{children}", (form.get("children") or [""])[0])
                    .replace("<!--AVATAR-->", self._avatar()))
            return self._send(body.encode())

        return self._send(b"<h1>Not Found</h1>", status=404)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8098)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()

    # Threading, for the same reason ti's fixture server is: with HTTP/1.1
    # keep-alive a browser holds its connection open, and a single-threaded
    # server blocks every other request behind it.
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"phpTravels fixtures on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
