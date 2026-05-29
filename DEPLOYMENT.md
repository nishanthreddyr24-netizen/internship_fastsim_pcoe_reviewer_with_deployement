# EV Routing Deployment Guide

This repository deploys the existing FastAPI EV routing physics service. It keeps the working FASTSim pipeline intact and adds a production wrapper around it: Docker, nginx, mounted runtime data, health checks, and smoke tests.

The v1 production deployment does **not** require a live Valhalla server. It uses pre-generated Valhalla route output such as `route_edges.json`. A later production routing upgrade can add a Valhalla container to dynamically generate `route_edges` from start/end coordinates.

## What This Deployment Runs

The production stack is:

```text
Internet / browser / app client
  -> nginx on port 80
  -> FastAPI app on internal port 8000
  -> FASTSim physics simulation or synthetic fallback
  -> local vehicle + charger review datasets
```

Exposed endpoints:

```text
GET  /health
POST /api/v1/physics/simulate
POST /api/v1/routing/simulate
GET  /api/v1/confidence/stations/{station_id}
GET  /api/v1/confidence/nearby
POST /api/v1/confidence/rank
```

Important files:

```text
Dockerfile                 Builds the FastAPI service image
docker-compose.yml         Runs FastAPI and nginx together
docker-compose.valhalla.yml Optional Valhalla routing service override
nginx/nginx.conf           Reverse proxy, gzip, rate limiting, security headers
.env.example               Runtime settings template
requirements.txt           Python production dependencies
scripts/production_smoke.py Deployment smoke test
DEPLOYMENT.md              This guide
```

## What The Person Deploying Needs

You need:

```text
1. A Linux server, recommended Ubuntu 22.04 or 24.04 LTS
2. At least 16 GB RAM for this v1 FastAPI deployment
3. SSH access to the server
4. Docker Engine
5. Docker Compose plugin
6. Git, or a copied zip/tar of this repository
7. Port 80 open in the server firewall
8. The runtime data files included in this repo or copied into ./data
```

Recommended DigitalOcean droplet:

```text
OS: Ubuntu LTS
RAM: 16 GB
CPU: 4 vCPU or better
Disk: 80 GB or better
Inbound firewall: SSH 22, HTTP 80
```

Required runtime data:

```text
vehicles_enrichment_GLOBAL_20260517_0915.csv
india_ev_reviews.xlsx
normalized_new_delhi_chargers.csv
route_edges.json
route_edges_charger.json
valhalla.json
```

For v1, `valhalla.json` is kept as an artifact/reference file. The API simulation uses `route_edges.json` directly.

## Fresh Droplet Setup

SSH into the droplet:

```bash
ssh root@YOUR_DROPLET_IP
```

Update packages:

```bash
apt-get update
apt-get upgrade -y
```

Install basic tools:

```bash
apt-get install -y ca-certificates curl git ufw
```

Install Docker:

```bash
curl -fsSL https://get.docker.com | sh
```

Verify Docker:

```bash
docker --version
docker compose version
```

