import io
import json

import pytest
from urllib.error import HTTPError, URLError

from casio_watch.__main__ import main, run_cycle, self_test
from casio_watch.config import load_config
from casio_watch.notify import NotifyError
from casio_watch.state import State
from casio_watch.store import FetchError


def watch(handle, title, price, compare_at=None, available=True, tags=()):
    return {"id": 1, "title": title, "handle": handle, "product_type": "Watches",
            "tags": list(tags),
            "variants": [{"available": available, "price": price,
                          "compare_at_price": compare_at}]}


FULL_PRICE = watch("gma", "GMA-P2110SC-4A", "9495.00", "9495.00")
DISCOUNTED = watch("gma", "GMA-P2110SC-4A", "6646.50", "9495.00")
SILENT_OOS = watch("mtp", "MTP-VT04L-8E", "3495.00", None, available=False,
                   tags=["silent_sale_product"])
SILENT_BACK = watch("mtp", "MTP-VT04L-8E", "1048.00", None, available=True,
                    tags=["silent_sale_product"])


class FakeResponse(io.BytesIO):
    def __init__(self, payload=b"ok", etag=None):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self._etag = etag

    @property
    def headers(self):
        return {"ETag": self._etag} if self._etag else {}

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

    def posted(self):
        return [r for r in self.requests if r.get_method() == "POST"]


def cfg_for(tmp_path, **overrides):
    return load_config({"NTFY_TOPIC": "t",
                        "STATE_PATH": str(tmp_path / "state.json"),
                        "HEARTBEAT_PATH": str(tmp_path / "beat"),
                        **overrides})


def noop_sleep(_s):
    return None


def catalogue(*products, etag='W/"p1"'):
    """One page of products followed by the empty page that ends pagination."""
    return [FakeResponse({"products": list(products)}, etag=etag),
            FakeResponse({"products": []})]


# --- self test --------------------------------------------------------------

def test_self_test_posts_a_silent_ping(tmp_path):
    opener = FakeOpener([FakeResponse()])
    self_test(cfg_for(tmp_path), opener, noop_sleep)
    assert opener.requests[0].get_header("Priority") == "min"


def test_self_test_raises_when_publishing_is_blocked(tmp_path):
    opener = FakeOpener([URLError("blocked")] * 3)
    with pytest.raises(NotifyError):
        self_test(cfg_for(tmp_path), opener, noop_sleep)


# --- cycles -----------------------------------------------------------------

def test_first_run_announces_an_already_active_discount(tmp_path):
    """A restart re-seeds; a deal that appeared during downtime must still surface."""
    state = State()
    opener = FakeOpener(catalogue(DISCOUNTED) + [FakeResponse()])
    assert run_cycle(cfg_for(tmp_path), state, opener, noop_sleep) is True
    assert len(opener.posted()) == 1
    assert state.prices["gma"] == 6646.50
    assert state.seen["gma"] == 30


def test_first_run_is_silent_when_nothing_is_discounted(tmp_path):
    state = State()
    opener = FakeOpener(catalogue(FULL_PRICE))
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert opener.posted() == []


def test_new_discount_after_baseline_alerts(tmp_path):
    state = State(prices={"gma": 9495.00}, stock={"gma": True}, seen={})
    opener = FakeOpener(catalogue(DISCOUNTED) + [FakeResponse()])
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert len(opener.posted()) == 1
    assert state.seen["gma"] == 30


def test_silent_sale_restock_alerts_urgently(tmp_path):
    state = State(prices={"mtp": 3495.00}, stock={"mtp": False}, silent={"mtp": False})
    opener = FakeOpener(catalogue(SILENT_BACK) + [FakeResponse()])
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    posted = opener.posted()
    assert len(posted) == 1
    assert posted[0].get_header("Priority") == "urgent"


def test_watchlist_restock_alerts(tmp_path):
    state = State(prices={"f91": 1295.0}, stock={"f91": False})
    back = watch("f91", "F-91W-1", "1295.00", None, available=True)
    opener = FakeOpener(catalogue(back) + [FakeResponse()])
    run_cycle(cfg_for(tmp_path, WATCHLIST="F-91W-1"), state, opener, noop_sleep)
    assert opener.posted()[0].get_header("Title") == "Back in stock: F-91W-1"


