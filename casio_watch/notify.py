"""Format deals into a single batched push and deliver it to ntfy."""

from __future__ import annotations

import logging
import time
import urllib.request
from urllib.error import HTTPError, URLError


log = logging.getLogger(__name__)

MAX_LISTED = 10
MAX_ACTIONS = 3
KIND_ORDER = ("restock", "silent_sale", "discount", "price_drop")
RETRY_DELAYS = (2, 6, 18)
TIMEOUT_SECONDS = 15


class NotifyError(Exception):
    """Raised when a notification could not be delivered after every retry."""


# singular title, plural label, ntfy priority, ntfy tag
KINDS = {
    "restock":     ("Back in stock", "back in stock",    "urgent", "rotating_light"),
    "silent_sale": ("Silent sale",   "silent sale items", "urgent", "zap"),
    "discount":    ("New deal",      "new Casio deals",  "high",   "fire"),
    "price_drop":  ("Price drop",    "price drops",      "high",   "chart_with_downwards_trend"),
}


def _action_label(title: str) -> str:
    """Strip the separators ntfy uses to delimit actions and their fields."""
    return " ".join(title.replace(",", " ").replace(";", " ").split())


def format_actions(alerts: list) -> str | None:
    """Build ntfy view buttons so a batch can reach every product.

    A single alert needs none - the notification's own click target already goes there.
    """
    if len(alerts) < 2:
        return None
    return "; ".join(
        f"view, {_action_label(a.product.title)}, {a.product.url}"
        for a in alerts[:MAX_ACTIONS]
    )


def format_group(kind: str, alerts: list) -> tuple[str, str, str]:
    """Build the (title, body, click_url) triple for one kind of alert."""
    singular, plural, _, _ = KINDS[kind]

    if len(alerts) == 1:
        title = f"{singular}: {alerts[0].product.title}"
    else:
        title = f"{len(alerts)} {plural}"

    lines = [f"{a.product.title} - {a.detail}" for a in alerts[:MAX_LISTED]]
    if len(alerts) > MAX_LISTED:
        lines.append(f"+{len(alerts) - MAX_LISTED} more")

    # Always a product page, never a collection: the store's only discount facet is
    # "30% Off Or More", so no collection URL can represent what we actually alert on.
    return title, "\n".join(lines), alerts[0].product.url


def _post(cfg, body: str, headers: dict[str, str], opener, sleep) -> None:
    """POST to the topic, retrying transient failures before giving up."""
    request = urllib.request.Request(cfg.ntfy_url, data=body.encode("utf-8"), method="POST")
    for name, value in headers.items():
        request.add_header(name, value)

    last_error: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            with opener(request, timeout=TIMEOUT_SECONDS):
                return
        except (HTTPError, URLError, OSError) as exc:
            last_error = exc
            log.warning("notify attempt %d/%d failed: %s", attempt, len(RETRY_DELAYS), exc)
            if attempt < len(RETRY_DELAYS):
                sleep(delay)

    raise NotifyError(f"delivery failed after {len(RETRY_DELAYS)} attempts: {last_error}")


def send(cfg, alerts: list, opener=urllib.request.urlopen,
         sleep=time.sleep) -> set[str]:
    """Publish one push per alert kind. Returns handles that could not be delivered.

    Grouping by kind keeps a restock urgent without making every discount urgent too,
    while still collapsing a store-wide sale into a single notification.
    """
    if not alerts:
        return set()

    failed: set[str] = set()
    for kind in KIND_ORDER:
        group = [a for a in alerts if a.kind == kind]
        if not group:
            continue

        group = sorted(group, key=lambda a: a.product.title)
        title, body, click = format_group(kind, group)
        _, _, priority, tag = KINDS[kind]

        headers = {"Title": title, "Priority": priority, "Tags": tag, "Click": click}
        actions = format_actions(group)
        if actions:
            headers["Actions"] = actions

        try:
            _post(cfg, body, headers, opener, sleep)
            log.info("notified: %s", title)
        except NotifyError as exc:
            log.error("could not deliver %s alert(s): %s", kind, exc)
            failed.update(a.product.handle for a in group)

    return failed


def ping(cfg, opener=urllib.request.urlopen, sleep=time.sleep) -> None:
    """Publish a silent startup marker, proving the real publish path works.

    Priority "min" lands in the ntfy app's history without a sound or banner, so
    restarts stay visible without being noisy.
    """
    scope = ", ".join(cfg.product_types) if cfg.product_types else "the whole store"
    body = (
        f"casio-price-alerts started · watching {scope} "
        f"at >={cfg.min_discount_pct}% off, every {cfg.poll_seconds}s"
    )
    _post(cfg, body, {"Title": "Watcher online", "Priority": "min",
                      "Tags": "white_check_mark"}, opener, sleep)
    log.info("startup ping delivered")
