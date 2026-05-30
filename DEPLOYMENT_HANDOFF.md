# EV Routing Deployment Handoff

This repo is prepared for a legacy-compatible production deployment based on the
Deployment-1 API shape, while keeping the existing FastAPI FASTSim engine as the
source of simulation behavior.

## What Was Built

- Public stack: `nginx -> Node.js orchestrator -> FastAPI -> optional Valhalla`.
- Legacy endpoint: `POST /api/calculate-ev-route`.
- Existing FastAPI endpoints remain reachable through nginx under `/api/v1/*`.
- Health endpoint: `GET /health` checks Node and FastAPI, and reports Valhalla
  as optional. Missing Valhalla files will not make the base stack unhealthy.
- Charger lookup:
  - Node calls Supabase RPC first when a depletion coordinate exists.
  - If Supabase is not configured, errors, or returns no usable rows, the
    response falls back to the Python/local charger recommendations.
  - Supabase secrets are read from `.env` only and are not committed.
- Runtime diagnostics expose whether Python is using real FASTSim or fallback
  behavior through the FastAPI `/health` response.

## Local Docker Layout

Docker Desktop was installed locally with Docker's heavy WSL data on:

```powershell
D:\DockerDesktopWSL
```

The Docker CLI is available from:

```powershell
D:\DockerDesktop\resources\bin
```

For a new PowerShell session, use:

```powershell
$env:Path = "D:\DockerDesktop\resources\bin;$env:Path"
```

The base local stack can be built and started without Valhalla files:

```powershell
docker compose build
docker compose up -d
docker compose ps
curl http://localhost/health
```

## Testing On Nishanth's Local Docker

The base Docker stack has already been validated locally on Nishanth's Windows
machine. The local stack exposes nginx on port `80`, so the API can be tested at:

```text
http://localhost
```

From the same Windows machine, verify it with:

```powershell
$env:Path = "D:\DockerDesktop\resources\bin;$env:Path"
docker compose ps
curl http://localhost/health
python scripts\production_smoke.py --base-url http://localhost --route-edges data\route_edges.json
python scripts\production_smoke.py --base-url http://localhost --route-edges data\route_edges_charger.json
```

Expected base result:

- `nginx`, `orchestrator`, and `fastsim` are running.
- `/health` returns HTTP `200`.
- `runtime` is `fastsim`.
- `valhalla` may show `unreachable` until `custom_files/` is available.

To let another person test this local Docker stack from a different device on the
same Wi-Fi/LAN:

1. Keep Docker Desktop running.
2. Keep the compose stack running:

   ```powershell
   docker compose up -d
   ```

3. Find Nishanth's LAN IP:

   ```powershell
   ipconfig
   ```

   Use the IPv4 address for the active Wi-Fi/Ethernet adapter, for example
   `192.168.1.25`.

4. Allow inbound HTTP on Windows Firewall only for the private network:

   ```powershell
   New-NetFirewallRule `
     -DisplayName "EV Platform Local Docker HTTP" `
     -Direction Inbound `
     -Protocol TCP `
     -LocalPort 80 `
     -Action Allow `
     -Profile Private
   ```

5. The other person can test:

   ```bash
   curl http://NISHANTH_LAN_IP/health
   curl -X POST http://NISHANTH_LAN_IP/api/calculate-ev-route \
     -H "Content-Type: application/json" \
     -d @legacy_route.json
   ```

Only expose this on a trusted private network. Do not open the local Windows
machine directly to the public internet.

When local sharing is finished, the firewall rule can be removed:

```powershell
Remove-NetFirewallRule -DisplayName "EV Platform Local Docker HTTP"
```

## Building Docker On Another Device

The receiving team does not need to manually create a Dockerfile. The repo
already contains:

- Root `Dockerfile` for FastAPI/FASTSim.
- `nodejs-api/Dockerfile` for the Node orchestrator.
- `docker-compose.yml` for the base stack.
- `docker-compose.valhalla.yml` for the optional Valhalla container.
- `nginx/nginx.conf` for public HTTP routing.

They should clone the `deployment-backup/main` repo and build from the existing
files.

### Windows With Docker Desktop

Prerequisites:

- Windows 10/11 with WSL2 enabled.
- Docker Desktop installed and running.
- Git installed.
- Python installed only if they want to run smoke scripts outside Docker.

Commands:

```powershell
git clone https://github.com/nishanthreddyr24-netizen/internship_fastsim_pcoe_reviewer_with_deployement.git
cd internship_fastsim_pcoe_reviewer_with_deployement
copy .env.example .env
mkdir data
```

