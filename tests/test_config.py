import pytest
from pathlib import Path

from casio_watch.config import Config, ConfigError, load_config

BASE_ENV = {"NTFY_TOPIC": "casio-deals-secret"}


def test_loads_required_topic():
    cfg = load_config(BASE_ENV)
    assert cfg.ntfy_topic == "casio-deals-secret"


def test_missing_topic_raises_config_error():
    with pytest.raises(ConfigError, match="NTFY_TOPIC"):
        load_config({})


def test_blank_topic_raises_config_error():
    with pytest.raises(ConfigError, match="NTFY_TOPIC"):
        load_config({"NTFY_TOPIC": "   "})


def test_defaults_applied():
    cfg = load_config(BASE_ENV)
    assert cfg.ntfy_server == "https://ntfy.sh"
    assert cfg.min_discount_pct == 10
    assert cfg.poll_seconds == 60
    assert cfg.collection == "watches"
    assert cfg.state_path == Path("/data/state.json")
    assert cfg.seed_silent is False
    assert cfg.heartbeat_path == Path("/tmp/heartbeat")
    assert cfg.log_level == "INFO"


def test_overrides_applied():
    cfg = load_config({
        **BASE_ENV,
        "NTFY_SERVER": "https://ntfy.internal/",
        "MIN_DISCOUNT_PCT": "25",
        "POLL_SECONDS": "90",
        "COLLECTION": "clocks",
        "STATE_PATH": "/var/lib/casio/state.json",
        "SEED_SILENT": "true",
        "LOG_LEVEL": "DEBUG",
    })
    assert cfg.ntfy_server == "https://ntfy.internal"
    assert cfg.min_discount_pct == 25
    assert cfg.poll_seconds == 90
    assert cfg.collection == "clocks"
    assert cfg.state_path == Path("/var/lib/casio/state.json")
    assert cfg.seed_silent is True
    assert cfg.log_level == "DEBUG"


@pytest.mark.parametrize("raw", ["true", "TRUE", "1", "yes", "on"])
def test_truthy_seed_silent_values(raw):
    assert load_config({**BASE_ENV, "SEED_SILENT": raw}).seed_silent is True


@pytest.mark.parametrize("raw", ["false", "0", "no", "", "off"])
def test_falsy_seed_silent_values(raw):
    assert load_config({**BASE_ENV, "SEED_SILENT": raw}).seed_silent is False


def test_non_numeric_int_raises_config_error():
    with pytest.raises(ConfigError, match="POLL_SECONDS"):
        load_config({**BASE_ENV, "POLL_SECONDS": "soon"})


def test_out_of_range_discount_raises_config_error():
    with pytest.raises(ConfigError, match="MIN_DISCOUNT_PCT"):
        load_config({**BASE_ENV, "MIN_DISCOUNT_PCT": "0"})
    with pytest.raises(ConfigError, match="MIN_DISCOUNT_PCT"):
        load_config({**BASE_ENV, "MIN_DISCOUNT_PCT": "100"})


def test_poll_seconds_floor_enforced():
    with pytest.raises(ConfigError, match="POLL_SECONDS"):
        load_config({**BASE_ENV, "POLL_SECONDS": "5"})


def test_urls_built_from_collection_and_topic():
    cfg = load_config({**BASE_ENV, "COLLECTION": "watches"})
    assert cfg.collection_url == "https://casiostore.bhawar.com/collections/watches"
    assert cfg.products_url(2) == (
        "https://casiostore.bhawar.com/collections/watches/products.json?limit=250&page=2"
    )
    assert cfg.ntfy_url == "https://ntfy.sh/casio-deals-secret"


def test_config_is_immutable():
    cfg = load_config(BASE_ENV)
    with pytest.raises(Exception):
        cfg.poll_seconds = 1
