"""Fetch the whole-store catalogue and map it to Product objects."""

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
class Product:
    """One catalogue entry, whether in stock or not.

    Out-of-stock products matter: a restock is only visible if we track them, and
    Shopify omits them from collection feeds entirely.
    """

    handle: str
    title: str
    url: str
    price: float
    compare_at: float | None
    available: bool
    product_type: str
    tags: tuple[str, ...]

    @property
    def discount_pct(self) -> int:
        if self.compare_at is None:
            return 0
        return _discount_pct(self.price, self.compare_at)


def _discount_pct(price: float, compare_at: float) -> int:
    if compare_at <= 0 or price >= compare_at:
        return 0
    return round((1 - price / compare_at) * 100)


def _pick_variant(variants: list[dict]) -> dict | None:
    """Prefer an in-stock variant, deepest discount first; fall back to any variant.

    Falling back matters: a sold-out product still needs a price and a title so a
    later restock can be recognised as a change rather than a first sighting.
    """
    parsed = []
    for v in variants or []:
        try:
            price = float(v["price"])
        except (KeyError, TypeError, ValueError):
            continue
        cap = v.get("compare_at_price")
        try:
            compare_at = float(cap) if cap is not None else None
        except (TypeError, ValueError):
            compare_at = None
        parsed.append((bool(v.get("available")), price, compare_at))

    if not parsed:
        return None

    in_stock = [p for p in parsed if p[0]]
    pool = in_stock or parsed
    best = max(pool, key=lambda t: _discount_pct(t[1], t[2]) if t[2] else 0)
    return {"available": best[0], "price": best[1], "compare_at": best[2]}


def parse_catalogue(payload: dict, cfg) -> list[Product]:
    """Map a products.json payload to Products, filtered by configured type."""
    products: list[Product] = []
    for raw in payload.get("products") or []:
        handle = raw.get("handle")
        if not handle:
            continue

        ptype = raw.get("product_type") or ""
        if cfg.product_types and ptype not in cfg.product_types:
            continue

        chosen = _pick_variant(raw.get("variants"))
        if chosen is None:
            continue

        products.append(Product(
            handle=handle,
            title=raw.get("title") or handle,
            url=cfg.product_url(handle),
            price=chosen["price"],
            compare_at=chosen["compare_at"],
            available=chosen["available"],
            product_type=ptype,
            tags=tuple(raw.get("tags") or ()),
        ))
    return products


@dataclass(frozen=True)
class PageResult:
    body: dict | None
    etag: str | None
    not_modified: bool


@dataclass(frozen=True)
class FetchResult:
    products: list[Product] | None
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
    """Return the current catalogue, or FetchResult(products=None) when unchanged."""
    if etags and not force_full:
        probes = [fetch_page(cfg, int(page), tag, opener) for page, tag in sorted(etags.items())]
        if all(probe.not_modified for probe in probes):
            log.debug("all %d pages unchanged, skipping cycle", len(probes))
            return FetchResult(products=None, etags=etags)

    pages = _crawl(cfg, opener)
    products: list[Product] = []
    fresh_etags: dict[str, str] = {}
    for index, page in enumerate(pages, start=1):
        products.extend(parse_catalogue(page.body, cfg))
        if page.etag:
            fresh_etags[str(index)] = page.etag

    in_stock = sum(1 for p in products if p.available)
    log.info("scanned %d page(s), %d product(s), %d in stock", len(pages), len(products), in_stock)
    return FetchResult(products=products, etags=fresh_etags)
