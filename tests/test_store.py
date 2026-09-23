import json
from pathlib import Path

import pytest

from casio_watch.config import load_config
from casio_watch.store import Product, parse_catalogue

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "products.json").read_text())
CFG = load_config({"NTFY_TOPIC": "t"})
ALL_TYPES = load_config({"NTFY_TOPIC": "t", "PRODUCT_TYPES": "*"})


def by_handle(cfg=CFG):
    return {p.handle: p for p in parse_catalogue(FIXTURE, cfg)}


# --- discount maths ---------------------------------------------------------

def test_equal_compare_and_price_is_not_a_discount():
    p = by_handle()["casio-g-shock-ga-2100rl-1adr-black-analog-digital-mens-watch"]
    assert p.discount_pct == 0


def test_null_compare_at_is_not_a_discount():
    p = by_handle()["mtp-vt04l-8e"]
    assert p.compare_at is None
    assert p.discount_pct == 0


def test_price_above_compare_is_not_a_discount():
    assert by_handle()["price-above-compare"].discount_pct == 0


def test_zero_compare_does_not_divide_by_zero():
    assert by_handle()["zero-compare"].discount_pct == 0


def test_discount_pct_computed_from_compare_at():
    assert by_handle()["gma-p2110sc-4a"].discount_pct == 30


def test_small_discounts_are_still_reported():
    assert by_handle()["below-threshold"].discount_pct == 5


def test_multi_variant_takes_deepest_discount():
    p = by_handle()["multi-variant"]
    assert p.discount_pct == 50
    assert p.price == 5000.00


def test_in_stock_variant_preferred_over_deeper_sold_out_one():
    p = by_handle()["deep-but-sold-out"]
    assert p.available is True
    assert p.price == 8800.00
    assert p.discount_pct == 12


# --- catalogue scope --------------------------------------------------------

def test_out_of_stock_products_are_kept():
    p = by_handle()["casio-f-91w-1q-black-digital-unisex-watch"]
    assert p.available is False
    assert p.price == 1295.00


def test_product_types_filtered_by_default():
    assert "fx-991ex" not in by_handle()


def test_every_type_included_when_unfiltered():
    assert "fx-991ex" in by_handle(ALL_TYPES)


def test_tags_exposed():
    assert "silent_sale_product" in by_handle()["mtp-vt04l-8e"].tags


def test_product_without_variants_is_skipped():
    assert "no-variants" not in by_handle()


def test_missing_products_key_yields_nothing():
    assert parse_catalogue({}, CFG) == []


def test_entry_without_handle_is_skipped():
    payload = {"products": [{"title": "orphan", "product_type": "Watches", "variants": []}]}
    assert parse_catalogue(payload, CFG) == []


def test_url_points_at_the_product_page():
    assert by_handle()["gma-p2110sc-4a"].url == (
        "https://casiostore.bhawar.com/products/gma-p2110sc-4a"
    )


def test_product_is_immutable():
    with pytest.raises(Exception):
        by_handle()["gma-p2110sc-4a"].price = 1.0
