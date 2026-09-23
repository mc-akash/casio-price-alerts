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

## Run it with Docker

```bash
cp .env.example .env          # then edit in your topic
docker compose up -d --build
docker compose logs -f
```

State persists in the `state` named volume, so restarts do not re-announce deals
already seen. A healthcheck restarts the container if no poll completes in 5 minutes.

```bash
docker compose ps             # health status
docker compose down           # stop, keeping state
docker compose down -v        # stop and wipe state (next start re-announces)
```

If Docker reports `permission denied ... /var/run/docker.sock`, add yourself to the
docker group and start a new login session:

```bash
sudo usermod -aG docker $USER
```

## Deploy a pre-built image (no source checkout)

Export the image on a machine that can build it:

```bash
docker build -t casio-price-alerts:1.0.0 .
docker save casio-price-alerts:1.0.0 | gzip -9 > casio-price-alerts-1.0.0.tar.gz
```

Copy the tarball, `docker-compose.prod.yaml` and your `.env` to the target host, then:

```bash
docker load < casio-price-alerts-1.0.0.tar.gz
docker compose -f docker-compose.prod.yaml up -d
docker compose -f docker-compose.prod.yaml logs -f
```

The image is architecture-specific. One built on x86_64 will not run on an arm64
host; rebuild there, or use `docker buildx build --platform` to produce both.

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

## Deploying on a VM

Builds from source on the target host. Needs Docker, git, outbound internet, and
read access to this private repo.

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER      # then log out and back in
```

Give the VM read-only access with a deploy key:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/casio_deploy -N ""
cat ~/.ssh/casio_deploy.pub        # add under repo Settings > Deploy keys
```

```bash
cat >> ~/.ssh/config <<'EOF'
Host github-casio
  HostName github.com
  User git
  IdentityFile ~/.ssh/casio_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

git clone git@github-casio:mc-akash/casio-price-alerts.git
cd casio-price-alerts
cp .env.example .env               # set NTFY_TOPIC
docker compose up -d --build
docker compose logs -f
```

`docker compose ps` should read `(healthy)` after ~90s. Update with
`git pull && docker compose up -d --build`; the state volume survives rebuilds.

| Symptom | Cause |
|---|---|
| exits code 2 | `NTFY_TOPIC` missing from `.env` |
| exits code 1 at startup | cannot reach ntfy.sh — check egress or proxy |
| `permission denied ... docker.sock` | not in `docker` group, or login session predates `usermod` |
| healthy but silent | nothing discounted — normal; unchanged polls log at DEBUG |
| repeat alerts after restart | state volume was removed (`down -v`) |
