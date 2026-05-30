# Complete 0-To-100 Deployment Runbook

This file is the final deployment playbook for the EV routing platform. It is
written so a CTO, deployment engineer, or another Codex session can take the repo
from GitHub and deploy it on a DigitalOcean Droplet with Docker.

The final production shape is:

```text
Public HTTP :80
  -> nginx ingress container
  -> Node.js legacy orchestrator
  -> FastAPI FASTSim engine
  -> optional/live Valhalla routing container
  -> optional Supabase charger RPC
```

The repo already contains the source code, Dockerfiles, compose files, nginx
config, tests, deployment docs, Valhalla helper scripts, and validation reports.
The remaining production work is providing server access, secrets, and runtime
data files.

## Current Deployment Status

Completed locally:

- Docker Desktop was installed and validated.
- FastAPI/FASTSim Docker image builds.
- Node orchestrator Docker image builds.
- Base Docker stack runs through nginx.
- Valhalla-enabled Docker stack runs through nginx.
- Python tests passed.
- Node tests passed.
- Docker smoke tests passed.
- Live Valhalla smoke test passed.
- Legacy endpoint returned HTTP `200`.
- GitHub target `deployment-backup/main` has been updated.

Validated output summary:

```text
/health:
  status: ok
  node: ok
  python: ok
  runtime: fastsim
  valhalla: reachable

live Valhalla smoke:
  route edges generated: 112
  charger recommendations generated: 3
  multi-stop status: destination_reached

legacy endpoint:
  HTTP status: 200
  response status: success
  simulation status: route_completed
  final_soc: 0.757488
  route_edges: 112
  charger_source: local_fallback_no_depletion
```

For the CTO-facing validation details, read:

```text
CTO_DEPLOYMENT_VALIDATION.md
```

For Valhalla-specific local structure notes, read:

```text
valhalla/README.md
```

## What The Deployer Or Codex Needs From The Team

Before starting production deployment, collect these exact inputs:

```text
1. DigitalOcean account access or a ready Droplet.
2. Droplet public IP address.
3. SSH username, usually root or a sudo user.
4. SSH private key path or password-based SSH method.
5. GitHub access to deployment-backup/main.
6. Supabase URL.
7. Supabase service/anon key approved for the RPC.
8. Confirmation that the RPC is named find_nearest_chargers.
9. Runtime data files for ./data.
10. Valhalla runtime files as custom_files.zip or a valhalla/custom_files folder.
11. Confirmation whether first launch is HTTP-only by IP, or if a domain/HTTPS is required later.
```

Do not ask for Supabase secrets in chat if avoidable. They should be entered
directly into `.env` on the server.

## GitHub Target

Use only this deployment repo:

```text
https://github.com/nishanthreddyr24-netizen/internship_fastsim_pcoe_reviewer_with_deployement.git
```

Branch:

```text
main
```

Remote name used locally:

```text
deployment-backup
```

## Runtime Files That Are Not In Git

These are intentionally excluded from GitHub:

```text
.env
data/
custom_files/
valhalla/custom_files/
valhalla/data/
Deployment-1.pdf
route_edges_charger_11.json
```

They are excluded because they are secrets, runtime data, or heavy generated map
artifacts.

## Required `data/` Files

On the droplet, these must exist under:

```text
/opt/ev_platform/data/
```

Required files:

```text
vehicles_enrichment_GLOBAL_20260517_0915.csv
india_ev_reviews.xlsx
normalized_new_delhi_chargers.csv
route_edges.json
route_edges_charger.json
```

Optional but useful for validation or handoff:

```text
new_delhi_chargers.json
route_edges_charger_11.json
```

The app reads those files inside containers at:

```text
/data/...
```

## Required Valhalla Files

Docker expects Valhalla runtime files under:

```text
/opt/ev_platform/custom_files/
```

Minimum validated structure:

```text
custom_files/
  valhalla.json
  valhalla_tiles/
  elevation_tiles/
```