def test_sold_out_discount_does_not_alert(tmp_path):
    state = State(prices={"z": 10000.0}, stock={"z": True})
    dead = watch("z", "Sold Out Bargain", "0.00", "10000.00", available=False)
    opener = FakeOpener(catalogue(dead))
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert opener.posted() == []


def test_unchanged_catalogue_skips_cycle(tmp_path):
    state = State(prices={"gma": 6646.5}, etags={"1": 'W/"p1"'})
    opener = FakeOpener([HTTPError("u", 304, "nm", {}, None)])
    assert run_cycle(cfg_for(tmp_path), state, opener, noop_sleep) is False
    assert opener.posted() == []


def test_notify_failure_withholds_so_it_retries(tmp_path):
    state = State(prices={"gma": 9495.00}, stock={"gma": True})
    opener = FakeOpener(catalogue(DISCOUNTED) + [URLError("down")] * 3)
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert state.prices["gma"] == 9495.00, "price must not advance while the alert is unsent"


def test_heartbeat_written_each_cycle(tmp_path):
    opener = FakeOpener(catalogue(FULL_PRICE))
    run_cycle(cfg_for(tmp_path), State(), opener, noop_sleep)
    assert (tmp_path / "beat").exists()


# --- entry point ------------------------------------------------------------

def test_main_once_returns_zero_and_persists_state(tmp_path, monkeypatch):
    opener = FakeOpener([FakeResponse()] + catalogue(DISCOUNTED) + [FakeResponse()])
    monkeypatch.setattr("casio_watch.__main__.urlopen", opener)
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("HEARTBEAT_PATH", str(tmp_path / "beat"))
    assert main(["--once"]) == 0
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["prices"]["gma"] == 6646.50


def test_main_once_returns_one_on_fetch_failure(tmp_path, monkeypatch):
    opener = FakeOpener([FakeResponse(), URLError("offline")])
    monkeypatch.setattr("casio_watch.__main__.urlopen", opener)
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("HEARTBEAT_PATH", str(tmp_path / "beat"))
    assert main(["--once"]) == 1


def test_main_returns_one_when_startup_ping_blocked(tmp_path, monkeypatch):
    opener = FakeOpener([URLError("egress blocked")] * 3)
    monkeypatch.setattr("casio_watch.__main__.urlopen", opener)
    monkeypatch.setattr("casio_watch.notify.RETRY_DELAYS", (0, 0, 0))
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("HEARTBEAT_PATH", str(tmp_path / "beat"))
    assert main(["--once"]) == 1


def test_main_returns_two_on_config_error(monkeypatch, capsys):
    monkeypatch.delenv("NTFY_TOPIC", raising=False)
    assert main(["--once"]) == 2
    assert "NTFY_TOPIC" in capsys.readouterr().err


class LoopBreak(Exception):
    pass


def test_loop_backs_off_progressively(tmp_path, monkeypatch):
    from casio_watch import __main__ as entry
    delays = []

    def boom(*a, **k):
        raise FetchError("store down")

    def record(seconds):
        delays.append(seconds)
        if len(delays) == 5:
            raise LoopBreak

    monkeypatch.setattr(entry, "run_cycle", boom)
    monkeypatch.setattr(entry.time, "sleep", record)
    with pytest.raises(LoopBreak):
        entry._loop(cfg_for(tmp_path), State())
    assert delays == [60, 120, 240, 300, 300]


def test_loop_resets_backoff_after_success(tmp_path, monkeypatch):
    from casio_watch import __main__ as entry
    delays = []
    outcomes = [FetchError("down"), FetchError("down"), None, FetchError("down")]

    def flaky(*a, **k):
        r = outcomes.pop(0)
        if isinstance(r, Exception):
            raise r
        return False

    def record(seconds):
        delays.append(seconds)
        if len(delays) == 4:
            raise LoopBreak

    monkeypatch.setattr(entry, "run_cycle", flaky)
    monkeypatch.setattr(entry.time, "sleep", record)
    with pytest.raises(LoopBreak):
        entry._loop(cfg_for(tmp_path), State())
    assert delays == [60, 120, 60, 60]
