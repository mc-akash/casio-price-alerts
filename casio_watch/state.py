"""Persist which deals have already been announced, and diff each poll against them."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from casio_watch.store import Deal

log = logging.getLogger(__name__)

DEEPER_THRESHOLD = 1


@dataclass
class State:
    seen: dict[str, int] = field(default_factory=dict)
    etags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Diff:
    new: list[Deal]
    deeper: list[Deal]
    gone: list[str]

    @property
    def alertable(self) -> list[Deal]:
        return [*self.new, *self.deeper]


def load_state(path: Path) -> State:
    """Read persisted state, quarantining the file and starting fresh if unreadable."""
    if not path.exists():
        return State()

    try:
        payload = json.loads(path.read_text())
        if not isinstance(payload, dict):
            raise ValueError("state root must be an object")
        seen = {str(k): int(v) for k, v in (payload.get("seen") or {}).items()}
        etags = {str(k): str(v) for k, v in (payload.get("etags") or {}).items()}
        return State(seen=seen, etags=etags)
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
    tmp.write_text(json.dumps({"seen": state.seen, "etags": state.etags}, indent=2))
    os.replace(tmp, path)


def diff_deals(seen: dict[str, int], deals: list[Deal]) -> Diff:
    """Split current deals into newly seen, newly deepened, and expired."""
    current = {deal.handle: deal for deal in deals}

    new = [d for h, d in current.items() if h not in seen]
    deeper = [
        d for h, d in current.items()
        if h in seen and d.pct >= seen[h] + DEEPER_THRESHOLD
    ]
    gone = sorted(h for h in seen if h not in current)

    return Diff(new=new, deeper=deeper, gone=gone)