The local handoff that was validated also contained:

```text
custom_files/
  NewDelhi.osm.pbf
  valhalla.json
  valhalla_tiles/
  elevation_tiles/
```

If available, these are also acceptable and can be present:

```text
custom_files/admins.sqlite
custom_files/timezones.sqlite
custom_files/valhalla_tiles.tar
custom_files/traffic.tar
```

During local validation, `valhalla_tiles.tar` and `traffic.tar` were missing and
Valhalla logged warnings, but routing still worked because the extracted
`valhalla_tiles/` directory existed.

The final `custom_files/valhalla.json` inside Docker must use paths like:

```text
/custom_files/valhalla_tiles
/custom_files/valhalla_tiles.tar
/custom_files/elevation_tiles
/custom_files/admins.sqlite
/custom_files/timezones.sqlite
```

It must not use Windows paths like:

```text
C:/valhalla/custom_files/valhalla_tiles
```

If the handoff arrives as `valhalla/custom_files/`, copy it into root
`custom_files/` and overwrite the config with the repo-normalized
`valhalla.json`.

Windows:

```powershell
mkdir custom_files
Copy-Item -Path valhalla\custom_files\* -Destination custom_files -Recurse -Force
Copy-Item -Path valhalla.json -Destination custom_files\valhalla.json -Force
```

Linux/Droplet:

```bash
mkdir -p custom_files
cp -a valhalla/custom_files/. custom_files/
cp valhalla.json custom_files/valhalla.json
```

## Supabase Requirements

Supabase is optional at runtime because the API falls back to local charger
recommendations. For production, configure it once the Supabase team provides
approved values.

Put these only in `.env`:

```text
SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_RPC_NAME=find_nearest_chargers
SUPABASE_SEARCH_RADIUS_METERS=25000
```

Expected RPC name:

```text
find_nearest_chargers
```

Expected RPC request payload:

```json
{
  "deplete_lat": 28.0,
  "deplete_lng": 77.0,
  "search_radius_meters": 25000
}
```

Behavior:

- If depletion occurs and Supabase is configured, Node calls Supabase first.
- If Supabase returns useful rows, response `charger_source` is `supabase`.
- If Supabase is blank, errors, or returns no useful rows, local charger fallback
  is returned.
- If no depletion occurs, local/destination-anchored recommendations can be used.

## DigitalOcean Droplet Recommendation

Recommended:

```text
Ubuntu LTS
16 GB RAM
4 vCPU or higher
80 GB disk or higher
```

Reason:

- Docker build uses Rust/Python compilation for FASTSim.
- Valhalla map tiles and elevation files are heavy.
- Running nginx, Node, FastAPI workers, and Valhalla on a tiny droplet can fail
  from memory pressure.

For first public deployment:

```text
HTTP only
Public droplet IP
Port 80
No domain
No HTTPS
```

HTTPS/domain can be added later after the IP deployment is confirmed.

## DigitalOcean UI Setup

In the DigitalOcean control panel:

1. Create a new Droplet.
2. Select Ubuntu LTS.
3. Select a plan with at least 16 GB RAM for reliable deployment.
4. Add an SSH key.
5. Choose the preferred datacenter region.
6. Enable backups only if the team wants automatic snapshots.
7. Create a DigitalOcean Cloud Firewall.
8. Allow inbound SSH:

   ```text
   TCP 22 from trusted IPs, or from all IPv4/IPv6 for first setup if necessary
   ```

9. Allow inbound HTTP:

   ```text
   TCP 80 from all IPv4/IPv6
   ```

10. Do not expose Node `3000`, FastAPI `8000`, or Valhalla `8002` publicly.

Docker publishes only nginx port `80` publicly.

## SSH Into The Droplet

From local machine:

```bash
ssh root@DROPLET_IP
```

If using a key:

```bash
ssh -i /path/to/private_key root@DROPLET_IP
```

If the deployment uses a non-root sudo user:

