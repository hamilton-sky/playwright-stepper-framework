"""
brightsky/config.py — Where the BrightSky backend is, and the bridge token.

Half of the trust boundary to the backend (the HTTP client is the other half).
The token is sent only over https, or over http to a loopback host, so a
mistyped `http://` URL can never put it on the wire in clear. No message this
module raises contains the token, and `BrightSkyConfig`'s repr leaves it out.

`load_config` takes the environment as a mapping and does no I/O: the caller
loads `.env` first and passes `os.environ`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from urllib.parse import urlsplit

API_URL_VAR = "BRIGHTSKY_API_URL"
TOKEN_VAR = "BRIGHTSKY_BRIDGE_TOKEN"

#: Hosts plain http may go to. urlsplit lowercases the host and drops the
#: brackets around an IPv6 literal, so `http://[::1]:3001` gives "::1".
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_HTTPS_ONLY = (
    f"{API_URL_VAR} must be an https URL (http is allowed only for "
    "localhost, 127.0.0.1 and ::1): the bridge token is only sent over https"
)


class BrightSkyConfigError(Exception):
    """The BrightSky environment is missing or unsafe. Never carries the token."""


@dataclass(frozen=True)
class BrightSkyConfig:
    #: The backend's base URL, with no trailing "/".
    api_url: str
    #: The bridge token, sent as `Authorization: Bearer <token>`.
    token: str = field(repr=False)


def _required(environ: Mapping[str, str], name: str) -> str:
    value = (environ.get(name) or "").strip()
    if not value:
        raise BrightSkyConfigError(f"{name} is not set")
    return value


def _visible_ascii(value: str) -> bool:
    """True when every character is printable ASCII other than space (! to ~)."""
    return all("!" <= ch <= "~" for ch in value)


def load_config(environ: Mapping[str, str]) -> BrightSkyConfig:
    """Read and check the two BrightSky variables. Raises BrightSkyConfigError."""
    api_url = _required(environ, API_URL_VAR).rstrip("/")
    token = _required(environ, TOKEN_VAR)

    # A line break in the token would end up in an HTTP header, and the stdlib
    # transport echoes a bad header value, token and all, in its exception.
    if not _visible_ascii(token):
        raise BrightSkyConfigError(
            f"{TOKEN_VAR} may contain only visible ASCII characters")

    if not _visible_ascii(api_url):
        raise BrightSkyConfigError(f"{API_URL_VAR} is not a valid URL")
    try:
        parts = urlsplit(api_url)
        host = parts.hostname
        parts.port  # raises ValueError on a non-numeric or out-of-range port
    except ValueError:
        raise BrightSkyConfigError(f"{API_URL_VAR} is not a valid URL") from None
    scheme = parts.scheme.lower()

    if scheme not in ("http", "https"):
        raise BrightSkyConfigError(_HTTPS_ONLY)
    if not host:
        raise BrightSkyConfigError(f"{API_URL_VAR} has no host")
    # Request paths are appended to the base URL, so a query or fragment would
    # swallow them; userinfo would put a credential in the repr.
    if "?" in api_url or "#" in api_url or "@" in parts.netloc:
        raise BrightSkyConfigError(
            f"{API_URL_VAR} must not have a query, a fragment or a user name")
    if scheme == "http" and host not in LOOPBACK_HOSTS:
        raise BrightSkyConfigError(_HTTPS_ONLY)

    return BrightSkyConfig(api_url=api_url, token=token)
