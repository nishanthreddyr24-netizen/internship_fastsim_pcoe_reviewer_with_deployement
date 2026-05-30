# Valhalla Handoff Structure

This folder documents the Valhalla handoff layout used to validate live routing.

## Repo-Safe Files

The files committed under this folder are safe to keep in Git:

```text
valhalla/
  README.md
  project/
    route.py
    EV_route.py
```

`project/route.py` generates a direct `route_edges.json` file using the local
Python Valhalla binding.

`project/EV_route.py` generates a charger-stop `route_edges_charger.json` file
using the local Python Valhalla binding and a charger JSON file.

Both scripts now support repo-relative paths and optional CLI overrides.

## Runtime Files Kept Out Of Git

The large runtime map/data files are intentionally not committed:

```text
valhalla/custom_files/
valhalla/data/
custom_files/
data/
```

They are ignored because they are deployment artifacts and can be hundreds of MB.
They should be copied to the server or local machine during deployment.

## Docker Layout

Docker expects the live Valhalla files at the repo root:

```text
custom_files/valhalla.json
custom_files/valhalla_tiles/
custom_files/elevation_tiles/
```

If the handoff arrives as `valhalla/custom_files/`, copy it into the root
`custom_files/` directory and overwrite the config with the repo-normalized
`valhalla.json`:

```powershell
mkdir custom_files
Copy-Item -Path valhalla\custom_files\* -Destination custom_files -Recurse -Force
Copy-Item -Path valhalla.json -Destination custom_files\valhalla.json -Force
```

On Linux or the droplet:

```bash
mkdir -p custom_files
cp -a valhalla/custom_files/. custom_files/
cp valhalla.json custom_files/valhalla.json
```

The final `custom_files/valhalla.json` must use `/custom_files/...` paths inside
the container.

## Local Helper Script Examples

Direct route:

```powershell
python valhalla\project\route.py --output route_edges.json
```

Charger-stop route:

```powershell
python valhalla\project\EV_route.py --output route_edges_charger.json
```

Explicit paths:

```powershell
python valhalla\project\route.py `
  --config custom_files\valhalla.json `
  --output data\route_edges.json
```

These helper scripts are optional. The production deployment uses the Valhalla
Docker container through HTTP.
