# Legacy-Compatible EV Routing Deployment

This deployment keeps the tested FastAPI FASTSim service and adds the legacy-compatible public layer from `Deployment-1.pdf`.

```text
Internet
  -> nginx :80
  -> Node.js orchestrator :3000
  -> FastAPI simulation engine :8000
  -> Valhalla routing service :8002
```

The public API supports both:

```text
POST /api/calculate-ev-route   Legacy PDF contract
GET  /health                   Stack health and runtime engine mode
POST /api/v1/...               Pass-through to the existing FastAPI API
```

## Required Server Inputs

Use an Ubuntu LTS DigitalOcean droplet with at least 16 GB RAM recommended.

You need:

```text
1. SSH access to the droplet
2. Docker Engine and Docker Compose plugin
3. Port 80 open in ufw and any DigitalOcean cloud firewall
4. Runtime data files copied into ./data
5. custom_files.zip extracted into ./custom_files
6. Supabase URL/key if charger RPC lookup should run
```

Runtime data files:

```text
vehicles_enrichment_GLOBAL_20260517_0915.csv
india_ev_reviews.xlsx
normalized_new_delhi_chargers.csv
route_edges.json
route_edges_charger.json
valhalla.json
```

Valhalla files must be under:

```text
/opt/ev_platform/custom_files
```

The Valhalla config used by the container must resolve these paths:

```text
/custom_files/valhalla_tiles
/custom_files/valhalla_tiles.tar
/custom_files/elevation_tiles
/custom_files/admins.sqlite
/custom_files/timezones.sqlite
```

## Fresh Droplet Setup

```bash
ssh root@YOUR_DROPLET_IP
apt-get update
apt-get upgrade -y
apt-get install -y ca-certificates curl git unzip ufw
curl -fsSL https://get.docker.com | sh
docker --version
docker compose version
ufw allow OpenSSH
ufw allow 80/tcp
ufw --force enable
mkdir -p /opt/ev_platform
cd /opt/ev_platform
git clone https://github.com/nishanthreddyr24-netizen/internship_fastsim_pcoe_reviewer_with_deployement.git .
```

## Prepare Runtime Data

From `/opt/ev_platform`:

```bash
mkdir -p data custom_files
cp vehicles_enrichment_GLOBAL_20260517_0915.csv data/
cp india_ev_reviews.xlsx data/
cp normalized_new_delhi_chargers.csv data/
cp route_edges.json data/
cp route_edges_charger.json data/
cp valhalla.json data/
```

Upload `custom_files.zip` to `/opt/ev_platform`, then:

```bash
unzip -o custom_files.zip -d .
test -f custom_files/valhalla.json
test -d custom_files/elevation_tiles
```

If the zip extracts as `custom_files/custom_files/...`, move the inner contents up one level.

## Configure Environment

```bash
cp .env.example .env
nano .env
```

Minimum values:

```text
HTTP_PORT=80
WEB_CONCURRENCY=2
GUNICORN_TIMEOUT=120
PYTHON_ENGINE_URL=http://fastsim:8000
VALHALLA_URL=http://valhalla:8002
VALHALLA_TIMEOUT_S=10.0

VEHICLE_ENRICHMENT_PATH=/data/vehicles_enrichment_GLOBAL_20260517_0915.csv
INDIA_EV_REVIEWS_PATH=/data/india_ev_reviews.xlsx
NORMALIZED_CHARGERS_PATH=/data/normalized_new_delhi_chargers.csv
ROUTE_EDGES_PATH=/data/route_edges.json
CHARGER_ROUTE_EDGES_PATH=/data/route_edges_charger.json
VALHALLA_CONFIG_PATH=/custom_files/valhalla.json

SUPABASE_URL=
SUPABASE_KEY=
SUPABASE_RPC_NAME=find_nearest_chargers
SUPABASE_SEARCH_RADIUS_METERS=25000
```

When `SUPABASE_URL` or `SUPABASE_KEY` is blank, the Node orchestrator returns local CSV/review charger recommendations instead.

## Start The Stack

```bash
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
docker compose ps
```

Expected containers:

```text
ev_nginx_ingress
ev_node_orchestrator
ev_fastsim_api
ev_valhalla_geometry
```

Check logs:

```bash
docker compose logs -f orchestrator
docker compose logs -f fastsim
docker compose logs -f valhalla
```

## Verify

Health through nginx:

```bash
curl http://localhost/health
curl http://YOUR_DROPLET_IP/health
```

The response includes:

```text
checks.runtime = fastsim
```

or:

```text
checks.runtime = synthetic_fallback
```

Deployment is not complete until this value is reviewed and accepted.

Run smoke tests:

```bash
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges_charger.json
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json --live-valhalla
```

Legacy endpoint sample:

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
    "state_of_health": 1.0,
    "hvac_power_kw": 0.0
  }
}
JSON

curl -s -H "Content-Type: application/json" \
  -d @/tmp/legacy_route.json \
  http://localhost/api/calculate-ev-route
```

Expected legacy response shape:

```text
status
simulation
route_edges
chargers
charger_source
```

## Updating

```bash
cd /opt/ev_platform
git pull
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
docker compose ps
python3 scripts/production_smoke.py --base-url http://localhost --route-edges data/route_edges.json
```

## Troubleshooting

If `/health` fails:

```bash
docker compose ps
docker compose logs orchestrator
docker compose logs fastsim
docker compose logs valhalla
```

If live routing returns HTTP 502:

```bash
docker compose logs valhalla
docker compose exec fastsim python -c "from urllib.request import urlopen; print(urlopen('http://valhalla:8002/status', timeout=5).read())"
```

If charger lookup falls back unexpectedly, check:

```bash
docker compose logs orchestrator
grep SUPABASE .env
```
