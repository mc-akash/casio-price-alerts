# Casio Deal Watch

Polls the Casio India store (`casiostore.bhawar.com`) every 60 seconds and pushes an
ntfy notification when a watch drops 10% or more.

## How it works

Reads Shopify's public `products.json` for the `watches` collection and compares each
available variant's `price` against its `compare_at_price`. Alerts once per deal,
again if the discount deepens, and again if an ended deal returns later.

Per-page `ETag` conditional requests mean an unchanged catalogue costs ~0 bytes.

## Run it locally

```bash
export NTFY_TOPIC=your-secret-topic
export STATE_PATH=./state.json
python3 -m casio_watch --once    # one poll, exit
python3 -m casio_watch --loop    # poll forever
```

Subscribe to the same topic in the ntfy app (Android/iOS/web) to receive alerts.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `NTFY_TOPIC` | required | ntfy topic; treat as a credential |
| `NTFY_SERVER` | `https://ntfy.sh` | swap for a self-hosted ntfy |
| `MIN_DISCOUNT_PCT` | `10` | alert threshold |
| `POLL_SECONDS` | `60` | minimum 30 |
| `COLLECTION` | `watches` | any collection handle on the store |
| `STATE_PATH` | `/data/state.json` | seen-deals and ETag store |
| `SEED_SILENT` | `false` | suppress the first-run summary |
| `HEARTBEAT_PATH` | `/tmp/heartbeat` | liveness probe target |
| `LOG_LEVEL` | `INFO` | |

Anyone who knows `NTFY_TOPIC` can read and publish your alerts. Keep it out of git.

## Tests

```bash
python3 -m pytest -m "not network"                 # offline suite
python3 -m pytest -m network                       # live endpoint contract checks
.venv/bin/python -m pytest -m "not network" --cov=casio_watch
```

## Run it in the background locally

```bash
cp .env.example .env                      # then edit in your topic
cp systemd/casio-price-alerts.service.example ~/.config/systemd/user/casio-price-alerts.service
# edit in your topic there too
systemctl --user daemon-reload
systemctl --user enable --now casio-price-alerts
journalctl --user -u casio-price-alerts -f
```

State lives in `~/.local/state/casio-price-alerts/`. Note this only polls while the machine
is awake and online — overnight flash sales are missed. Use the Kubernetes deployment
for genuine 24/7 coverage.

## Deploy

See `k8s/`. Single replica, `Recreate` strategy — a second replica would double-alert.

## Startup self-test

On start the watcher publishes a silent `Priority: min` ping to your topic before
entering the loop. This proves the real publish path works: a blocked notification
path is otherwise invisible, since polling keeps succeeding and nothing alerts until
a sale happens. The store is deliberately not probed — a fetch failure surfaces on
the first cycle anyway.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | poll completed (`--once`) |
| 1 | self-test or poll failed |
| 2 | configuration error |

## Design

`docs/superpowers/specs/2026-09-23-casio-price-alerts-design.md`
