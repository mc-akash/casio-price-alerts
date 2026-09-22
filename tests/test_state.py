import json

import pytest

from casio_watch.state import State, diff_deals, load_state, save_state
from casio_watch.store import Deal


def deal(handle, pct, price=5000.0):
    return Deal(handle=handle, title=handle.upper(),
                url=f"https://casiostore.bhawar.com/collections/watches/products/{handle}",
                price=price, compare_at=price / (1 - pct / 100), pct=pct)


def test_missing_file_yields_empty_state(tmp_path):
    state = load_state(tmp_path / "absent.json")
    assert state.seen == {}
    assert state.etags == {}


def test_state_round_trips(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, State(seen={"a": 30}, etags={"1": 'W/"x"'}))
    restored = load_state(path)
    assert restored.seen == {"a": 30}
    assert restored.etags == {"1": 'W/"x"'}


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "deep" / "state.json"
    save_state(path, State(seen={"a": 10}, etags={}))
    assert path.exists()


def test_corrupt_file_is_backed_up_and_state_reset(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json")
    state = load_state(path)
    assert state.seen == {}
    assert (tmp_path / "state.json.bak").read_text() == "{not valid json"


def test_state_with_wrong_shape_resets(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(["unexpected", "list"]))
    assert load_state(path).seen == {}


def test_save_is_atomic_leaving_no_temp_file(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, State(seen={"a": 10}, etags={}))
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_new_deal_is_reported_as_new():
    result = diff_deals({}, [deal("a", 30)])
    assert [d.handle for d in result.new] == ["a"]
    assert result.deeper == []
    assert result.gone == []


def test_unchanged_deal_is_not_alertable():
    result = diff_deals({"a": 30}, [deal("a", 30)])
    assert result.alertable == []


def test_deeper_discount_is_alertable():
    result = diff_deals({"a": 30}, [deal("a", 40)])
    assert [d.handle for d in result.deeper] == ["a"]
    assert result.new == []


def test_one_point_increase_meets_threshold():
    result = diff_deals({"a": 30}, [deal("a", 31)])
    assert [d.handle for d in result.deeper] == ["a"]


def test_shallower_discount_is_not_alertable():
    result = diff_deals({"a": 40}, [deal("a", 30)])
    assert result.alertable == []


def test_ended_deal_is_reported_gone():
    result = diff_deals({"a": 30, "b": 20}, [deal("a", 30)])
    assert result.gone == ["b"]


def test_alertable_combines_new_and_deeper():
    result = diff_deals({"a": 30}, [deal("a", 40), deal("b", 15)])
    assert sorted(d.handle for d in result.alertable) == ["a", "b"]


def test_diff_is_immutable():
    result = diff_deals({}, [deal("a", 30)])
    with pytest.raises(Exception):
        result.new = []
