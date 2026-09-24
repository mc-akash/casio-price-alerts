"""Decide what is worth notifying about, given the catalogue and what we saw before.

Four independent signals, in descending order of urgency:

* restock      - a watchlist model is available again
* silent_sale  - a product the store tags silent_sale_product is available again
* discount     - compare_at_price exceeds price by at least the threshold
* price_drop   - the price itself fell, even with no compare_at_price set

price_drop exists because the store runs sales that never populate
compare_at_price; a discount-only watcher cannot see those at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from casio_watch.store import Product

SILENT_SALE_TAG = "silent_sale_product"
DEEPER_THRESHOLD = 1

# Highest urgency first. At most one alert is emitted per product per cycle, so a
# restocked watchlist model is not also announced as a mere price drop.
KIND_PRIORITY = ("restock", "silent_sale", "discount", "price_drop")


@dataclass(frozen=True)
class Alert:
    kind: str
    product: Product
    detail: str


def _rupees(amount: float) -> str:
    return f"₹{amount:,.0f}"


def _is_seed(state) -> bool:
    """No prices recorded means we have never seen the catalogue before."""
    return not state.prices


def _restock(cfg, p: Product, state) -> Alert | None:
    if p.title not in cfg.watchlist or not p.available:
        return None
    if state.stock.get(p.handle, False):
        return None
    return Alert("restock", p, f"back in stock at {_rupees(p.price)}")


def _silent_sale(p: Product, state) -> Alert | None:
    if SILENT_SALE_TAG not in p.tags or not p.available:
        return None
    if state.silent.get(p.handle, False):
        return None
    return Alert("silent_sale", p, f"silent sale item available at {_rupees(p.price)}")


def _discount(cfg, p: Product, state) -> Alert | None:
    # A bargain you cannot buy is noise. The store leaves discounts, and sometimes
    # a zero price, on sold-out products long after the sale ended.
    if not p.available:
        return None
    pct = p.discount_pct
    if pct < cfg.min_discount_pct:
        return None
    previous = state.seen.get(p.handle)
    if previous is not None and pct < previous + DEEPER_THRESHOLD:
        return None
    return Alert("discount", p,
                 f"{pct}% off {_rupees(p.price)} (was {_rupees(p.compare_at)})")


def _price_drop(cfg, p: Product, state) -> Alert | None:
    if not p.available:
        return None
    previous = state.prices.get(p.handle)
    if previous is None or p.price >= previous:
        return None
    pct = round((1 - p.price / previous) * 100)
    if pct < cfg.min_discount_pct:
        return None
    return Alert("price_drop", p,
                 f"{pct}% cheaper: {_rupees(previous)} -> {_rupees(p.price)}")


def compute(cfg, products: list[Product], state) -> list[Alert]:
    """Return at most one alert per product.

    A first run has no history, so the transition signals - restock, silent sale,
    price drop - cannot be evaluated and stay silent. Discounts are different: they
    are an absolute condition, visible without any prior state. Announcing them on a
    seed matters because every restart with a fresh state volume is a first run, and
    a restart is exactly when a deal may have appeared unseen.
    """
    seed = _is_seed(state)

    alerts = []
    for p in products:
        if seed:
            existing = _discount(cfg, p, state)
            if existing is not None:
                alerts.append(existing)
            continue

        candidates = {
            "restock": _restock(cfg, p, state),
            "silent_sale": _silent_sale(p, state),
            "discount": _discount(cfg, p, state),
            "price_drop": _price_drop(cfg, p, state),
        }
        for kind in KIND_PRIORITY:
            if candidates[kind] is not None:
                alerts.append(candidates[kind])
                break
    return alerts


def apply_state(cfg, state, products: list[Product], withheld: set[str]) -> None:
    """Record what we saw, skipping products whose alert could not be delivered.

    Withholding leaves the previous values in place so the next cycle recomputes the
    same alert and retries it, rather than silently swallowing it.
    """
    for p in products:
        if p.handle in withheld:
            continue

        state.prices[p.handle] = p.price
        state.stock[p.handle] = p.available
        state.silent[p.handle] = SILENT_SALE_TAG in p.tags and p.available

        if p.discount_pct >= cfg.min_discount_pct:
            state.seen[p.handle] = p.discount_pct
        else:
            state.seen.pop(p.handle, None)
