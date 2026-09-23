"""Live checks against the real store. Deselect with -m "not network"."""

import pytest

from casio_watch.config import load_config
from casio_watch.store import fetch_all, fetch_page, parse_catalogue

pytestmark = pytest.mark.network

CFG = load_config({"NTFY_TOPIC": "unused-for-fetch-tests"})
ALL_TYPES = load_config({"NTFY_TOPIC": "unused", "PRODUCT_TYPES": "*"})


def test_store_serves_the_whole_catalogue_feed():
    page = fetch_page(CFG, 1, None)
    assert page.not_modified is False
    assert page.body["products"], "page 1 should not be empty"


def test_variants_still_expose_availability_and_prices():
    variant = fetch_page(CFG, 1, None).body["products"][0]["variants"][0]
    for key in ("price", "compare_at_price", "available"):
        assert key in variant, f"{key} disappeared from the feed"


def test_products_still_carry_type_and_tags():
    product = fetch_page(CFG, 1, None).body["products"][0]
    assert "product_type" in product
    assert "tags" in product


def test_endpoint_still_honours_if_none_match():
    first = fetch_page(CFG, 1, None)
    assert first.etag, "ETag gone; conditional polling would stop working"
    assert fetch_page(CFG, 1, first.etag).not_modified is True


def test_whole_store_scan_sees_far_more_than_one_collection():
    result = fetch_all(ALL_TYPES, {})
    assert result.products is not None
    # the watches collection held ~463; the whole store is several times that
    assert len(result.products) > 1000, f"only {len(result.products)} products seen"


def test_out_of_stock_products_are_present_in_the_feed():
    result = fetch_all(ALL_TYPES, {})
    assert any(not p.available for p in result.products), \
        "no out-of-stock products: restock detection would be impossible"


def test_silent_sale_tag_still_exists_in_the_catalogue():
    result = fetch_all(ALL_TYPES, {})
    assert any("silent_sale_product" in p.tags for p in result.products)