Copy the required app data files into `data\`, then run:

```powershell
docker compose build
docker compose up -d
docker compose ps
curl http://localhost/health
```

If port `80` is already used on their machine, edit `.env`:

```text
HTTP_PORT=8080
```

Then test with:

```powershell
docker compose up -d
curl http://localhost:8080/health
```

### macOS Or Linux

Prerequisites:

- Docker Engine or Docker Desktop.
- Docker Compose plugin.
- Git.
- Python 3 if running smoke scripts outside Docker.

Commands:

```bash
git clone https://github.com/nishanthreddyr24-netizen/internship_fastsim_pcoe_reviewer_with_deployement.git
cd internship_fastsim_pcoe_reviewer_with_deployement
cp .env.example .env
mkdir -p data
docker compose build
docker compose up -d
docker compose ps
curl http://localhost/health
```

If port `80` is already used:

```bash
sed -i 's/^HTTP_PORT=.*/HTTP_PORT=8080/' .env
docker compose up -d
curl http://localhost:8080/health
```

### Adding Valhalla On Their Device

After they receive `custom_files.zip`:

```bash
mkdir -p custom_files
unzip custom_files.zip -d custom_files
docker compose down
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
curl http://localhost/health
```

On Windows PowerShell:

```powershell
mkdir custom_files
Expand-Archive .\custom_files.zip -DestinationPath .\custom_files -Force
docker compose down
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
curl http://localhost/health
```

If the zip extracts into an extra nested folder, move the contents so this path
exists:

```text
custom_files/valhalla.json
```

not:

```text
custom_files/custom_files/valhalla.json
```

### Common Docker Troubleshooting

- Docker command not found: start Docker Desktop or install Docker Engine.
- Compose command not found: install the Docker Compose plugin or update Docker
  Desktop.
- Port `80` already in use: set `HTTP_PORT=8080` in `.env`.
- `fastsim` fails during build on a tiny machine: use a larger machine because
  the Rust/Python FASTSim build can be memory intensive.
- `/health` says Valhalla is `unreachable`: this is expected until
  `custom_files/` is present and the Valhalla override compose file is used.
- Supabase errors: keep `SUPABASE_URL` and `SUPABASE_KEY` blank for local
  fallback testing, or add real values only in `.env`.

## Files That Must Stay Out Of Git

These are runtime inputs or secrets and must not be committed:

- `.env`
- `data/`
- `custom_files/`
- `Deployment-1.pdf`
- `route_edges_charger_11.json`

Use `.env.example` as the template, then put real values in `.env` on each
machine or droplet.

## Required Runtime Data

Create this directory on the droplet:

```bash
sudo mkdir -p /opt/ev_platform/data
```

Copy the app datasets and route test files into:

```text
/opt/ev_platform/data/
```

The compose file mounts this directory into the containers at `/data`.

## Valhalla File Handoff

The Valhalla owner should upload `custom_files.zip` to the droplet and extract it
under:

```text
/opt/ev_platform/custom_files
```

After extraction, confirm these exist:

```text
/opt/ev_platform/custom_files/valhalla.json
/opt/ev_platform/custom_files/valhalla_tiles
```

or:

```text
/opt/ev_platform/custom_files/valhalla_tiles.tar
```

Also confirm:

```text
/opt/ev_platform/custom_files/elevation_tiles
/opt/ev_platform/custom_files/admins.sqlite
/opt/ev_platform/custom_files/timezones.sqlite
```

The Valhalla config paths must point inside the container, for example:

```text
/custom_files/valhalla_tiles
/custom_files/valhalla_tiles.tar
/custom_files/elevation_tiles
/custom_files/admins.sqlite
/custom_files/timezones.sqlite
```

Run the base stack first without Valhalla:

```bash
docker compose up -d --build
```

After `custom_files/` is present, start the Valhalla-enabled stack:

```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
```

## Supabase Handoff

The Supabase team should add real values only in `.env`:

```text
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_RPC_NAME=find_nearest_chargers
SUPABASE_SEARCH_RADIUS_METERS=25000
```

The expected RPC is:

```text
find_nearest_chargers
```

The Node orchestrator sends this payload:

```json
{
  "deplete_lat": 28.0,
  "deplete_lng": 77.0,
  "search_radius_meters": 25000
}
```

If Supabase is blank or fails, the API still returns local charger fallback data.

## DigitalOcean Droplet Setup

As of May 30, 2026, DigitalOcean Droplets should be treated as a paid server
cost. The public pricing page lists low-cost Droplets starting at a monthly paid
tier, not as a permanent free Droplet. Supabase does provide a Free plan that can
be enough for initial charger lookup testing, but production usage should watch
database size, egress, and inactivity limits.

Recommended production droplet:

- Ubuntu LTS
- 16 GB RAM
- 4 vCPU or higher
- 80 GB disk or higher

Valhalla map files and Docker builds are memory and disk heavy, so the cheapest
small droplet is not recommended for a reliable deployment.

Open only:

```text
22/tcp
80/tcp
```

Install system dependencies:

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git unzip ufw
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

Configure firewall:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw --force enable
sudo ufw status
```

Clone and prepare the app:

```bash
sudo mkdir -p /opt/ev_platform
sudo chown "$USER:$USER" /opt/ev_platform
git clone <deployment-backup-repo-url> /opt/ev_platform
cd /opt/ev_platform
cp .env.example .env
mkdir -p data custom_files
```

Edit `.env` on the droplet and add the Supabase values there. Do not commit
`.env`.

Start the base stack:

```bash
docker compose up -d --build
docker compose ps
curl http://localhost/health
```

When Valhalla files are uploaded and checked:

```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
docker compose ps
curl http://localhost/health
```

## Verification Commands

Base stack:

```bash
curl http://localhost/health
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges_charger.json
```

Valhalla-enabled live routing:

```bash
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json --live-valhalla
```

Legacy PDF-style endpoint:

```bash
curl -X POST http://localhost/api/calculate-ev-route \
  -H "Content-Type: application/json" \
  -d @legacy_route.json
```

Public droplet check from another machine:

```bash
curl http://DROPLET_IP/health
curl -X POST http://DROPLET_IP/api/calculate-ev-route \
  -H "Content-Type: application/json" \
  -d @legacy_route.json
```

## Expected Health Response

Without Valhalla files, the service should still return HTTP 200 when Node and
FastAPI are healthy. Valhalla may show `not_configured` or `unreachable`.

With Valhalla enabled, health should show the Valhalla service as reachable and
live routing smoke tests should pass.

## Final Push Rule

Push only to `deployment-backup/main` after:

- Python tests pass.
- Node tests pass.
- Docker build passes.
- Base health and smoke checks pass.
- Valhalla live routing is either verified or explicitly marked pending because
  `custom_files/` has not been provided yet.
