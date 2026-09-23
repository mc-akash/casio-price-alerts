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
    assert cfg.product_types == ("Watches",)
    assert cfg.watchlist == ()
    assert cfg.state_path == Path("/data/state.json")
    assert cfg.heartbeat_path == Path("/tmp/heartbeat")
    assert cfg.log_level == "INFO"


def test_overrides_applied():
    cfg = load_config({
        **BASE_ENV,
        "NTFY_SERVER": "https://ntfy.internal/",
        "MIN_DISCOUNT_PCT": "25",
        "POLL_SECONDS": "90",
        "PRODUCT_TYPES": "Watches, Clocks",
        "STATE_PATH": "/var/lib/casio/state.json",
        "LOG_LEVEL": "DEBUG",
    })
    assert cfg.ntfy_server == "https://ntfy.internal"
    assert cfg.min_discount_pct == 25
    assert cfg.poll_seconds == 90
    assert cfg.product_types == ("Watches", "Clocks")
    assert cfg.state_path == Path("/var/lib/casio/state.json")
    assert cfg.log_level == "DEBUG"


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


def test_products_url_covers_the_whole_store_not_one_collection():
    cfg = load_config(BASE_ENV)
    assert cfg.products_url(2) == "https://casiostore.bhawar.com/products.json?limit=250&page=2"
    assert "collections" not in cfg.products_url(1)


def test_product_url_built_from_handle():
    cfg = load_config(BASE_ENV)
    assert cfg.product_url("gbd-200-1a1") == "https://casiostore.bhawar.com/products/gbd-200-1a1"


def test_ntfy_url_built_from_topic():
    assert load_config(BASE_ENV).ntfy_url == "https://ntfy.sh/casio-deals-secret"


def test_empty_product_types_means_every_type():
    assert load_config({**BASE_ENV, "PRODUCT_TYPES": ""}).product_types == ("Watches",)
    assert load_config({**BASE_ENV, "PRODUCT_TYPES": "*"}).product_types == ()


def test_watchlist_parsed_and_trimmed():
    cfg = load_config({**BASE_ENV, "WATCHLIST": " F-91W-1 , GBD-200UU-1 ,"})
    assert cfg.watchlist == ("F-91W-1", "GBD-200UU-1")


def test_config_is_immutable():
    cfg = load_config(BASE_ENV)
    with pytest.raises(Exception):
        cfg.poll_seconds = 1
