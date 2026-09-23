import io

import pytest
from urllib.error import HTTPError, URLError

from casio_watch.alerts import Alert
from casio_watch.config import load_config
from casio_watch.notify import (MAX_ACTIONS, NotifyError, RETRY_DELAYS,
                                format_actions, format_group, ping, send)
from casio_watch.store import Product

CFG = load_config({"NTFY_TOPIC": "secret-topic"})


def alert(kind, handle, title, detail="detail"):
    p = Product(handle=handle, title=title,
                url=f"https://casiostore.bhawar.com/products/{handle}",
                price=1000.0, compare_at=None, available=True,
                product_type="Watches", tags=())
    return Alert(kind, p, detail)


DEAL = alert("discount", "gma-p2110sc-4a", "GMA-P2110SC-4A", "30% off ₹6,646 (was ₹9,495)")
DEAL2 = alert("discount", "gm-2110d-3a", "GM-2110D-3A", "30% off ₹15,396")
RESTOCK = alert("restock", "f-91w", "F-91W-1", "back in stock at ₹1,295")


class FakeResponse(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *exc): self.close(); return False


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class FakeSleep:
    def __init__(self): self.calls = []
    def __call__(self, s): self.calls.append(s)


# --- formatting -------------------------------------------------------------

def test_single_alert_title_names_the_product():
    title, _, _ = format_group("discount", [DEAL])
    assert title == "New deal: GMA-P2110SC-4A"


def test_multiple_alerts_title_counts_them():
    title, _, _ = format_group("discount", [DEAL, DEAL2])
    assert title == "2 new Casio deals"


def test_restock_title_uses_its_own_wording():
    assert format_group("restock", [RESTOCK])[0] == "Back in stock: F-91W-1"


def test_body_lists_product_and_detail():
    _, body, _ = format_group("discount", [DEAL])
    assert body == "GMA-P2110SC-4A - 30% off ₹6,646 (was ₹9,495)"


def test_body_truncates_beyond_max_listed():
    many = [alert("discount", f"h{i}", f"W{i}") for i in range(14)]
    lines = format_group("discount", many)[1].splitlines()
    assert len(lines) == 11
    assert lines[-1] == "+4 more"


def test_click_is_a_product_page_never_a_collection():
    _, _, click = format_group("discount", [DEAL, DEAL2])
    assert click == DEAL.product.url
    assert "collections" not in click


def test_single_alert_needs_no_action_buttons():
    assert format_actions([DEAL]) is None


def test_action_button_per_alert_up_to_the_cap():
    many = [alert("discount", f"h{i}", f"W{i}") for i in range(8)]
    assert format_actions(many).count("view,") == MAX_ACTIONS


def test_action_labels_strip_separators():
    messy = alert("discount", "m", "GA-2100, Black; Special")
    actions = format_actions([messy, DEAL])
    assert f"view, GA-2100 Black Special, {messy.product.url}" in actions


# --- delivery ---------------------------------------------------------------

def test_send_posts_one_message_per_kind():
    opener = FakeOpener([FakeResponse(b"ok"), FakeResponse(b"ok")])
    send(CFG, [DEAL, RESTOCK], opener=opener, sleep=FakeSleep())
    assert len(opener.requests) == 2


def test_restock_is_sent_at_urgent_priority():
    opener = FakeOpener([FakeResponse(b"ok")])
    send(CFG, [RESTOCK], opener=opener, sleep=FakeSleep())
    assert opener.requests[0].get_header("Priority") == "urgent"


def test_discounts_are_sent_at_high_priority():
    opener = FakeOpener([FakeResponse(b"ok")])
    send(CFG, [DEAL], opener=opener, sleep=FakeSleep())
    assert opener.requests[0].get_header("Priority") == "high"


def test_urgent_kinds_are_sent_before_routine_ones():
    opener = FakeOpener([FakeResponse(b"ok"), FakeResponse(b"ok")])
    send(CFG, [DEAL, RESTOCK], opener=opener, sleep=FakeSleep())
    assert opener.requests[0].get_header("Title").startswith("Back in stock")


def test_one_kind_collapses_into_a_single_push():
    opener = FakeOpener([FakeResponse(b"ok")])
    send(CFG, [DEAL, DEAL2], opener=opener, sleep=FakeSleep())
    assert len(opener.requests) == 1


def test_send_posts_to_the_topic_url():
    opener = FakeOpener([FakeResponse(b"ok")])
    send(CFG, [DEAL], opener=opener, sleep=FakeSleep())
    assert opener.requests[0].full_url == "https://ntfy.sh/secret-topic"


def test_send_does_nothing_without_alerts():
    opener = FakeOpener([])
    assert send(CFG, [], opener=opener, sleep=FakeSleep()) == set()


def test_send_returns_no_failures_when_delivered():
    opener = FakeOpener([FakeResponse(b"ok")])
    assert send(CFG, [DEAL], opener=opener, sleep=FakeSleep()) == set()


def test_failed_kind_reports_its_handles_only():
    opener = FakeOpener([FakeResponse(b"ok")] + [URLError("down")] * 3)
    failed = send(CFG, [DEAL, RESTOCK], opener=opener, sleep=FakeSleep())
    assert failed == {DEAL.product.handle}


def test_send_retries_before_giving_up():
    opener = FakeOpener([URLError("x"), FakeResponse(b"ok")])
    sleeper = FakeSleep()
    send(CFG, [DEAL], opener=opener, sleep=sleeper)
    assert len(opener.requests) == 2
    assert sleeper.calls == [RETRY_DELAYS[0]]


def test_send_never_logs_the_topic(caplog):
    opener = FakeOpener([URLError("down")] * 3)
    send(CFG, [DEAL], opener=opener, sleep=FakeSleep())
    assert "secret-topic" not in caplog.text


def test_ping_is_silent_priority():
    opener = FakeOpener([FakeResponse(b"ok")])
    ping(CFG, opener, FakeSleep())
    assert opener.requests[0].get_header("Priority") == "min"


def test_ping_raises_when_undeliverable():
    opener = FakeOpener([URLError("blocked")] * 3)
    with pytest.raises(NotifyError):
        ping(CFG, opener, FakeSleep())
