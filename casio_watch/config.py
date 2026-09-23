"""Environment-driven configuration, validated once at startup."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

STORE_HOST = "https://casiostore.bhawar.com"
PAGE_SIZE = 250
MIN_POLL_SECONDS = 30
TRUTHY = {"true", "1", "yes", "on"}


class ConfigError(Exception):
    """Raised when the environment is missing or malformed."""


@dataclass(frozen=True)
class Config:
    ntfy_topic: str
    ntfy_server: str
    min_discount_pct: int
    poll_seconds: int
    product_types: tuple[str, ...]
    watchlist: tuple[str, ...]
    state_path: Path
    heartbeat_path: Path
    log_level: str

    def products_url(self, page: int) -> str:
        """The whole-store feed.

        A collection feed would be smaller, but Shopify drops out-of-stock products
        from collections and keeps hundreds of watches outside /collections/watches
        entirely, so a collection cannot see restocks or every sale.
        """
        return f"{STORE_HOST}/products.json?limit={PAGE_SIZE}&page={page}"

    def product_url(self, handle: str) -> str:
        return f"{STORE_HOST}/products/{handle}"

    @property
    def ntfy_url(self) -> str:
        return f"{self.ntfy_server}/{self.ntfy_topic}"


def _require(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise ConfigError(f"{key} is required and must not be blank")
    return value


def _int(env: Mapping[str, str], key: str, default: int) -> int:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{key} must be an integer, got {raw!r}") from exc


def _csv(env: Mapping[str, str], key: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    if raw == "*":
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _bool(env: Mapping[str, str], key: str, default: bool) -> bool:
    raw = env.get(key, "").strip().lower()
    if not raw:
        return default
    return raw in TRUTHY


def load_config(env: Mapping[str, str] | None = None) -> Config:
    """Build a validated Config, defaulting to the process environment."""
    env = os.environ if env is None else env

    min_pct = _int(env, "MIN_DISCOUNT_PCT", 10)
    if not 1 <= min_pct <= 99:
        raise ConfigError(f"MIN_DISCOUNT_PCT must be between 1 and 99, got {min_pct}")

    poll = _int(env, "POLL_SECONDS", 60)
    if poll < MIN_POLL_SECONDS:
        raise ConfigError(
            f"POLL_SECONDS must be at least {MIN_POLL_SECONDS} to stay a polite client, got {poll}"
        )

    return Config(
        ntfy_topic=_require(env, "NTFY_TOPIC"),
        ntfy_server=env.get("NTFY_SERVER", "https://ntfy.sh").strip().rstrip("/"),
        min_discount_pct=min_pct,
        poll_seconds=poll,
        product_types=_csv(env, "PRODUCT_TYPES", ("Watches",)),
        watchlist=_csv(env, "WATCHLIST", ()),
        state_path=Path(env.get("STATE_PATH", "/data/state.json").strip()),
        heartbeat_path=Path(env.get("HEARTBEAT_PATH", "/tmp/heartbeat").strip()),
        log_level=env.get("LOG_LEVEL", "INFO").strip().upper() or "INFO",
    )
