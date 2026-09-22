"""
`navigate` deciding whether a URL is already absolute.

The test used to be `url.startswith("http")`, which reads as "is this absolute?"
and is not. It got two cases wrong in opposite directions:

    file:///tmp/page.html  →  https://file///tmp/page.html   (a scheme it broke)
    httpbin.org            →  left alone, then fails to load (a host it trusted)

The first is what M6 found: a mixed web+db workflow wants a checked-in fixture
page over file://, so it needs no network, no port and no server process. The
second was always broken and nobody had a hostname starting with "http".

Matching a URL scheme asks the question that was meant. Bare hostnames and bare
paths still get https:// prepended, exactly as before — that convenience is the
reason the check exists and no workflow should notice this change.
"""
from __future__ import annotations

import pytest

from stepper.engine.actions.basic import _HAS_SCHEME


@pytest.mark.parametrize("url", [
    "https://www.saucedemo.com",
    "http://localhost:8000/page",
    "file:///tmp/page.html",
    "about:blank",
    "data:text/html,<h1>hi</h1>",
])
def test_a_url_naming_its_scheme_is_left_alone(url):
    assert _HAS_SCHEME.match(url), f"{url} already says what it is"


@pytest.mark.parametrize("url", [
    "www.saucedemo.com",
    "openlibrary.org/search",
    "/inventory.html",
    "httpbin.org",
])
def test_a_url_without_a_scheme_still_gets_one(url):
    assert not _HAS_SCHEME.match(url)


def test_the_hostname_that_starts_with_http_is_the_point():
    """
    The old prefix test passed `httpbin.org` straight to page.goto, which fails
    with no scheme. It is the case that shows the check was asking the wrong
    question rather than merely being incomplete.
    """
    assert not _HAS_SCHEME.match("httpbin.org")
    assert _HAS_SCHEME.match("http://httpbin.org")
