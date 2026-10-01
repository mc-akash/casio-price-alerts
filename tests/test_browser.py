import urllib.request
from urllib.error import HTTPError, URLError

import pytest
from curl_cffi.requests.errors import RequestsError

from casio_watch.browser import IMPERSONATE, browser_open

URL = "https://casiostore.bhawar.com/products.json?limit=250&page=1"


class FakeCurlResponse:
    def __init__(self, status_code=200, content=b"{}", headers=None, reason="OK"):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.reason = reason


class FakeGet:
    """Stands in for curl_cffi.requests.get, recording each call."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def request(**headers):
    req = urllib.request.Request(URL)
    for name, value in headers.items():
        req.add_header(name, value)
    return req


def test_success_reads_like_urlopen():
    get = FakeGet(FakeCurlResponse(content=b'{"products": []}', headers={"ETag": 'W/"p1"'}))
    with browser_open(request(), timeout=20, get=get) as response:
        assert response.read() == b'{"products": []}'
        assert response.headers.get("ETag") == 'W/"p1"'


def test_impersonates_a_browser_and_passes_the_timeout():
    get = FakeGet(FakeCurlResponse())
    browser_open(request(), timeout=20, get=get)
    url, kwargs = get.calls[0]
    assert url == URL
    assert kwargs["impersonate"] == IMPERSONATE
    assert kwargs["timeout"] == 20


def test_forwards_request_headers_except_user_agent():
    """A bot User-Agent on top of a Chrome handshake is a mismatch the edge can flag."""
    get = FakeGet(FakeCurlResponse())
    browser_open(request(**{"Accept": "application/json", "If-None-Match": 'W/"p1"',
                            "User-Agent": "casio-price-alerts/1.0"}), get=get)
    sent = {k.lower(): v for k, v in get.calls[0][1]["headers"].items()}
    assert sent["accept"] == "application/json"
    assert sent["if-none-match"] == 'W/"p1"'
    assert "user-agent" not in sent


def test_not_modified_raises_http_error_like_urlopen():
    get = FakeGet(FakeCurlResponse(status_code=304, content=b"", reason="Not Modified"))
    with pytest.raises(HTTPError) as caught:
        browser_open(request(), get=get)
    assert caught.value.code == 304


def test_rate_limit_keeps_retry_after_header():
    get = FakeGet(FakeCurlResponse(status_code=429, headers={"Retry-After": "120"},
                                   reason="Too Many Requests"))
    with pytest.raises(HTTPError) as caught:
        browser_open(request(), get=get)
    assert caught.value.code == 429
    assert caught.value.headers.get("Retry-After") == "120"


def test_transport_failure_raises_url_error():
    get = FakeGet(RequestsError("Could not resolve host"))
    with pytest.raises(URLError, match="Could not resolve host"):
        browser_open(request(), get=get)
