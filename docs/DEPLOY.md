# Deploying on a VM

Builds from source on the target host. The VM needs outbound internet, Docker, git,
and read access to this private repository.

## 1. Prerequisites

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y git curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# RHEL / Fedora / Rocky
sudo dnf install -y git curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
```

Log out and back in so the `docker` group applies. Verify:

```bash
docker run --rm hello-world
docker compose version          # must be v2; "docker-compose" v1 is not supported
```

## 2. Give the VM read access to the repository

Pick one. The deploy key needs no extra tooling and is read-only, so it is the
better choice for a machine that only ever pulls.

### Option A - deploy key (git only, read-only)

On the VM:

```bash
ssh-keygen -t ed25519 -C "casio-price-alerts deploy" -f ~/.ssh/casio_deploy -N ""
cat ~/.ssh/casio_deploy.pub
```

Add that public key at
`https://github.com/mc-akash/casio-price-alerts/settings/keys` as a deploy key.
Leave "Allow write access" unchecked.

Then on the VM:

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
```

The `github-casio` alias keeps this key from colliding with any other GitHub
identity already on the machine.

### Option B - GitHub CLI device flow (works headless)

```bash
gh auth login          # choose GitHub.com, HTTPS, "Login with a web browser"
```

It prints a one-time code. Open the URL on any machine with a browser and enter it -
no browser needed on the VM itself. Then:

```bash
gh repo clone mc-akash/casio-price-alerts
```

## 3. Configure

```bash
cd casio-price-alerts
cp .env.example .env
```

Edit `.env` and set `NTFY_TOPIC` to your real topic. Without it the container exits
with code 2 on a configuration error. The file is gitignored and holds the only
secret in the system: anyone who knows the topic can read and publish your alerts.

## 4. Build and run

```bash
docker compose up -d --build
docker compose logs -f
```

Within about 15 seconds you should see:

```
startup ping delivered
polling https://casiostore.bhawar.com/collections/watches every 60s at >=10% off
scanned 2 page(s), 2 deal(s) at >=10%
```

The startup ping is a silent `Priority: min` notification. If it does not arrive,
the VM cannot reach ntfy and the container will exit rather than poll uselessly.

## 5. Verify

```bash
docker compose ps        # STATUS should read (healthy) after ~90s
```

`restart: unless-stopped` means the watcher returns automatically after a VM reboot.

Healthy operation is silent: unchanged polls log at DEBUG, so nothing is printed
between alerts. Judge liveness from `(healthy)`, not from log activity.

## Updating

```bash
git pull
docker compose up -d --build
```

State lives in the `state` named volume and survives rebuilds, so already-announced
deals are not re-announced.

## Operating

```bash
docker compose restart
docker compose down             # stop, keep state
docker compose down -v          # stop, wipe state; next start re-announces everything
docker compose logs --tail 50
```

## Troubleshooting

| Symptom | Cause |
|---|---|
| exits with code 2 | `NTFY_TOPIC` missing from `.env` |
| exits with code 1 at startup | cannot reach ntfy.sh - check egress and any proxy |
| `permission denied ... docker.sock` | not in the `docker` group, or the login session predates `usermod` |
| container healthy, no alerts | nothing is currently discounted - expected, verify with the startup ping |
| repeated alerts after restart | state volume was removed (`down -v`) |
