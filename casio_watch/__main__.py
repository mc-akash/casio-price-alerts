"""Entry point: one-shot or continuous polling of the Casio store."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from urllib.request import urlopen

from casio_watch import notify
from casio_watch.browser import browser_open
from casio_watch.config import ConfigError, load_config
from casio_watch.notify import NotifyError
from casio_watch import alerts as alerting
from casio_watch.state import load_state, save_state
from casio_watch.store import FetchError, fetch_all

log = logging.getLogger("casio_watch")

# Shopify's storefront limiter needs a long quiet spell to clear; a short capped
# backoff re-trips it on every retry, so failures escalate to half an hour.
BACKOFF = (60, 300, 900, 1800)
MAX_DELAY_SECONDS = 3600
FULL_REFRESH_CYCLES = 30


def self_test(cfg, opener=urlopen, sleep=time.sleep) -> None:
    """Prove the notification path works before committing to a long-running loop.

    A blocked publish path is the one failure that is otherwise invisible: polling
    keeps succeeding and the pod stays Running, but no alert ever arrives, and with
    nothing discounted the loop may not attempt a publish for weeks. The store is
    deliberately not probed here - a fetch failure surfaces on the first cycle.
    """
    notify.ping(cfg, opener, sleep)


def _touch(path, deadline: float) -> None:
    """Record when the next cycle is due; the healthcheck fails once it is overdue.

    A deadline rather than a last-seen time keeps a long backoff healthy: restarting
    a container that is merely waiting out a rate limit would only reset the backoff
    and hit the store again.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(deadline))
    except OSError as exc:
        log.warning("could not write heartbeat: %s", exc)


def note_rate_limit(cfg, state, exc: FetchError, opener=urlopen,
                    sleep=time.sleep) -> bool:
    """Warn once when the store starts answering 429. Returns True when state changed.

    The flag lives in persisted state, so a restart mid-outage stays quiet; the next
    successful poll clears it. An undelivered warning leaves the flag unset, so the
    next 429 tries again.
    """
    if exc.status != 429 or state.rate_limited:
        return False
    try:
        notify.rate_limited(cfg, str(exc), opener, sleep)
    except NotifyError as exc_notify:
        log.error("could not deliver rate-limit warning: %s", exc_notify)
        return False
    state.rate_limited = True
    return True


def run_cycle(cfg, state, opener=urlopen, sleep=time.sleep, force_full: bool = False,
              store_opener=None) -> bool:
    """Poll once. Returns True when state changed and should be persisted.

    opener publishes to ntfy; store_opener fetches the catalogue and defaults to
    opener, so tests can script both through one fake.
    """
    result = fetch_all(cfg, state.etags, store_opener or opener, force_full=force_full,
                       sleep=sleep)
    if result.products is None:
        return False

    state.etags = result.etags

    found = alerting.compute(cfg, result.products, state)
    withheld = notify.send(cfg, found, opener=opener, sleep=sleep) if found else set()
    if withheld:
        log.error("withholding %d undelivered alert(s) for retry next cycle", len(withheld))

    alerting.apply_state(cfg, state, result.products, withheld)
    return True


def _loop(cfg, state) -> int:
    failures = 0
    cycles = 0
    while True:
        try:
            force_full = cycles % FULL_REFRESH_CYCLES == 0
            changed = run_cycle(cfg, state, urlopen, force_full=force_full,
                                store_opener=browser_open)
            if state.rate_limited:
                log.info("store reachable again")
                state.rate_limited = False
                changed = True
            if changed:
                save_state(cfg.state_path, state)
            failures = 0
            delay = cfg.poll_seconds
        except FetchError as exc:
            backoff = BACKOFF[min(failures, len(BACKOFF) - 1)]
            delay = min(max(backoff, exc.retry_after or 0), MAX_DELAY_SECONDS)
            failures += 1
            log.warning("cycle failed (%s); backing off %ds", exc, delay)
            if note_rate_limit(cfg, state, exc, urlopen):
                save_state(cfg.state_path, state)
        cycles += 1
        _touch(cfg.heartbeat_path, time.time() + delay)
        time.sleep(delay)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="casio_watch", description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="poll once and exit")
    mode.add_argument("--loop", action="store_true", help="poll forever")
    args = parser.parse_args(argv)

    try:
        cfg = load_config()
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(
        level=cfg.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    try:
        self_test(cfg, urlopen)
    except NotifyError as exc:
        log.error("startup self-test failed, notifications would be lost: %s", exc)
        return 1

    state = load_state(cfg.state_path)

    if args.once:
        try:
            if run_cycle(cfg, state, urlopen, store_opener=browser_open):
                save_state(cfg.state_path, state)
        except FetchError as exc:
            log.error("poll failed: %s", exc)
            return 1
        return 0

    scope = ", ".join(cfg.product_types) if cfg.product_types else "all product types"
    log.info("polling the whole store (%s) every %ds at >=%d%%, watchlist: %s",
             scope, cfg.poll_seconds, cfg.min_discount_pct,
             ", ".join(cfg.watchlist) or "none")
    return _loop(cfg, state)


if __name__ == "__main__":
    sys.exit(main())
