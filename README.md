# Casio Price Alerts

Watches the Casio India store (`casiostore.bhawar.com`) and pushes a phone
notification within a few minutes of a watch being discounted.

The store runs unannounced sales, some of them short-lived, and offers no way to be
notified. This polls it every 5 minutes and alerts you through
[ntfy](https://ntfy.sh).

One runtime dependency, [`curl_cffi`](https://github.com/lexiforest/curl_cffi). Runs as
a plain script, a systemd service, a Docker container, or a Kubernetes pod.

## How it works

Reads Shopify's public whole-store `products.json` and watches for four things:

| Signal | Fires when |
|---|---|
| **restock** | a product named in `WATCHLIST` is available again |
| **silent sale** | a product the store tags `silent_sale_product` is available again |
| **discount** | `compare_at_price` exceeds `price` by at least the threshold |
| **price drop** | the price itself falls, even with no `compare_at_price` set |

At most one alert per product per cycle, urgent signals first. Sold-out products never
alert — the store leaves stale discounts, sometimes a ₹0 price, on things you cannot buy.

**It polls the whole store, not a collection.** Shopify drops out-of-stock products
from collection feeds entirely, and over 700 watches sit outside
`/collections/watches` regardless, so a collection feed can see neither restocks nor
every sale.

**Price drops are tracked separately from discounts** because the store runs sales
that never populate `compare_at_price`. A discount-only watcher cannot see those at
all.

It deliberately does **not** scrape the store's own "30% Off Or More" filter. That
facet defines exactly one bucket, so it cannot express a lower threshold, and if the
underlying metafield were ever renamed the filtered page would silently return either
the entire catalogue or nothing at all — indistinguishable from "no sales this month".

Each poll sends `If-None-Match` per page, spaced 2s apart. An unchanged catalogue
costs ~0 bytes, but every request still counts against Shopify's per-IP storefront
limit: a once-a-minute whole-store poll gets a server IP answered with `429` all day.
On a `429` the watcher honours `Retry-After` and backs off up to 30 minutes. Every
30th cycle refetches unconditionally so a newly added page cannot hide behind a `304`.

You are alerted when a deal first appears, again if it deepens by a point, and again
if an ended deal later returns — including a sold-out watch restocked at the same
discount. Undelivered notifications are withheld from state and
retried rather than lost.

## Quick start

```bash
export NTFY_TOPIC=pick-something-unguessable
docker compose up -d --build
docker compose logs -f
```

Subscribe to the same topic in the [ntfy app](https://ntfy.sh/app) to receive alerts.

On startup it publishes a silent `Priority: min` ping. That is the proof the publish
path works — a blocked notification path is otherwise invisible, since polling keeps
succeeding and nothing alerts until a sale happens. If the ping cannot be delivered
the process exits rather than polling uselessly.

> Your topic is a credential. Anyone who knows it can read your alerts and publish to
> your phone. Choose something unguessable and keep it out of version control — which
> is why it is supplied at runtime rather than written into `docker-compose.yaml`.

## Running it directly

```bash
python3 -m pip install -r requirements.txt
export NTFY_TOPIC=your-topic
export STATE_PATH=./state.json

python3 -m casio_watch --once    # one poll, then exit
python3 -m casio_watch --loop    # poll forever
```

`--once` is useful for cron, CI, or a quick check; it exits non-zero on failure.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `NTFY_TOPIC` | *required* | ntfy topic; treat as a credential |
| `NTFY_SERVER` | `https://ntfy.sh` | point at a self-hosted ntfy |
| `MIN_DISCOUNT_PCT` | `10` | alert threshold |
| `POLL_SECONDS` | `300` | minimum 30; below 300 risks `429`s from the store |
| `PRODUCT_TYPES` | `Watches` | comma-separated types to watch; `*` for everything |
| `WATCHLIST` | *(empty)* | exact product titles to alert on when back in stock |
| `STATE_PATH` | `/data/state.json` | last-seen prices, stock and per-page ETags |
| `HEARTBEAT_PATH` | `/tmp/heartbeat` | liveness probe target; holds when the next cycle is due |
| `LOG_LEVEL` | `INFO` | |

All of these except `NTFY_TOPIC` are set in `docker-compose.yaml`.

## Deploying on a server

```bash
git clone https://github.com/mc-akash/casio-price-alerts.git
cd casio-price-alerts

echo 'NTFY_TOPIC=your-topic' > .env    # gitignored; compose reads it automatically
docker compose up -d --build
```

`docker compose ps` should report `(healthy)` after about 90 seconds.
`restart: unless-stopped` brings it back after a reboot. Update with
`git pull && docker compose up -d --build` — the `state` volume survives rebuilds, so
nothing is re-announced.

Also included: `systemd/` for a plain user service, and `k8s/` for a single-replica
Deployment. Use one replica only; two would double every alert.

## Operating

```bash
docker compose ps
docker compose logs --tail 50
docker compose down          # stop, keep state
docker compose down -v       # stop and wipe state; next start re-announces everything
```

**Silence is correct.** Unchanged polls log at `DEBUG`, so a healthy watcher prints
nothing between alerts. Judge liveness from `(healthy)`, not log activity.

| Symptom | Cause |
|---|---|
| exits code 2 | `NTFY_TOPIC` unset |
| exits code 1 at startup | cannot reach ntfy — check egress or proxy |
| `permission denied ... docker.sock` | not in the `docker` group, or the login session predates `usermod` |
| healthy but no alerts | nothing is discounted — normal |
| repeat alerts after restart | state volume was removed |
| `HTTP 429` warnings | store rate limit; raise `POLL_SECONDS` — the watcher backs off on its own and pushes one "Store is rate-limiting the watcher" warning per outage |
| `HTTP 429` from the first request, every time | the edge is rejecting the client's TLS fingerprint, not the rate — see below |

### Why not urllib

From a datacenter IP, Shopify's edge rejects Python's urllib with `429` on the very
first request — any headers, any rate, even after an hour of silence. Current curl
builds fare no better. It judges the TLS handshake, not the request, so the store is
fetched through `curl_cffi` impersonating Chrome (`casio_watch/browser.py`). ntfy is
still reached with urllib. From a home connection urllib works, which is why this
only shows up once deployed.

## Tests

```bash
python3 -m pytest -m "not network"     # offline suite
python3 -m pytest -m network           # live contract checks against the real store
```

The live tests assert the store still serves `products.json`, still exposes
`compare_at_price`, and still honours `If-None-Match` — the three assumptions the
watcher is built on.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | poll completed (`--once`) |
| 1 | self-test or poll failed |
| 2 | configuration error |
