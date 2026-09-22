import io

import pytest
from urllib.error import HTTPError, URLError

from casio_watch.config import load_config
from casio_watch.notify import (MAX_ACTIONS, NotifyError, RETRY_DELAYS,
                                format_actions, format_message, send)
from casio_watch.store import Deal

CFG = load_config({"NTFY_TOPIC": "secret-topic"})
COLLECTION_URL = "https://casiostore.bhawar.com/collections/watches"


def deal(handle, pct, price, compare_at):
    return Deal(handle=handle, title=handle.upper(),
                url=f"{COLLECTION_URL}/products/{handle}",
                price=price, compare_at=compare_at, pct=pct)


ONE = deal("gma-p2110sc-4a", 30, 6646.50, 9495.00)
TWO = deal("gm-2110d-3a", 30, 15396.50, 21995.00)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeSleep:
    def __init__(self):
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)


def test_single_deal_title_is_singular():
    title, _, _ = format_message([ONE], COLLECTION_URL)
    assert title == "1 new Casio deal"


def test_multiple_deals_title_is_plural():
    title, _, _ = format_message([ONE, TWO], COLLECTION_URL)
    assert title == "2 new Casio deals"


def test_body_lists_percent_price_and_was_price():
    _, body, _ = format_message([ONE], COLLECTION_URL)
    assert body == "GMA-P2110SC-4A — 30% off ₹6,646 (was ₹9,495)"


def test_body_lists_each_deal_on_its_own_line():
    _, body, _ = format_message([ONE, TWO], COLLECTION_URL)
    assert len(body.splitlines()) == 2


def test_deals_sorted_by_deepest_discount_first():
    shallow = deal("shallow", 12, 8800.0, 10000.0)
    _, body, _ = format_message([shallow, ONE], COLLECTION_URL)
    assert body.splitlines()[0].startswith("GMA-P2110SC-4A")


def test_body_truncates_beyond_max_listed():
    many = [deal(f"d{i}", 20 + i, 800.0, 1000.0) for i in range(14)]
    _, body, _ = format_message(many, COLLECTION_URL)
    lines = body.splitlines()
    assert len(lines) == 11
    assert lines[-1] == "+4 more"


def test_click_url_is_the_product_for_a_single_deal():
    _, _, click = format_message([ONE], COLLECTION_URL)
    assert click == ONE.url


def test_click_url_is_the_deepest_deal_for_multiple_deals():
    deepest = deal("deepest", 55, 450.0, 1000.0)
    _, _, click = format_message([ONE, TWO, deepest], COLLECTION_URL)
    assert click == deepest.url


def test_click_url_is_never_the_collection_page():
    _, _, click = format_message([ONE, TWO], COLLECTION_URL)
    assert click != COLLECTION_URL
    assert click in {ONE.url, TWO.url}


def test_single_deal_needs_no_action_buttons():
    assert format_actions([ONE]) is None


def test_each_deal_gets_an_action_button():
    actions = format_actions([ONE, TWO])
    assert actions.count("view,") == 2
    assert ONE.url in actions
    assert TWO.url in actions


def test_action_buttons_are_capped():
    many = [deal(f"d{i}", 20 + i, 800.0, 1000.0) for i in range(8)]
    assert format_actions(many).count("view,") == MAX_ACTIONS


def test_action_buttons_follow_deepest_discount_first():
    shallow = deal("shallow", 12, 8800.0, 10000.0)
    deepest = deal("deepest", 55, 450.0, 1000.0)
    actions = format_actions([shallow, deepest])
    assert actions.index(deepest.url) < actions.index(shallow.url)


def test_action_labels_strip_separators_that_would_corrupt_the_header():
    messy = Deal(handle="m", title="GA-2100, Black; Special", url=f"{COLLECTION_URL}/products/m",
                 price=700.0, compare_at=1000.0, pct=30)
    actions = format_actions([messy, ONE])
    # ntfy splits actions on ";" and their fields on ",", so a title carrying either
    # would silently produce a malformed button.
    assert f"view, GA-2100 Black Special, {messy.url}" in actions
    assert actions.count(";") == 1


def test_send_posts_to_topic_url_with_headers():
    opener = FakeOpener([FakeResponse(b"ok")])
    send(CFG, [ONE], opener=opener, sleep=FakeSleep())
    request = opener.requests[0]
    assert request.full_url == "https://ntfy.sh/secret-topic"
    assert request.get_method() == "POST"
    assert request.get_header("Title") == "1 new Casio deal"
    assert request.get_header("Priority") == "high"
    assert request.get_header("Tags") == "fire"
    assert request.get_header("Click") == ONE.url


def test_send_body_is_utf8_encoded():
    opener = FakeOpener([FakeResponse(b"ok")])
    send(CFG, [ONE], opener=opener, sleep=FakeSleep())
    assert "₹" in opener.requests[0].data.decode("utf-8")


def test_send_does_nothing_when_there_are_no_deals():
    opener = FakeOpener([])
    send(CFG, [], opener=opener, sleep=FakeSleep())
    assert opener.requests == []


def test_send_retries_then_succeeds():
    opener = FakeOpener([URLError("flaky"), FakeResponse(b"ok")])
    sleeper = FakeSleep()
    send(CFG, [ONE], opener=opener, sleep=sleeper)
    assert len(opener.requests) == 2
    assert sleeper.calls == [RETRY_DELAYS[0]]


def test_send_raises_after_all_retries_exhausted():
    opener = FakeOpener([URLError("down")] * 3)
    sleeper = FakeSleep()
    with pytest.raises(NotifyError, match="3 attempt"):
        send(CFG, [ONE], opener=opener, sleep=sleeper)
    assert len(opener.requests) == 3
    assert sleeper.calls == [RETRY_DELAYS[0], RETRY_DELAYS[1]]


def test_send_retries_on_http_error():
    opener = FakeOpener([HTTPError("u", 500, "err", {}, None), FakeResponse(b"ok")])
    send(CFG, [ONE], opener=opener, sleep=FakeSleep())
    assert len(opener.requests) == 2


def test_send_never_logs_the_topic(caplog):
    opener = FakeOpener([URLError("down")] * 3)
    with pytest.raises(NotifyError):
        send(CFG, [ONE], opener=opener, sleep=FakeSleep())
    assert "secret-topic" not in caplog.text