Configure firewall:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw --force enable
ufw status
```

Create deployment folder:

```bash
mkdir -p /opt/ev_platform
cd /opt/ev_platform
```

## Get The Code Onto The Droplet

Clone the deployment backup repo:

```bash
git clone https://github.com/nishanthreddyr24-netizen/internship_fastsim_pcoe_reviewer_with_deployement.git .
```

If the folder is not empty, use:

```bash
git clone https://github.com/nishanthreddyr24-netizen/internship_fastsim_pcoe_reviewer_with_deployement.git app
cd app
```

## Prepare Runtime Data

From the repository root on the droplet:

```bash
mkdir -p data
cp vehicles_enrichment_GLOBAL_20260517_0915.csv data/
cp india_ev_reviews.xlsx data/
cp normalized_new_delhi_chargers.csv data/
cp route_edges.json data/
cp route_edges_charger.json data/
cp valhalla.json data/
```

The Docker Compose file mounts `./data` read-only into the container at `/data`.

The app reads:

```text
/data/vehicles_enrichment_GLOBAL_20260517_0915.csv
/data/india_ev_reviews.xlsx
```

## Configure Environment

Create `.env` from the example:

```bash
cp .env.example .env
```

Default `.env` values are enough for the first deployment:

```text
HTTP_PORT=80
WEB_CONCURRENCY=2
GUNICORN_TIMEOUT=120
VEHICLE_ENRICHMENT_PATH=/data/vehicles_enrichment_GLOBAL_20260517_0915.csv
INDIA_EV_REVIEWS_PATH=/data/india_ev_reviews.xlsx
NORMALIZED_CHARGERS_PATH=/data/normalized_new_delhi_chargers.csv
ROUTE_EDGES_PATH=/data/route_edges.json
CHARGER_ROUTE_EDGES_PATH=/data/route_edges_charger.json
VALHALLA_CONFIG_PATH=/data/valhalla.json
```

For a 16 GB droplet, start with:

```text
WEB_CONCURRENCY=2
```

Increase to `3` or `4` only after checking CPU and memory usage.

## Build And Start

Run:

```bash
docker compose up -d --build
```

Check containers:

```bash
docker compose ps
```

Expected containers:

```text
ev_fastsim_api       Up / healthy
ev_nginx_ingress     Up
```

Check logs:

```bash
docker compose logs -f fastapi
docker compose logs -f nginx
```

## Verify Health

From the droplet:

```bash
curl http://localhost/health
```

Expected:

```json
{"status":"ok"}
```

From your laptop:

```bash
curl http://YOUR_DROPLET_IP/health
```

Expected:

```json
{"status":"ok"}
```

## Run Production Smoke Tests

Install Python on the droplet if needed:

```bash
apt-get install -y python3
```

Run the smoke test:

```bash
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json
```

Expected output:

```text
ok: /health
ok: PluginAny worst-case depletion
ok: Delhi route completed
ok: confidence endpoint loaded
all smoke checks passed
```

To validate the longer charger route fixture instead of the shorter demo route:

```bash
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges_charger.json
```

This fixture contains 223 Valhalla edges, about 26.57 km of route distance, and is useful for proving that a realistic charger-route JSON can flow through the same FASTSim endpoint.

This validates:

```text
1. nginx can reach FastAPI
2. /health works
3. PluginAny worst-case payload returns depletion_triggered
4. Delhi route_edges.json works through the simulation endpoint
5. confidence service can load the review workbook
```

## How To Test The Simulation Manually

Create a quick request:

```bash
cat > /tmp/sim_payload.json <<'JSON'
{
  "vehicle_id": "IN-2025-0007",
  "environment": {
    "ambient_temp_c": 25.0
  },
  "vehicle_state": {
    "starting_soc": 0.80,
    "protection_soc": 0.15
  },
  "route_edges": [
    {
      "edge_index": 0,
      "distance_m": 1200.0,
      "speed_kph": 40.0,
      "grade_pct": 0.5,
      "heading_deg": 180.0,
      "start_coordinate": {"lat": 28.57, "lon": 77.05},
      "end_coordinate": {"lat": 28.58, "lon": 77.06}
    }
  ]
}
JSON
```

Send it:

```bash
curl -s \
  -H "Content-Type: application/json" \
  -d @/tmp/sim_payload.json \
  http://localhost/api/v1/physics/simulate
```

You should receive fields like:

```text
status
final_soc
route_duration_s
route_distance_m
soc_timeline
vehicle
battery_correction
```

## Updating The Deployment

When code changes are pushed to GitHub:

```bash
cd /opt/ev_platform
git pull
docker compose up -d --build
docker compose ps
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json
```

If only `.env` changed:

```bash
docker compose up -d
```

If only data changed:

```bash
cp NEW_FILE data/
docker compose restart fastapi
```

## Stopping Or Restarting

Restart:

```bash
docker compose restart
```

Stop:

```bash
docker compose down
```

Stop and rebuild:

```bash
docker compose down
docker compose up -d --build
```

## Logs And Debugging

FastAPI logs:

```bash
docker compose logs -f fastapi
```

nginx logs:

```bash
docker compose logs -f nginx
```

Container shell:

```bash
docker compose exec fastapi sh
```

Check mounted data inside container:

```bash
docker compose exec fastapi ls -lh /data
```

Check app health from inside the Docker network:

```bash
docker compose exec fastapi python -c "from urllib.request import urlopen; print(urlopen('http://127.0.0.1:8000/health').read())"
```

## Common Problems

### `curl http://localhost/health` fails