```bash
ssh -i /path/to/private_key USERNAME@DROPLET_IP
```

Then become root or use `sudo` for system steps.

## Fresh Droplet System Setup

Run on the droplet:

```bash
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl git unzip ufw nano
```

Install Docker Engine and Compose plugin using Docker's official apt repository:

```bash
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" \
  > /etc/apt/sources.list.d/docker.list

apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker
```

Verify Docker:

```bash
docker --version
docker compose version
docker run --rm hello-world
```

Firewall on the droplet:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw --force enable
ufw status verbose
```

Important: also configure the DigitalOcean Cloud Firewall in the control panel.
Docker can interact with Linux firewall rules, so the DigitalOcean Cloud Firewall
is the cleaner external boundary.

## Clone The Repo On The Droplet

Use `/opt/ev_platform` as the deployment directory:

```bash
mkdir -p /opt/ev_platform
cd /opt
rm -rf /opt/ev_platform
git clone https://github.com/nishanthreddyr24-netizen/internship_fastsim_pcoe_reviewer_with_deployement.git ev_platform
cd /opt/ev_platform
git checkout main
```

Confirm expected files exist:

```bash
test -f docker-compose.yml
test -f docker-compose.valhalla.yml
test -f Dockerfile
test -f nodejs-api/Dockerfile
test -f nginx/nginx.conf
test -f .env.example
```

## Prepare `.env`

Create the server-only `.env` file:

```bash
cp .env.example .env
nano .env
```

Minimum production values:

```text
HTTP_PORT=80
WEB_CONCURRENCY=2
GUNICORN_TIMEOUT=120
PYTHON_ENGINE_URL=http://fastsim:8000

VEHICLE_ENRICHMENT_PATH=/data/vehicles_enrichment_GLOBAL_20260517_0915.csv
INDIA_EV_REVIEWS_PATH=/data/india_ev_reviews.xlsx
NORMALIZED_CHARGERS_PATH=/data/normalized_new_delhi_chargers.csv
ROUTE_EDGES_PATH=/data/route_edges.json
CHARGER_ROUTE_EDGES_PATH=/data/route_edges_charger.json

VALHALLA_URL=http://valhalla:8002
VALHALLA_TIMEOUT_S=10.0
VALHALLA_HEALTH_TIMEOUT_MS=1000
VALHALLA_CONFIG_PATH=/custom_files/valhalla.json

SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_RPC_NAME=find_nearest_chargers
SUPABASE_SEARCH_RADIUS_METERS=25000
```

If Supabase values are not available yet, leave `SUPABASE_URL` and
`SUPABASE_KEY` blank. The API will use local charger fallback.

Never commit `.env`.

## Upload Runtime Data

Create runtime directories:

```bash
mkdir -p /opt/ev_platform/data
mkdir -p /opt/ev_platform/custom_files
```

Upload data from local machine to droplet.

Example using `scp`:

```bash
scp -i /path/to/private_key vehicles_enrichment_GLOBAL_20260517_0915.csv root@DROPLET_IP:/opt/ev_platform/data/
scp -i /path/to/private_key india_ev_reviews.xlsx root@DROPLET_IP:/opt/ev_platform/data/
scp -i /path/to/private_key normalized_new_delhi_chargers.csv root@DROPLET_IP:/opt/ev_platform/data/
scp -i /path/to/private_key route_edges.json root@DROPLET_IP:/opt/ev_platform/data/
scp -i /path/to/private_key route_edges_charger.json root@DROPLET_IP:/opt/ev_platform/data/
```

If data is packaged as `data.zip`:

```bash
scp -i /path/to/private_key data.zip root@DROPLET_IP:/opt/ev_platform/
ssh -i /path/to/private_key root@DROPLET_IP
cd /opt/ev_platform
unzip -o data.zip -d data
```

Confirm:

```bash
ls -lah data
test -f data/vehicles_enrichment_GLOBAL_20260517_0915.csv
test -f data/india_ev_reviews.xlsx
test -f data/normalized_new_delhi_chargers.csv
test -f data/route_edges.json
test -f data/route_edges_charger.json
```

## Upload Valhalla Files

If the Valhalla team provides `custom_files.zip`:

```bash
scp -i /path/to/private_key custom_files.zip root@DROPLET_IP:/opt/ev_platform/
ssh -i /path/to/private_key root@DROPLET_IP
cd /opt/ev_platform
rm -rf custom_files
mkdir -p custom_files
unzip -o custom_files.zip -d custom_files
```

If the zip creates an extra nested folder:

```bash
find custom_files -maxdepth 3 -type f -name valhalla.json -print
```

If the result is:

```text
custom_files/custom_files/valhalla.json
```

then fix it:

```bash
tmpdir="$(mktemp -d)"
cp -a custom_files/custom_files/. "$tmpdir/"
rm -rf custom_files
mkdir custom_files
cp -a "$tmpdir/." custom_files/
rm -rf "$tmpdir"
```

If the Valhalla team provides a `valhalla/` folder:

```bash
cp -a valhalla/custom_files/. custom_files/
```

Always overwrite the container config with the repo-normalized config:

```bash
cp valhalla.json custom_files/valhalla.json
```

Confirm required Valhalla paths:

```bash
test -f custom_files/valhalla.json
test -d custom_files/valhalla_tiles
test -d custom_files/elevation_tiles
grep -n "/custom_files" custom_files/valhalla.json
```

If `grep` shows `C:/valhalla`, the wrong config is being used. Run:

```bash
cp valhalla.json custom_files/valhalla.json
```

## Base Stack Deployment Without Valhalla

Use this when `custom_files/` is not ready yet or to validate FastAPI/Node/nginx
first.

```bash
cd /opt/ev_platform
docker compose up -d --build
docker compose ps
curl http://localhost/health
```

Expected:

```json
{
  "status": "ok",
  "checks": {
    "node": "ok",
    "python": "ok",
    "runtime": "fastsim",
    "valhalla": "unreachable"
  }
}
```

`valhalla` can be `unreachable` in the base stack. That is acceptable only before
live routing is required.

## Full Stack Deployment With Valhalla

Use this for the actual production deployment after `custom_files/` is ready.

```bash
cd /opt/ev_platform
docker compose down
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml ps
```

Expected containers:

```text
ev_nginx_ingress
ev_node_orchestrator
ev_fastsim_api
ev_valhalla_geometry
```

Expected health:

```bash
curl http://localhost/health
```

Expected:

```json
{
  "status": "ok",
  "checks": {
    "node": "ok",
    "python": "ok",
    "runtime": "fastsim",
    "valhalla": "reachable"
  }
}
```

If nginx returns `502` immediately after switching stacks, restart nginx:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml restart nginx
curl http://localhost/health
```

## Public Health Check

From another machine:

```bash
curl http://DROPLET_IP/health
```

Expected public response must match local health and show:

```text
status = ok
runtime = fastsim
valhalla = reachable
```

Deployment is not complete if:

```text
runtime = synthetic_fallback
```

unless the CTO explicitly accepts fallback physics mode.

## Production Smoke Tests

Install Python tooling on the droplet if needed:

```bash
apt-get install -y python3 python3-pip
```

Run:

```bash
cd /opt/ev_platform
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges_charger.json
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json --live-valhalla
```

Expected live Valhalla smoke output includes:

```text
ok: /health
ok: runtime diagnostics, simulation_engine=fastsim
ok: live Valhalla route generated
ok: live charger recommendations generated
ok: live multi-stop plan generated
all smoke checks passed
```

## Legacy Endpoint Test

Create a sample legacy payload:

