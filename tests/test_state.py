import json

from casio_watch.state import State, load_state, save_state


def test_missing_file_yields_empty_state(tmp_path):
    state = load_state(tmp_path / "absent.json")
    assert state.seen == {} and state.prices == {} and state.etags == {}


def test_state_round_trips_every_field(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, State(seen={"a": 30}, prices={"a": 700.0}, stock={"a": True},
                           silent={"a": False}, etags={"1": 'W/"x"'}))
    r = load_state(path)
    assert r.seen == {"a": 30}
    assert r.prices == {"a": 700.0}
    assert r.stock == {"a": True}
    assert r.silent == {"a": False}
    assert r.etags == {"1": 'W/"x"'}


def test_save_creates_parent_directory(tmp_path):
    path = tmp_path / "nested" / "deep" / "state.json"
    save_state(path, State(prices={"a": 1.0}))
    assert path.exists()


def test_corrupt_file_is_backed_up_and_state_reset(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not valid json")
    assert load_state(path).prices == {}
    assert (tmp_path / "state.json.bak").read_text() == "{not valid json"


def test_state_with_wrong_shape_resets(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps(["unexpected", "list"]))
    assert load_state(path).prices == {}


def test_save_is_atomic_leaving_no_temp_file(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, State(prices={"a": 1.0}))
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]


def test_older_state_without_new_fields_still_loads(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"seen": {"a": 30}, "etags": {"1": "x"}}))
    state = load_state(path)
    assert state.seen == {"a": 30}
    assert state.prices == {} and state.stock == {} and state.silent == {}
