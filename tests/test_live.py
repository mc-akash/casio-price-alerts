"""Live checks against the real store. Deselect with -m "not network"."""

import pytest

from casio_watch.config import load_config
from casio_watch.store import fetch_all, fetch_page

pytestmark = pytest.mark.network

CFG = load_config({"NTFY_TOPIC": "unused-for-fetch-tests", "MIN_DISCOUNT_PCT": "10"})


def test_store_still_serves_products_json():
    page = fetch_page(CFG, 1, None)
    assert page.not_modified is False
    assert isinstance(page.body.get("products"), list)
    assert page.body["products"], "page 1 should not be empty"


def test_variants_still_expose_price_and_compare_at_price():
    page = fetch_page(CFG, 1, None)
    variant = page.body["products"][0]["variants"][0]
    assert "price" in variant
    assert "compare_at_price" in variant
    assert "available" in variant


def test_endpoint_still_honours_if_none_match():
    first = fetch_page(CFG, 1, None)
    assert first.etag, "endpoint stopped returning an ETag; conditional polling is broken"
    second = fetch_page(CFG, 1, first.etag)
    assert second.not_modified is True


def test_full_catalogue_scan_completes():
    result = fetch_all(CFG, {})
    assert result.deals is not None
    assert result.etags, "expected at least one page ETag"
    for deal in result.deals:
        assert deal.pct >= 10
        assert deal.price < deal.compare_at
        assert deal.url.startswith("https://casiostore.bhawar.com/collections/watches/products/")
