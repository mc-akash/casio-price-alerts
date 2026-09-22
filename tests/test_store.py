import json
from pathlib import Path

import pytest

from casio_watch.store import Deal, best_deal, parse_products

COLLECTION_URL = "https://casiostore.bhawar.com/collections/watches"
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "products.json").read_text())


def product(handle):
    return next(p for p in FIXTURE["products"] if p["handle"] == handle)


def test_equal_compare_and_price_is_not_a_deal():
    assert best_deal(product("casio-g-shock-ga-2100rl-1adr-black-analog-digital-mens-watch"),
                     COLLECTION_URL, 10) is None


def test_null_compare_price_is_not_a_deal():
    assert best_deal(product("no-compare-price"), COLLECTION_URL, 10) is None


def test_price_above_compare_is_not_a_deal():
    assert best_deal(product("price-above-compare"), COLLECTION_URL, 10) is None


def test_zero_compare_price_does_not_divide_by_zero():
    assert best_deal(product("zero-compare"), COLLECTION_URL, 10) is None


def test_product_without_variants_is_not_a_deal():
    assert best_deal(product("no-variants"), COLLECTION_URL, 10) is None


def test_below_threshold_is_excluded():
    assert best_deal(product("below-threshold"), COLLECTION_URL, 10) is None


def test_below_threshold_included_when_threshold_lowered():
    deal = best_deal(product("below-threshold"), COLLECTION_URL, 1)
    assert deal is not None
    assert deal.pct == 5


def test_real_discount_parsed_correctly():
    deal = best_deal(product("gma-p2110sc-4a"), COLLECTION_URL, 10)
    assert deal == Deal(
        handle="gma-p2110sc-4a",
        title="GMA-P2110SC-4A",
        url="https://casiostore.bhawar.com/collections/watches/products/gma-p2110sc-4a",
        price=6646.50,
        compare_at=9495.00,
        pct=30,
    )


def test_multi_variant_takes_deepest_discount():
    deal = best_deal(product("multi-variant"), COLLECTION_URL, 10)
    assert deal.pct == 50
    assert deal.price == 5000.00


def test_unavailable_variants_are_ignored():
    deal = best_deal(product("deep-but-sold-out"), COLLECTION_URL, 10)
    assert deal.pct == 12
    assert deal.price == 8800.00


def test_parse_products_returns_only_qualifying_deals():
    deals = parse_products(FIXTURE, COLLECTION_URL, 10)
    handles = sorted(d.handle for d in deals)
    assert handles == [
        "casio-g-shock-gm-2110d-3adr-green-analog-digital-mens-watch",
        "deep-but-sold-out",
        "gma-p2110sc-4a",
        "multi-variant",
    ]


def test_parse_products_tolerates_missing_products_key():
    assert parse_products({}, COLLECTION_URL, 10) == []


def test_parse_products_skips_malformed_entries():
    payload = {"products": [{"handle": "broken"}, product("gma-p2110sc-4a")]}
    deals = parse_products(payload, COLLECTION_URL, 10)
    assert [d.handle for d in deals] == ["gma-p2110sc-4a"]


def test_deal_is_immutable():
    deal = best_deal(product("gma-p2110sc-4a"), COLLECTION_URL, 10)
    with pytest.raises(Exception):
        deal.pct = 99
