"""Fetch the collection catalogue and map products to Deal objects."""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass
from urllib.error import HTTPError, URLError

log = logging.getLogger(__name__)

MAX_PAGES = 20
TIMEOUT_SECONDS = 20
USER_AGENT = "casio-price-alerts/1.0 (personal price alert; 1 request/min)"


class FetchError(Exception):
    """Raised when the catalogue could not be retrieved."""


@dataclass(frozen=True)
class Deal:
    handle: str
    title: str
    url: str
    price: float
    compare_at: float
    pct: int


def _discount_pct(price: float, compare_at: float) -> int:
    if compare_at <= 0 or price >= compare_at:
        return 0
    return round((1 - price / compare_at) * 100)


def best_deal(product: dict, collection_url: str, min_pct: int) -> Deal | None:
    """Return the deepest qualifying discount across a product's available variants."""
    handle = product.get("handle")
    if not handle:
        return None

    best: tuple[int, float, float] | None = None
    for variant in product.get("variants") or []:
        if not variant.get("available"):
            continue
        try:
            price = float(variant["price"])
            compare_at = float(variant["compare_at_price"])
        except (KeyError, TypeError, ValueError):
            continue

        pct = _discount_pct(price, compare_at)
        if pct >= min_pct and (best is None or pct > best[0]):
            best = (pct, price, compare_at)

    if best is None:
        return None

    pct, price, compare_at = best
    return Deal(
        handle=handle,
        title=product.get("title") or handle,
        url=f"{collection_url}/products/{handle}",
        price=price,
        compare_at=compare_at,
        pct=pct,
    )


def parse_products(payload: dict, collection_url: str, min_pct: int) -> list[Deal]:
    """Map a products.json payload to the deals that meet the threshold."""
    deals = []
    for product in payload.get("products") or []:
        deal = best_deal(product, collection_url, min_pct)
        if deal is not None:
            deals.append(deal)
    return deals


@dataclass(frozen=True)
class PageResult:
    body: dict | None
    etag: str | None
    not_modified: bool


@dataclass(frozen=True)
class FetchResult:
    deals: list[Deal] | None
    etags: dict[str, str]


def fetch_page(cfg, page: int, etag: str | None, opener=urllib.request.urlopen) -> PageResult:
    """Fetch one catalogue page, conditionally when an ETag is known."""
    request = urllib.request.Request(cfg.products_url(page))
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    if etag:
        request.add_header("If-None-Match", etag)

    try:
        with opener(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
            new_etag = response.headers.get("ETag")
    except HTTPError as exc:
        if exc.code == 304:
            return PageResult(body=None, etag=etag, not_modified=True)
        raise FetchError(f"page {page} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise FetchError(f"page {page} unreachable: {exc.reason}") from exc

    try:
        body = json.loads(raw)
    except ValueError as exc:
        raise FetchError(f"page {page} returned invalid JSON") from exc

    return PageResult(body=body, etag=new_etag, not_modified=False)


def _crawl(cfg, opener) -> list[PageResult]:
    """Walk pages unconditionally until one comes back empty."""
    pages = []
    for page in range(1, MAX_PAGES + 1):
        result = fetch_page(cfg, page, None, opener)
        if not (result.body.get("products") or []):
            break
        pages.append(result)
    return pages


def fetch_all(cfg, etags: dict[str, str], opener=urllib.request.urlopen,
              force_full: bool = False) -> FetchResult:
    """Return current deals, or FetchResult(deals=None) when nothing changed."""
    if etags and not force_full:
        probes = [fetch_page(cfg, int(page), tag, opener) for page, tag in sorted(etags.items())]
        if all(probe.not_modified for probe in probes):
            log.debug("all %d pages unchanged, skipping cycle", len(probes))
            return FetchResult(deals=None, etags=etags)

    pages = _crawl(cfg, opener)
    deals: list[Deal] = []
    fresh_etags: dict[str, str] = {}
    for index, page in enumerate(pages, start=1):
        deals.extend(parse_products(page.body, cfg.collection_url, cfg.min_discount_pct))
        if page.etag:
            fresh_etags[str(index)] = page.etag

    log.info("scanned %d page(s), %d deal(s) at >=%d%%", len(pages), len(deals), cfg.min_discount_pct)
    return FetchResult(deals=deals, etags=fresh_etags)
