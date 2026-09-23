import pytest

from casio_watch.alerts import compute, apply_state
from casio_watch.config import load_config
from casio_watch.state import State
from casio_watch.store import Product

CFG = load_config({"NTFY_TOPIC": "t", "WATCHLIST": "F-91W-1,GBD-200UU-1"})


def prod(handle, title="X", price=1000.0, compare_at=None, available=True, tags=()):
    return Product(handle=handle, title=title,
                   url=f"https://casiostore.bhawar.com/products/{handle}",
                   price=price, compare_at=compare_at, available=available,
                   product_type="Watches", tags=tuple(tags))


def kinds(alerts):
    return sorted(a.kind for a in alerts)


# --- seeding ----------------------------------------------------------------

def test_first_run_records_without_alerting():
    state = State()
    products = [prod("a", price=700, compare_at=1000), prod("b", "F-91W-1", available=False)]
    assert compute(CFG, products, state) == []


def test_first_run_still_populates_state():
    state = State()
    products = [prod("a", price=700, compare_at=1000)]
    apply_state(CFG, state, products, withheld=set())
    assert state.prices["a"] == 700
    assert state.seen["a"] == 30


# --- discounts --------------------------------------------------------------

def test_new_discount_alerts():
    state = State(prices={"a": 1000.0}, seen={})
    alerts = compute(CFG, [prod("a", price=700, compare_at=1000)], state)
    assert kinds(alerts) == ["discount"]


def test_unchanged_discount_is_quiet():
    state = State(prices={"a": 700.0}, seen={"a": 30})
    assert compute(CFG, [prod("a", price=700, compare_at=1000)], state) == []


def test_discount_below_threshold_is_quiet():
    state = State(prices={"a": 1000.0}, seen={})
    assert compute(CFG, [prod("a", price=950, compare_at=1000)], state) == []


# --- price drops without compare_at (the MTP-VT04L case) --------------------

def test_price_drop_without_compare_at_alerts():
    state = State(prices={"mtp": 3495.0})
    alerts = compute(CFG, [prod("mtp", "MTP-VT04L-8E", price=1048.0, compare_at=None)], state)
    assert kinds(alerts) == ["price_drop"]
    assert "70%" in alerts[0].detail


def test_tiny_price_drop_is_quiet():
    state = State(prices={"a": 1000.0})
    assert compute(CFG, [prod("a", price=980.0)], state) == []


def test_price_rise_is_quiet():
    state = State(prices={"a": 1000.0})
    assert compute(CFG, [prod("a", price=1200.0)], state) == []


# --- watchlist restock ------------------------------------------------------

def test_watchlist_restock_alerts():
    state = State(prices={"f": 1295.0}, stock={"f": False})
    alerts = compute(CFG, [prod("f", "F-91W-1", price=1295.0, available=True)], state)
    assert kinds(alerts) == ["restock"]


def test_watchlist_still_out_of_stock_is_quiet():
    state = State(prices={"f": 1295.0}, stock={"f": False})
    assert compute(CFG, [prod("f", "F-91W-1", price=1295.0, available=False)], state) == []


def test_discount_on_a_sold_out_product_is_quiet():
    state = State(prices={"a": 1000.0}, seen={})
    assert compute(CFG, [prod("a", price=1.0, compare_at=1000.0, available=False)], state) == []


def test_price_drop_on_a_sold_out_product_is_quiet():
    state = State(prices={"a": 1000.0})
    assert compute(CFG, [prod("a", price=100.0, available=False)], state) == []


def test_non_watchlist_restock_is_quiet():
    state = State(prices={"z": 100.0}, stock={"z": False})
    assert compute(CFG, [prod("z", "Some Other Watch", available=True)], state) == []


# --- silent sale tag --------------------------------------------------------

def test_silent_sale_product_becoming_available_alerts():
    state = State(prices={"m": 3495.0}, silent={"m": False})
    alerts = compute(CFG, [prod("m", "MTP-VT04L-8E", price=3495.0,
                                available=True, tags=["silent_sale_product"])], state)
    assert kinds(alerts) == ["silent_sale"]


def test_silent_sale_already_available_is_quiet():
    state = State(prices={"m": 3495.0}, silent={"m": True})
    assert compute(CFG, [prod("m", price=3495.0, available=True,
                              tags=["silent_sale_product"])], state) == []


# --- one alert per product --------------------------------------------------

def test_restock_wins_over_discount_for_the_same_product():
    state = State(prices={"f": 2000.0}, stock={"f": False}, seen={})
    alerts = compute(CFG, [prod("f", "F-91W-1", price=1000.0,
                                compare_at=2000.0, available=True)], state)
    assert len(alerts) == 1
    assert alerts[0].kind == "restock"


def test_discount_wins_over_price_drop_for_the_same_product():
    state = State(prices={"a": 1000.0}, seen={})
    alerts = compute(CFG, [prod("a", price=600.0, compare_at=1000.0)], state)
    assert len(alerts) == 1
    assert alerts[0].kind == "discount"


# --- state application ------------------------------------------------------

def test_withheld_products_are_not_recorded():
    state = State(prices={"a": 1000.0})
    apply_state(CFG, state, [prod("a", price=600.0, compare_at=1000.0)], withheld={"a"})
    assert state.prices["a"] == 1000.0


def test_delivered_products_are_recorded():
    state = State(prices={"a": 1000.0})
    apply_state(CFG, state, [prod("a", price=600.0, compare_at=1000.0)], withheld=set())
    assert state.prices["a"] == 600.0
    assert state.seen["a"] == 40


def test_ended_discount_is_forgotten_so_it_can_alert_again():
    state = State(prices={"a": 600.0}, seen={"a": 40})
    apply_state(CFG, state, [prod("a", price=1000.0, compare_at=1000.0)], withheld=set())
    assert "a" not in state.seen