```bash
cat > /tmp/legacy_route.json <<'JSON'
{
  "vehicle_id": "IN-2025-0007",
  "start_lat": 28.597861,
  "start_lon": 77.032485,
  "end_lat": 28.556,
  "end_lon": 77.1,
  "environment": {
    "ambient_temp_c": 25.0,
    "wind_speed_kph": 0.0,
    "wind_direction_deg": 0.0,
    "precipitation_mm": 0.0
  },
  "vehicle_state": {
    "starting_soc": 0.80,
    "protection_soc": 0.15,
    "state_of_health": 0.95,
    "hvac_power_kw": 0.0
  }
}
JSON
```

Test locally on the droplet:

```bash
curl -s -H "Content-Type: application/json" \
  -d @/tmp/legacy_route.json \
  http://localhost/api/calculate-ev-route
```

Test publicly:

```bash
curl -s -H "Content-Type: application/json" \
  -d @/tmp/legacy_route.json \
  http://DROPLET_IP/api/calculate-ev-route
```

Expected response shape:

```text
status
simulation
route_edges
chargers
charger_source
```

Expected values from local validation:

```text
status: success
simulation.status: route_completed
route_edges count: 112
charger_source: local_fallback_no_depletion
```

If Supabase is configured and a depletion case is tested, `charger_source` may be:

```text
supabase
```

## Supabase Validation

After Supabase values are added to `.env`:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=100 orchestrator
```

Test with a route that causes depletion. The legacy response should show one of:

```text
charger_source: supabase
charger_source: local_fallback_supabase_empty
charger_source: local_fallback_supabase_error
```

To force fallback temporarily, blank `SUPABASE_KEY` in `.env`, restart the stack,
and run the same request:

```bash
sed -i 's/^SUPABASE_KEY=.*/SUPABASE_KEY=/' .env
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d
```

The endpoint should still return a usable response using local fallback.

Restore the real key after the fallback test.

## Logs To Check

All services:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=200
```

Node orchestrator:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=200 orchestrator
```

FastAPI:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=200 fastsim
```

Valhalla:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=200 valhalla
```

nginx:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=200 nginx
```

Follow logs live:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs -f
```

## Troubleshooting

### `docker` command not found

Docker is not installed or the shell cannot find it.

Run:

```bash
docker --version
docker compose version
```

If missing, repeat the Docker install section.

### Docker build fails during FASTSim/Rust build

Likely causes:

- Droplet too small.
- Out of memory.
- Network interruption while fetching packages.

Check:

```bash
free -h
df -h
docker system df
```

Retry:

```bash
docker compose build --no-cache fastsim
```

If it still fails on a small droplet, resize the droplet.

### `/health` returns 502

Check containers:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml ps
```

Restart nginx if containers were recreated:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml restart nginx
```

Then:

```bash
curl http://localhost/health
```

### `valhalla` is unreachable

Check:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml ps
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=200 valhalla
test -f custom_files/valhalla.json
test -d custom_files/valhalla_tiles
test -d custom_files/elevation_tiles
grep -n "/custom_files" custom_files/valhalla.json
```

If the config contains `C:/valhalla`, fix:

```bash
cp valhalla.json custom_files/valhalla.json
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml restart valhalla
```

### Valhalla logs missing tar warnings

Warnings like these may be acceptable:

```text
/custom_files/valhalla_tiles.tar No such file or directory
/custom_files/traffic.tar No such file or directory
```

They are acceptable only if:

```text
custom_files/valhalla_tiles/
```

exists and live routing smoke passes.

### `runtime` is `synthetic_fallback`

This means the real FASTSim runtime did not load. Check FastAPI logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=300 fastsim
```

Deployment should not be accepted until either:

- `runtime` becomes `fastsim`, or
- CTO explicitly approves fallback mode.

### Supabase errors

Check `.env`:

```bash
grep SUPABASE .env
```

Check Node logs:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml logs --tail=200 orchestrator
```

Blank Supabase values are allowed for local fallback behavior.

### Port 80 already in use

Check:

```bash
ss -ltnp | grep ':80'
```

Either stop the conflicting service or change `.env`:

