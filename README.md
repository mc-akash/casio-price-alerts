# Casio Price Alerts

Watches the Casio India store (`casiostore.bhawar.com`) and pushes a phone
notification within a minute of a watch being discounted.

The store runs unannounced sales, some of them short-lived, and offers no way to be
notified. This polls it every 60 seconds and alerts you through
[ntfy](https://ntfy.sh).

Standard library only — no runtime dependencies. Runs as a plain script, a systemd
service, a Docker container, or a Kubernetes pod.

## How it works

Reads Shopify's public `products.json` for the `watches` collection and compares each
available variant's `price` against its `compare_at_price`. The deepest discount
across a product's variants wins.

It deliberately does **not** scrape the store's own "30% Off Or More" filter. That
facet defines exactly one bucket, so it cannot express a lower threshold, and if the
underlying metafield were ever renamed the filtered page would silently return either
the entire catalogue or nothing at all — indistinguishable from "no sales this month".
Comparing prices directly fails loudly instead.

Each poll sends `If-None-Match` per page. An unchanged catalogue costs ~0 bytes, which
keeps a once-a-minute poll a polite neighbour. Every 30th cycle refetches
unconditionally so a newly added page cannot hide behind a `304`.

You are alerted when a deal first appears, again if it deepens by a point, and again
if an ended deal later returns. Undelivered notifications are withheld from state and
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
| `POLL_SECONDS` | `60` | minimum 30 |
| `COLLECTION` | `watches` | any collection handle on the store |
| `STATE_PATH` | `/data/state.json` | seen deals and per-page ETags |
| `SEED_SILENT` | `false` | suppress the first-run summary |
| `HEARTBEAT_PATH` | `/tmp/heartbeat` | liveness probe target |
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
