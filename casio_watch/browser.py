"""A urlopen-compatible opener that fetches with a real browser's TLS fingerprint.

Shopify's edge judges clients by their TLS/HTTP handshake. From a datacenter IP it
answers Python's urllib - and current curl builds - with 429 on the very first
request, regardless of headers or request rate, while a Chrome handshake passes.
curl_cffi reproduces that handshake. Only the store is fetched this way; ntfy is
happy with urllib.
"""

from __future__ import annotations

from urllib.error import HTTPError, URLError

from curl_cffi import requests as curl_requests
from curl_cffi.requests.errors import RequestsError

IMPERSONATE = "chrome"


class _Response:
    """The slice of urlopen's response that fetch_page uses."""

    def __init__(self, body: bytes, headers):
        self._body = body
        self.headers = headers

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def browser_open(request, timeout=None, get=curl_requests.get) -> _Response:
    """Perform a urllib Request as Chrome would, raising urllib's errors."""
    # The impersonated profile supplies a matching Chrome User-Agent; a bot
    # User-Agent on top of a Chrome handshake is a mismatch the edge can flag.
    headers = {name: value for name, value in request.header_items()
               if name.lower() != "user-agent"}
    try:
        response = get(request.full_url, headers=headers, timeout=timeout,
                       impersonate=IMPERSONATE)
    except RequestsError as exc:
        raise URLError(str(exc)) from exc

    if response.status_code >= 300:
        raise HTTPError(request.full_url, response.status_code, response.reason or "",
                        response.headers, None)
    return _Response(response.content, response.headers)
