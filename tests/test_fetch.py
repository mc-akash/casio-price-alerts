import io
import json
from urllib.error import HTTPError, URLError

import pytest

from casio_watch.config import load_config
from casio_watch.store import FetchError, fetch_all, fetch_page

CFG = load_config({"NTFY_TOPIC": "t", "MIN_DISCOUNT_PCT": "10"})

DISCOUNTED = {
    "id": 1, "title": "GMA-P2110SC-4A", "handle": "gma-p2110sc-4a",
    "variants": [{"available": True, "price": "6646.50", "compare_at_price": "9495.00"}],
}
FULL_PRICE = {
    "id": 2, "title": "GA-2100RL-1A", "handle": "ga-2100rl-1a",
    "variants": [{"available": True, "price": "9195.00", "compare_at_price": "9195.00"}],
}


class FakeResponse(io.BytesIO):
    def __init__(self, payload, etag=None):
        super().__init__(json.dumps(payload).encode())
        self._etag = etag

    @property
    def headers(self):
        return {"ETag": self._etag} if self._etag else {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    """Records requests and replays a scripted list of responses."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def http_error(code):
    return HTTPError("url", code, "msg", {}, None)


def test_fetch_page_returns_body_and_etag():
    opener = FakeOpener([FakeResponse({"products": [DISCOUNTED]}, etag='W/"abc"')])
    result = fetch_page(CFG, 1, None, opener)
    assert result.not_modified is False
    assert result.etag == 'W/"abc"'
    assert result.body["products"][0]["handle"] == "gma-p2110sc-4a"


def test_fetch_page_sends_if_none_match_when_etag_known():
    opener = FakeOpener([http_error(304)])
    result = fetch_page(CFG, 1, 'W/"abc"', opener)
    assert result.not_modified is True
    assert result.body is None
    assert opener.requests[0].get_header("If-none-match") == 'W/"abc"'


def test_fetch_page_omits_if_none_match_without_etag():
    opener = FakeOpener([FakeResponse({"products": []})])
    fetch_page(CFG, 1, None, opener)
    assert opener.requests[0].get_header("If-none-match") is None


def test_fetch_page_sends_user_agent():
    opener = FakeOpener([FakeResponse({"products": []})])
    fetch_page(CFG, 1, None, opener)
    assert "casio-price-alerts" in opener.requests[0].get_header("User-agent")


def test_fetch_page_raises_fetch_error_on_server_error():
    opener = FakeOpener([http_error(503)])
    with pytest.raises(FetchError, match="503"):
        fetch_page(CFG, 1, None, opener)


def test_fetch_page_raises_fetch_error_on_network_failure():
    opener = FakeOpener([URLError("dns boom")])
    with pytest.raises(FetchError, match="dns boom"):
        fetch_page(CFG, 1, None, opener)


def test_fetch_page_raises_fetch_error_on_invalid_json():
    class Garbage(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    opener = FakeOpener([Garbage(b"<html>nope</html>")])
    with pytest.raises(FetchError, match="JSON"):
        fetch_page(CFG, 1, None, opener)


def test_fetch_all_first_run_crawls_until_empty_page():
    opener = FakeOpener([
        FakeResponse({"products": [DISCOUNTED, FULL_PRICE]}, etag='W/"p1"'),
        FakeResponse({"products": []}, etag='W/"p2"'),
    ])
    result = fetch_all(CFG, {}, opener)
    assert [d.handle for d in result.deals] == ["gma-p2110sc-4a"]
    assert result.etags == {"1": 'W/"p1"'}


def test_fetch_all_skips_cycle_when_all_pages_unchanged():
    opener = FakeOpener([http_error(304)])
    result = fetch_all(CFG, {"1": 'W/"p1"'}, opener)
    assert result.deals is None
    assert result.etags == {"1": 'W/"p1"'}
    assert len(opener.requests) == 1


def test_fetch_all_refetches_everything_when_a_page_changed():
    opener = FakeOpener([
        FakeResponse({"products": [DISCOUNTED]}, etag='W/"new"'),
        FakeResponse({"products": [DISCOUNTED]}, etag='W/"new"'),
        FakeResponse({"products": []}, etag='W/"p2"'),
    ])
    result = fetch_all(CFG, {"1": 'W/"old"'}, opener)
    assert [d.handle for d in result.deals] == ["gma-p2110sc-4a"]
    assert result.etags == {"1": 'W/"new"'}


def test_fetch_all_force_full_skips_the_probe():
    opener = FakeOpener([
        FakeResponse({"products": [DISCOUNTED]}, etag='W/"p1"'),
        FakeResponse({"products": []}),
    ])
    result = fetch_all(CFG, {"1": 'W/"p1"'}, opener, force_full=True)
    assert result.deals is not None
    assert len(opener.requests) == 2


def test_fetch_all_propagates_fetch_error():
    opener = FakeOpener([URLError("offline")])
    with pytest.raises(FetchError):
        fetch_all(CFG, {}, opener)


def test_fetch_all_stops_at_max_pages():
    opener = FakeOpener([FakeResponse({"products": [DISCOUNTED]}) for _ in range(25)])
    result = fetch_all(CFG, {}, opener)
    assert len(opener.requests) == 20
    assert result.deals is not None
