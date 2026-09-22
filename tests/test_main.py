import io
import json

import pytest
from urllib.error import HTTPError, URLError

from casio_watch.__main__ import main, run_cycle, self_test
from casio_watch.config import load_config
from casio_watch.notify import NotifyError
from casio_watch.state import State
from casio_watch.store import FetchError

DISCOUNTED = {
    "id": 1, "title": "GMA-P2110SC-4A", "handle": "gma-p2110sc-4a",
    "variants": [{"available": True, "price": "6646.50", "compare_at_price": "9495.00"}],
}
DEEPER = {
    "id": 1, "title": "GMA-P2110SC-4A", "handle": "gma-p2110sc-4a",
    "variants": [{"available": True, "price": "4747.50", "compare_at_price": "9495.00"}],
}


class FakeResponse(io.BytesIO):
    def __init__(self, payload=b"ok", etag=None):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
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
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def posted(self):
        return [r for r in self.requests if r.get_method() == "POST"]


def cfg_for(tmp_path, **overrides):
    return load_config({
        "NTFY_TOPIC": "t",
        "STATE_PATH": str(tmp_path / "state.json"),
        "HEARTBEAT_PATH": str(tmp_path / "beat"),
        **overrides,
    })


def noop_sleep(_seconds):
    return None


def test_self_test_posts_a_silent_startup_ping(tmp_path):
    opener = FakeOpener([FakeResponse()])
    self_test(cfg_for(tmp_path), opener, noop_sleep)
    assert len(opener.requests) == 1
    request = opener.requests[0]
    assert request.get_method() == "POST"
    assert request.get_header("Priority") == "min"


def test_self_test_ping_names_the_collection_and_threshold(tmp_path):
    opener = FakeOpener([FakeResponse()])
    self_test(cfg_for(tmp_path), opener, noop_sleep)
    body = opener.requests[0].data.decode("utf-8")
    assert "watches" in body
    assert "10%" in body


def test_self_test_raises_when_publishing_is_blocked(tmp_path):
    opener = FakeOpener([URLError("blocked")] * 3)
    with pytest.raises(NotifyError):
        self_test(cfg_for(tmp_path), opener, noop_sleep)


def test_first_run_alerts_and_records(tmp_path):
    state = State()
    opener = FakeOpener([
        FakeResponse({"products": [DISCOUNTED]}, etag='W/"p1"'),
        FakeResponse({"products": []}),
        FakeResponse(),
    ])
    changed = run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert changed is True
    assert state.seen == {"gma-p2110sc-4a": 30}
    assert len(opener.posted()) == 1


def test_seed_silent_records_without_alerting(tmp_path):
    state = State()
    opener = FakeOpener([
        FakeResponse({"products": [DISCOUNTED]}, etag='W/"p1"'),
        FakeResponse({"products": []}),
    ])
    run_cycle(cfg_for(tmp_path, SEED_SILENT="true"), state, opener, noop_sleep)
    assert state.seen == {"gma-p2110sc-4a": 30}
    assert opener.posted() == []


def test_unchanged_catalogue_skips_cycle(tmp_path):
    state = State(seen={"gma-p2110sc-4a": 30}, etags={"1": 'W/"p1"'})
    opener = FakeOpener([HTTPError("u", 304, "nm", {}, None)])
    changed = run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert changed is False
    assert opener.posted() == []


def test_deeper_discount_triggers_alert(tmp_path):
    state = State(seen={"gma-p2110sc-4a": 30})
    opener = FakeOpener([
        FakeResponse({"products": [DEEPER]}, etag='W/"p1"'),
        FakeResponse({"products": []}),
        FakeResponse(),
    ])
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert state.seen == {"gma-p2110sc-4a": 50}
    assert len(opener.posted()) == 1


def test_expired_deal_is_dropped_from_state(tmp_path):
    state = State(seen={"gone-watch": 30})
    opener = FakeOpener([
        FakeResponse({"products": []}, etag='W/"p1"'),
    ])
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert state.seen == {}
    assert opener.posted() == []


def test_notify_failure_withholds_handle_so_it_retries(tmp_path):
    state = State()
    opener = FakeOpener([
        FakeResponse({"products": [DISCOUNTED]}, etag='W/"p1"'),
        FakeResponse({"products": []}),
        URLError("ntfy down"), URLError("ntfy down"), URLError("ntfy down"),
    ])
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert state.seen == {}


def test_heartbeat_written_on_successful_cycle(tmp_path):
    state = State()
    opener = FakeOpener([
        FakeResponse({"products": []}, etag='W/"p1"'),
    ])
    run_cycle(cfg_for(tmp_path), state, opener, noop_sleep)
    assert (tmp_path / "beat").exists()


def test_main_once_returns_zero_and_persists_state(tmp_path, monkeypatch):
    opener = FakeOpener([
        FakeResponse(),                                              # startup ping
        FakeResponse({"products": [DISCOUNTED]}, etag='W/"p1"'),
        FakeResponse({"products": []}),
        FakeResponse(),                                              # deal alert
    ])
    monkeypatch.setattr("casio_watch.__main__.urlopen", opener)
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("HEARTBEAT_PATH", str(tmp_path / "beat"))

    assert main(["--once"]) == 0
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["seen"] == {"gma-p2110sc-4a": 30}


def test_main_once_returns_one_on_fetch_failure(tmp_path, monkeypatch):
    opener = FakeOpener([FakeResponse(), URLError("offline")])
    monkeypatch.setattr("casio_watch.__main__.urlopen", opener)
    monkeypatch.setenv("NTFY_TOPIC", "t")
    monkeypatch.setenv("STATE_PATH", str(tmp_path / "state.json"))
    monkeypatch.setenv("HEARTBEAT_PATH", str(tmp_path / "beat"))

    assert main(["--once"]) == 1


def test_main_returns_one_when_startup_ping_is_blocked(tmp_path, monkeypatch):
    opener = FakeOpener([URLError("egress blocked")] * 3)
    monkeypatch.setattr("casio_watch.__main__.urlopen", opener)
    # main() calls self_test without a sleep argument, so the retry delay comes from
    # the default bound at definition time; shorten the delays themselves instead.
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
    """Escape hatch to terminate the otherwise-infinite poll loop under test."""


def test_loop_backs_off_progressively_on_repeated_fetch_failures(tmp_path, monkeypatch):
    from casio_watch import __main__ as entry

    delays = []

    def boom(*args, **kwargs):
        raise FetchError("store down")

    def record_sleep(seconds):
        delays.append(seconds)
        if len(delays) == 5:
            raise LoopBreak

    monkeypatch.setattr(entry, "run_cycle", boom)
    monkeypatch.setattr(entry.time, "sleep", record_sleep)

    with pytest.raises(LoopBreak):
        entry._loop(cfg_for(tmp_path), State())

    assert delays == [60, 120, 240, 300, 300]


def test_loop_resets_backoff_after_a_successful_cycle(tmp_path, monkeypatch):
    from casio_watch import __main__ as entry

    delays = []
    outcomes = [FetchError("down"), FetchError("down"), None, FetchError("down")]

    def flaky(*args, **kwargs):
        result = outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return False

    def record_sleep(seconds):
        delays.append(seconds)
        if len(delays) == 4:
            raise LoopBreak

    monkeypatch.setattr(entry, "run_cycle", flaky)
    monkeypatch.setattr(entry.time, "sleep", record_sleep)

    with pytest.raises(LoopBreak):
        entry._loop(cfg_for(tmp_path), State())

    assert delays == [60, 120, 60, 60]