Check:

```bash
docker compose ps
docker compose logs fastapi
docker compose logs nginx
```

Likely causes:

```text
1. Image build failed
2. App container is unhealthy
3. Port 80 already used by another service
4. .env has invalid HTTP_PORT
```

### App cannot find vehicle CSV

Check:

```bash
ls -lh data/vehicles_enrichment_GLOBAL_20260517_0915.csv
docker compose exec fastapi ls -lh /data
```

The `.env` path should be:

```text
VEHICLE_ENRICHMENT_PATH=/data/vehicles_enrichment_GLOBAL_20260517_0915.csv
```

### Confidence endpoint fails

Check:

```bash
ls -lh data/india_ev_reviews.xlsx
docker compose logs fastapi
```

The `.env` path should be:

```text
INDIA_EV_REVIEWS_PATH=/data/india_ev_reviews.xlsx
```

### Port 80 is blocked

Check firewall:

```bash
ufw status
```

Allow HTTP:

```bash
ufw allow 80/tcp
```

Check DigitalOcean cloud firewall too, if one is attached.

### Docker is not installed

Run:

```bash
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
```

## Live Valhalla Integration

The base deployment uses a pre-generated `route_edges.json`. That is good for testing and demos. Real production can now use the live endpoint:

```text
POST /api/v1/routing/simulate
```

The final charger recommendation endpoint is:

```text
POST /api/v1/routing/recommend
```

It returns one primary destination route, the FASTSim simulation, the charger search anchor, and ranked charger candidates. If `include_charger_routes` is true, each charger candidate can include a Valhalla-generated `route_to_charger_edges` array that frontend/map teams can draw as possible charging paths.

The multi-charging SOC-aware planner endpoint is:

```text
POST /api/v1/routing/plan
```

It repeatedly calls Valhalla and FASTSim. If the destination leg depletes, it searches chargers near the depletion coordinate, evaluates reachable charger legs, chooses the reachable charger with the lowest `p_fail`, estimates charge time to the target SOC, and repeats until the destination is reached or `max_charging_stops` is exhausted.

Live production flow:

```text
User selects origin and destination
  -> API calls Valhalla /route
  -> API calls Valhalla /trace_attributes
  -> API calls Valhalla /height or reads elevation data
  -> API converts Valhalla response into route_edges
  -> API calls the existing FASTSim simulation code
  -> API returns SOC, depletion point, and charger recommendations
```

The code for this is already present:

```text
app/routing/endpoints.py        FastAPI live routing endpoint
app/routing/valhalla_client.py  Valhalla HTTP client and route_edges adapter
app/routing/schemas.py          Request/response schemas
```

The live endpoint request looks like this:

```json
{
  "vehicle_id": "IN-2025-0007",
  "start": {"lat": 28.597861, "lon": 77.032485},
  "end": {"lat": 28.556, "lon": 77.1},
  "environment": {"ambient_temp_c": 25.0},
  "vehicle_state": {
    "starting_soc": 0.8,
    "protection_soc": 0.15
  }
}
```

The response includes both generated Valhalla edges and the existing FASTSim result:

```text
route_edges
simulation.status
simulation.final_soc
simulation.depletion_coordinate
simulation.soc_timeline
```

### What The Valhalla Person Must Provide

They must provide a compiled Valhalla graph folder on the droplet:

```text
/opt/ev_platform/data/valhalla/
  valhalla.json
  valhalla_tiles/
    0/
    1/
    2/
  admins.sqlite
  timezones.sqlite
  elevation_tiles/        optional but strongly recommended for real grade_pct
```

The `valhalla.json` inside this folder must point to container paths, not Windows paths:

```json
{
  "mjolnir": {
    "tile_dir": "/custom_files/valhalla_tiles",
    "tile_extract": "/custom_files/valhalla_tiles.tar",
    "admin": "/custom_files/admins.sqlite",
    "timezone": "/custom_files/timezones.sqlite"
  },
  "additional_data": {
    "elevation": "/custom_files/elevation_tiles"
  },
  "skadi": {
    "use_skadi": true
  }
}
```

### Start With Live Valhalla Enabled

Use the override compose file:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
```

Check containers:

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml ps
```

Expected:

```text
ev_fastsim_api
ev_nginx_ingress
ev_valhalla_geometry
```

Validate the normal API and live Valhalla route:

```bash
python3 scripts/production_smoke.py \
  --base-url http://localhost \
  --route-edges data/route_edges.json \
  --live-valhalla
```

Expected extra line:

```text
ok: live Valhalla route generated, edges=...
```

### Manual Live Valhalla Test

```bash
cat > /tmp/live_route_payload.json <<'JSON'
{
  "vehicle_id": "IN-2025-0007",
  "start": {"lat": 28.597861, "lon": 77.032485},
  "end": {"lat": 28.556, "lon": 77.1},
  "environment": {"ambient_temp_c": 25.0},
  "vehicle_state": {
    "starting_soc": 0.80,
    "protection_soc": 0.15
  }
}
JSON

curl -s \
  -H "Content-Type: application/json" \
  -d @/tmp/live_route_payload.json \
  http://localhost/api/v1/routing/simulate
```

To test route plus charger recommendations:

```bash
curl -s \
  -H "Content-Type: application/json" \
  -d @/tmp/live_route_payload.json \
  http://localhost/api/v1/routing/recommend
```

To test SOC-aware multi-charging planning:

```bash
cat > /tmp/live_plan_payload.json <<'JSON'
{
  "vehicle_id": "IN-2025-0007",
  "start": {"lat": 28.597861, "lon": 77.032485},
  "end": {"lat": 28.5434438, "lon": 77.2063442},
  "vehicle_state": {
    "starting_soc": 0.80,
    "protection_soc": 0.15
  },
  "target_soc_after_charge": 0.70,
  "max_charging_stops": 3,
  "charger_radius_km": 25,
  "charger_limit": 5,
  "fallback_charger_power_kw": 22,
  "include_leg_edges": true
}
JSON

curl -s \
  -H "Content-Type: application/json" \
  -d @/tmp/live_plan_payload.json \
  http://localhost/api/v1/routing/plan
```

The response shows:

```text
primary_route_edges        main route to the destination
simulation                 battery/SOC/depletion result
charger_search_anchor      depletion coordinate if depleted, otherwise destination
recommended_chargers       compatible chargers ranked by confidence, distance, and power
route_to_charger_edges     optional path from anchor to each charger
```

The planner response shows:

```text
status                         destination_reached, planning_failed, or max_stops_exceeded
plan_steps                     ordered drive and charge steps
chargers_considered            candidates evaluated for each failed leg
total_estimated_charge_minutes simple v1 charging-time estimate
```

If Valhalla is not reachable, this endpoint returns HTTP `502` with a Valhalla error message. The old direct JSON endpoint still works:

```text
POST /api/v1/physics/simulate
```

### Optional Compose Service

The Valhalla service is defined in `docker-compose.valhalla.yml`:

```yaml
valhalla:
  image: ghcr.io/valhalla/valhalla:latest
  container_name: ev_valhalla_geometry
  restart: unless-stopped
  expose:
    - "8002"
  volumes:
    - ./data/valhalla:/custom_files:ro
  command: valhalla_service /custom_files/valhalla.json 1
```

FastAPI calls:

```text
http://valhalla:8002/route
http://valhalla:8002/trace_attributes
http://valhalla:8002/height
```

`app/routing/valhalla_client.py` converts those live Valhalla responses into the existing `route_edges` schema.

For a 16 GB droplet:

```text
Delhi/NCR Valhalla graph: acceptable on the same droplet
Full India graph: build on a temporary 64 GB server, copy final tiles to production
```

Do not build the full India Valhalla graph on the 16 GB production droplet. Build it elsewhere, copy the compiled graph, then run only the service on production.

## Security Notes

For first deployment, HTTP on port 80 is enough to verify the service.

Before real public use:

```text
1. Put the API behind a domain
2. Add HTTPS using Cloudflare or certbot
3. Restrict SSH to your IP if possible
4. Keep .env out of git
5. Rotate any API keys placed in .env
6. Add monitoring for container health and disk usage
```

## Validation Command Summary

Run these after every deployment:

```bash
docker compose ps
curl http://localhost/health
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json
docker compose logs --tail=100 fastapi
```

If all pass, the deployment is ready for demo or staging use.
