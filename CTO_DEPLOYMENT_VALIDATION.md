# CTO Deployment Validation Report

Date: May 30, 2026

## Executive Summary

The deployment stack has been built and validated locally with Docker. The final
validated architecture is:

```text
nginx -> Node.js orchestrator -> FastAPI FASTSim engine -> Valhalla
```

The system is ready for droplet deployment once the runtime-only files are
provided on the server:

- `.env` with real Supabase values.
- `data/` app datasets.
- `custom_files/` Valhalla map/elevation bundle.

Secrets and large runtime files are intentionally excluded from Git.

## What Was Implemented

- Added a Node.js orchestrator service for the legacy PDF-compatible API:
  `POST /api/calculate-ev-route`.
- Kept existing FastAPI routes available through nginx under `/api/v1/*`.
- Added Supabase RPC charger lookup with local charger fallback.
- Added Docker Compose base stack for nginx, Node, and FastAPI.
- Added Valhalla override compose file for live routing.
- Normalized Valhalla Docker paths to `/custom_files/...`.
- Added health diagnostics that confirm the Python simulation runtime is
  `fastsim`.
- Added handoff documentation for local Docker, DigitalOcean, Supabase, and
  Valhalla.
- Added repo-safe Valhalla helper scripts under `valhalla/project/`.

## Local Docker Validation

Docker Desktop is installed locally with Docker/WSL data rooted on:

```text
D:\DockerDesktopWSL
```

The Docker CLI path used during validation was:

```text
D:\DockerDesktop\resources\bin
```

Validated containers:

```text
ev_nginx_ingress
ev_node_orchestrator
ev_fastsim_api
ev_valhalla_geometry
```

Container status output:

```text
NAME                   IMAGE                              SERVICE        STATUS
ev_fastsim_api         fastsim-fastsim-3-fastsim          fastsim        Up, healthy
ev_nginx_ingress       nginx:1.27-alpine                  nginx          Up, port 80
ev_node_orchestrator   fastsim-fastsim-3-orchestrator     orchestrator   Up, healthy
ev_valhalla_geometry   ghcr.io/valhalla/valhalla:latest   valhalla       Up
```

## Health Output

Command:

```bash
curl http://localhost/health
```

Output:

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

This confirms:

- nginx is reaching the Node orchestrator.
- Node is reaching FastAPI.
- FastAPI is using the real FASTSim runtime.
- Node can reach the Valhalla container.

## Test Results

Python tests:

```text
51 passed
```

Node tests:

```text
7 passed
```

Docker base smoke checks:

```text
ok: /health
ok: runtime diagnostics, simulation_engine=fastsim
ok: PluginAny worst-case depletion
ok: Delhi route completed
ok: confidence endpoint loaded
all smoke checks passed
```

Live Valhalla smoke check:

```text
ok: /health
ok: runtime diagnostics, simulation_engine=fastsim
ok: PluginAny worst-case depletion
ok: Delhi route completed, final_soc=0.780375
ok: confidence endpoint loaded, results=1
ok: live Valhalla route generated, edges=112
ok: live charger recommendations generated, chargers=3
ok: live multi-stop plan generated, status=destination_reached
all smoke checks passed
```

Legacy endpoint check:

```text
HTTP_STATUS:200
STATUS:success
SIMULATION_STATUS:route_completed
FINAL_SOC:0.757488
ROUTE_EDGES:112
CHARGER_SOURCE:local_fallback_no_depletion
```

## Valhalla Structure Validation

The local Valhalla handoff was found in this shape:

```text
valhalla/
  custom_files/
    NewDelhi.osm.pbf
    valhalla.json
    valhalla_tiles/
    elevation_tiles/
  data/
    new_delhi_chargers.json
  project/
    route.py
    EV_route.py
```

The structure is valid after copying `valhalla/custom_files/` to root
`custom_files/` and overwriting `custom_files/valhalla.json` with the normalized
repo `valhalla.json`.

Important note: the raw handoff config may contain Windows paths such as
`C:/valhalla/custom_files/...`. Docker requires `/custom_files/...` paths.

The Valhalla container logged warnings about missing optional tar extracts:

```text
/custom_files/valhalla_tiles.tar No such file or directory
/custom_files/traffic.tar No such file or directory
```

Those warnings did not block validation because the extracted
`valhalla_tiles/` directory was present and live routing succeeded.

## How It Ran

The validated Valhalla-enabled local run used:

```powershell
$env:Path = "D:\DockerDesktop\resources\bin;$env:Path"
Copy-Item -Path valhalla\custom_files\* -Destination custom_files -Recurse -Force
Copy-Item -Path valhalla.json -Destination custom_files\valhalla.json -Force
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
curl http://localhost/health
python scripts\production_smoke.py --base-url http://localhost --route-edges data\route_edges.json --live-valhalla
```

The first nginx health call after switching from the base stack to the Valhalla
stack returned a temporary `502` because nginx had a stale upstream container IP.
Restarting nginx resolved it:

```powershell
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml restart nginx
```

The documented production flow avoids this by running:

```bash
docker compose down
docker compose -f docker-compose.yml -f docker-compose.valhalla.yml up -d --build
```

## Deployment Readiness

Ready for handoff:

- Source and Docker stack are pushed to `deployment-backup/main`.
- Local Docker build works.
- Base stack works.
- Valhalla-enabled stack works.
- Legacy endpoint works through nginx.
- Supabase secrets remain out of Git.

Pending for production droplet:

- Provision DigitalOcean droplet.
- Add `.env` with real Supabase values.
- Copy `data/` runtime files.
- Copy `custom_files/` Valhalla runtime files.
- Run the documented droplet verification commands.
