"""Persist what the last poll saw, so the next one can tell what changed."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class State:
    """Last-seen facts, keyed by product handle.

    prices doubles as the "have we ever run" marker: an empty prices map means a
    first run, which records silently instead of announcing the whole catalogue.
    """

    seen: dict[str, int] = field(default_factory=dict)      # handle -> discount pct
    prices: dict[str, float] = field(default_factory=dict)  # handle -> last price
    stock: dict[str, bool] = field(default_factory=dict)    # handle -> was available
    silent: dict[str, bool] = field(default_factory=dict)   # handle -> tagged and available
    etags: dict[str, str] = field(default_factory=dict)     # page number -> ETag


def load_state(path: Path) -> State:
    """Read persisted state, quarantining the file and starting fresh if unreadable."""
    if not path.exists():
        return State()

    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("state root must be an object")
        return State(
            seen={str(k): int(v) for k, v in (payload.get("seen") or {}).items()},
            prices={str(k): float(v) for k, v in (payload.get("prices") or {}).items()},
            stock={str(k): bool(v) for k, v in (payload.get("stock") or {}).items()},
            silent={str(k): bool(v) for k, v in (payload.get("silent") or {}).items()},
            etags={str(k): str(v) for k, v in (payload.get("etags") or {}).items()},
        )
    except (ValueError, TypeError, AttributeError, OSError) as exc:
        backup = path.with_suffix(path.suffix + ".bak")
        log.error("state file unreadable (%s); moving to %s and starting empty", exc, backup)
        try:
            path.replace(backup)
        except OSError:
            log.error("could not back up corrupt state file")
        return State()


def save_state(path: Path, state: State) -> None:
    """Write state atomically so a crash mid-write cannot corrupt it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps({
        "seen": state.seen,
        "prices": state.prices,
        "stock": state.stock,
        "silent": state.silent,
        "etags": state.etags,
    }, indent=2))
    os.replace(tmp, path)
