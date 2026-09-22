"""Entry point: one-shot or continuous polling of the Casio store."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from urllib.request import urlopen

from casio_watch import notify
from casio_watch.config import ConfigError, load_config
from casio_watch.notify import NotifyError
from casio_watch.state import diff_deals, load_state, save_state
from casio_watch.store import FetchError, fetch_all

log = logging.getLogger("casio_watch")

BACKOFF = (60, 120, 240, 300)
FULL_REFRESH_CYCLES = 30


def self_test(cfg, opener=urlopen, sleep=time.sleep) -> None:
    """Prove the notification path works before committing to a long-running loop.

    A blocked publish path is the one failure that is otherwise invisible: polling
    keeps succeeding and the pod stays Running, but no alert ever arrives, and with
    nothing discounted the loop may not attempt a publish for weeks. The store is
    deliberately not probed here - a fetch failure surfaces on the first cycle.
    """
    notify.ping(cfg, opener, sleep)


def _touch(path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()))
    except OSError as exc:
        log.warning("could not write heartbeat: %s", exc)


def run_cycle(cfg, state, opener=urlopen, sleep=time.sleep, force_full: bool = False) -> bool:
    """Poll once. Returns True when state changed and should be persisted."""
    is_seed = not state.seen and not state.etags

    result = fetch_all(cfg, state.etags, opener, force_full=force_full)
    if result.deals is None:
        _touch(cfg.heartbeat_path)
        return False

    state.etags = result.etags
    diff = diff_deals(state.seen, result.deals)

    for handle in diff.gone:
        state.seen.pop(handle, None)
        log.info("deal ended: %s", handle)

    withheld: set[str] = set()
    alertable = diff.alertable
    if alertable and not (is_seed and cfg.seed_silent):
        try:
            notify.send(cfg, alertable, opener=opener, sleep=sleep)
        except NotifyError as exc:
            log.error("%s; withholding %d deal(s) for retry next cycle", exc, len(alertable))
            withheld = {d.handle for d in alertable}

    for deal in result.deals:
        if deal.handle not in withheld:
            state.seen[deal.handle] = deal.pct

    _touch(cfg.heartbeat_path)
    return True


def _loop(cfg, state) -> int:
    failures = 0
    cycles = 0
    while True:
        try:
            force_full = cycles % FULL_REFRESH_CYCLES == 0
            if run_cycle(cfg, state, urlopen, force_full=force_full):
                save_state(cfg.state_path, state)
            failures = 0
            delay = cfg.poll_seconds
        except FetchError as exc:
            delay = BACKOFF[min(failures, len(BACKOFF) - 1)]
            failures += 1
            log.warning("cycle failed (%s); backing off %ds", exc, delay)
        cycles += 1
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
            if run_cycle(cfg, state, urlopen):
                save_state(cfg.state_path, state)
        except FetchError as exc:
            log.error("poll failed: %s", exc)
            return 1
        return 0

    log.info("polling %s every %ds at >=%d%% off", cfg.collection_url,
             cfg.poll_seconds, cfg.min_discount_pct)
    return _loop(cfg, state)


if __name__ == "__main__":
    sys.exit(main())