```text
HTTP_PORT=8080
```

Then:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d
curl http://localhost:8080/health
```

For public production, prefer freeing port `80`.

## Update Existing Deployment

When new code is pushed to GitHub:

```bash
cd /opt/ev_platform
git fetch deployment-backup main || git fetch origin main
git pull
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml ps
curl http://localhost/health
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json --live-valhalla
```

If nginx shows stale upstream behavior:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml restart nginx
```

## Rollback

Find recent commits:

```bash
git log --oneline -5
```

Checkout the last known good commit:

```bash
git checkout COMMIT_SHA
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
curl http://localhost/health
```

Return to main later:

```bash
git checkout main
git pull
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
```

## Backup Before Changes

Before major updates:

```bash
cd /opt
tar -czf ev_platform_runtime_backup_$(date +%Y%m%d_%H%M%S).tar.gz \
  ev_platform/.env \
  ev_platform/data \
  ev_platform/custom_files
```

Do not publish this backup. It may contain secrets and runtime data.

## Final Production Acceptance Checklist

Deployment is accepted only when all of these are true:

```text
[ ] Droplet is reachable by SSH.
[ ] DigitalOcean Cloud Firewall allows only 22 and 80 for first deployment.
[ ] Docker Engine is installed.
[ ] Docker Compose plugin is installed.
[ ] Repo is cloned at /opt/ev_platform.
[ ] .env exists on droplet and is not committed.
[ ] data/ contains required app datasets.
[ ] custom_files/ contains Valhalla tiles and elevation files.
[ ] custom_files/valhalla.json uses /custom_files paths.
[ ] docker compose full Valhalla stack starts.
[ ] nginx container is running.
[ ] Node orchestrator container is healthy.
[ ] FastAPI container is healthy.
[ ] Valhalla container is running.
[ ] curl http://localhost/health returns status ok.
[ ] curl http://DROPLET_IP/health returns status ok.
[ ] health runtime is fastsim.
[ ] health valhalla is reachable.
[ ] route_edges smoke test passes.
[ ] route_edges_charger smoke test passes.
[ ] live Valhalla smoke test passes.
[ ] legacy endpoint returns HTTP 200.
[ ] Supabase path is tested or explicitly marked pending.
[ ] Supabase fallback is tested.
```

## What To Tell The Next Codex Session

Paste this into the next Codex session if asking it to deploy:

```text
You are deploying the EV routing platform from deployment-backup/main.
Use /opt/ev_platform on the droplet.
Use Docker Compose.
First verify Docker and clone the repo.
Create .env from .env.example and insert Supabase values only on the server.
Upload data/ runtime files.
Upload Valhalla custom_files/ runtime files.
Overwrite custom_files/valhalla.json with repo valhalla.json so paths use /custom_files.
Run docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build.
Verify /health locally and publicly.
Run scripts/production_smoke.py with --live-valhalla.
Test POST /api/calculate-ev-route.
Do not commit .env, data/, custom_files/, valhalla/custom_files/, or valhalla/data/.
Report exact outputs from health, compose ps, smoke tests, and legacy endpoint.
```

Then provide that Codex session:

```text
DROPLET_IP=
SSH_USER=
SSH_KEY_PATH_OR_AUTH_METHOD=
SUPABASE_URL=
SUPABASE_KEY=
LOCATION_OF_DATA_FILES=
LOCATION_OF_CUSTOM_FILES_ZIP_OR_FOLDER=
```

## Source References

The Docker install flow follows Docker's official Ubuntu Engine installation
pattern:

```text
https://docs.docker.com/engine/install/ubuntu/
```

The droplet hardening and firewall guidance is aligned with DigitalOcean's
recommended Droplet setup and firewall documentation:

```text
https://docs.digitalocean.com/products/droplets/getting-started/recommended-droplet-setup/
https://docs.digitalocean.com/products/networking/firewalls/how-to/configure-rules/
```
