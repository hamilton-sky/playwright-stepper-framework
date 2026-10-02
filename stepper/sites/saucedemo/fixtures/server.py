"""
A local stand-in for SauceDemo, for the `sd_*` workflows.

Why this exists
---------------
www.saucedemo.com is denied by this environment's egress policy, so of the
five SauceDemo workflows only the smoke test ever ran — in CI, against the live
host — and the hover-before-click rule applied to this site's collection
clicks had never once been exercised by a browser. The `ti` and `phptravels`
fixtures exist for the same reason, and each found real bugs the moment its
flows could run.

    python stepper/sites/saucedemo/fixtures/server.py --port 8097
    SAUCEDEMO_BASE_URL=http://127.0.0.1:8097 \\
        python stepper/main.py run sd_happy_path \\
        --vars '{"base_url": "http://127.0.0.1:8097"}'

Two knobs, because two layers address the site. `SAUCEDEMO_BASE_URL` points
the glue's POMs here; `base_url` is the workflow variable the engine-level
steps (`navigate`, `measure_performance`) interpolate. Set one without the
other and a flow starts on one host and finishes on the other.

What it is and is not
---------------------
The real site is a static single-page app — the session is a cookie, the cart
lives in localStorage — so a static server is a faithful model of its
transport. The markup is a reconstruction of what the POMs select on, not a
capture: the class names and `data-test` attributes, the cart link that is an
`<a>` with no href (so it has no link role and the cascade falls through to
CSS, as it does on the real site), the burger menu that is in the DOM but
hidden until opened, the 8% tax, and the cart emptied on Finish.

A flow passing here proves the selector matches *this* markup and that the
engine path behind it works end to end. It does not prove the selector still
matches the live site. CI still runs the smoke test against the live host;
any disagreement between the two is a fixture that has drifted.
"""
from __future__ import annotations

import argparse
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: Only these are served — the Python files and README next to them are not.
_SERVED = {".html", ".js", ".css"}


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self.path = "/index.html" + self.path[1:]
        elif Path(path).suffix not in _SERVED:
            self.send_error(404)
            return
        super().do_GET()

    def end_headers(self):
        # A fixture edited between runs must not be answered from cache.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8097)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    handler = functools.partial(Handler, directory=str(_HERE))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"SauceDemo fixtures on http://{args.host}:{args.port}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
