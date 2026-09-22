"""Format deals into a single batched push and deliver it to ntfy."""

from __future__ import annotations

import logging
import time
import urllib.request
from urllib.error import HTTPError, URLError

from casio_watch.store import Deal

log = logging.getLogger(__name__)

MAX_LISTED = 10
MAX_ACTIONS = 3
RETRY_DELAYS = (2, 6, 18)
TIMEOUT_SECONDS = 15


class NotifyError(Exception):
    """Raised when a notification could not be delivered after every retry."""


def _rupees(amount: float) -> str:
    return f"₹{amount:,.0f}"


def format_message(deals: list[Deal], collection_url: str) -> tuple[str, str, str]:
    """Build the (title, body, click_url) triple for a batch of deals."""
    ranked = sorted(deals, key=lambda d: (-d.pct, d.title))

    noun = "deal" if len(ranked) == 1 else "deals"
    title = f"{len(ranked)} new Casio {noun}"

    lines = [
        f"{d.title} — {d.pct}% off {_rupees(d.price)} (was {_rupees(d.compare_at)})"
        for d in ranked[:MAX_LISTED]
    ]
    if len(ranked) > MAX_LISTED:
        lines.append(f"+{len(ranked) - MAX_LISTED} more")

    # Always the deepest-discounted product, never the collection page: the store's
    # only discount facet is "30% Off Or More", so no collection URL can represent a
    # lower threshold, and the unfiltered page strands the reader among 465 watches.
    return title, "\n".join(lines), ranked[0].url


def format_actions(deals: list[Deal]) -> str | None:
    """Build ntfy view buttons, one per deal, so a batch reaches every watch.

    A single deal needs none - the notification's own click target already goes there.
    """
    if len(deals) < 2:
        return None

    ranked = sorted(deals, key=lambda d: (-d.pct, d.title))
    return "; ".join(
        f"view, {_action_label(d.title)}, {d.url}" for d in ranked[:MAX_ACTIONS]
    )


def _action_label(title: str) -> str:
    """Strip the separators ntfy uses to delimit actions and their fields."""
    return " ".join(title.replace(",", " ").replace(";", " ").split())


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


def send(cfg, deals: list[Deal], opener=urllib.request.urlopen, sleep=time.sleep) -> None:
    """POST one batched deal notification."""
    if not deals:
        return

    title, body, click = format_message(deals, cfg.collection_url)
    headers = {"Title": title, "Priority": "high", "Tags": "fire", "Click": click}
    actions = format_actions(deals)
    if actions:
        headers["Actions"] = actions
    _post(cfg, body, headers, opener, sleep)
    log.info("notified: %s", title)


def ping(cfg, opener=urllib.request.urlopen, sleep=time.sleep) -> None:
    """Publish a silent startup marker, proving the real publish path works.

    Priority "min" lands in the ntfy app's history without a sound or banner, so
    restarts stay visible without being noisy.
    """
    body = (
        f"casio-price-alerts started · watching {cfg.collection} "
        f"at >={cfg.min_discount_pct}% off, every {cfg.poll_seconds}s"
    )
    _post(cfg, body, {"Title": "Watcher online", "Priority": "min",
                      "Tags": "white_check_mark"}, opener, sleep)
    log.info("startup ping delivered")
