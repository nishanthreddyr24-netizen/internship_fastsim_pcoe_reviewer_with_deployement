"""Production smoke checks for the deployed EV routing API."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def request_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} failed with HTTP {err.code}: {detail}") from err
    except URLError as err:
        raise RuntimeError(f"{method} {url} failed: {err}") from err


def load_route_edges(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    edges = payload.get("route_edges") or payload.get("edges")
    if not edges:
        raise RuntimeError(f"{path} does not contain route_edges")
    return edges


def assert_health(base_url: str) -> None:
    body = request_json("GET", f"{base_url}/health")
    if body.get("status") != "ok":
        raise RuntimeError(f"unexpected health response: {body}")
    print("ok: /health")


def assert_worst_case_depletion(base_url: str) -> None:
    payload = {
        "vehicle_id": "IN-2025-0007",
        "environment": {
            "ambient_temp_c": 2.0,
            "wind_speed_kph": 30.0,
            "precipitation_mm": 5.0,
        },
        "vehicle_state": {
            "starting_soc": 0.20,
            "protection_soc": 0.15,
            "hvac_power_kw": 4.0,
            "adjusted_rr_coef": 0.014,
        },
        "route_edges": [
            {
                "edge_index": 0,
                "distance_m": 5000.0,
                "speed_kph": 90.0,
                "grade_pct": 3.0,
                "heading_deg": 180.0,
                "wind_direction_deg": 360.0,
                "start_coordinate": {"lat": 28.57, "lon": 77.05},
                "end_coordinate": {"lat": 28.60, "lon": 77.08},
            },
        ],
    }
    body = request_json("POST", f"{base_url}/api/v1/physics/simulate", payload)
    if body.get("status") != "depletion_triggered":
        raise RuntimeError(f"worst-case payload did not deplete: {body}")
    print("ok: PluginAny worst-case depletion")


def assert_delhi_route(base_url: str, route_edges_path: Path) -> None:
    payload = {
        "vehicle_id": "IN-2025-0007",
        "environment": {"ambient_temp_c": 25.0},
        "vehicle_state": {"starting_soc": 0.80, "protection_soc": 0.15},
        "route_edges": load_route_edges(route_edges_path),
    }
    body = request_json("POST", f"{base_url}/api/v1/physics/simulate", payload)
    if body.get("status") != "route_completed":
        raise RuntimeError(f"Delhi route did not complete: {body}")
    print(f"ok: Delhi route completed, final_soc={body.get('final_soc')}")


def assert_confidence_loads(base_url: str) -> None:
    query = urlencode({"lat": 28.57, "lon": 77.05, "radius_km": 100, "limit": 1})
    body = request_json("GET", f"{base_url}/api/v1/confidence/nearby?{query}")
    if "results" not in body:
        raise RuntimeError(f"confidence endpoint returned unexpected payload: {body}")
    print(f"ok: confidence endpoint loaded, results={len(body['results'])}")


def assert_live_valhalla_route(base_url: str) -> None:
    payload = {
        "vehicle_id": "IN-2025-0007",
        "start": {"lat": 28.597861, "lon": 77.032485},
        "end": {"lat": 28.556, "lon": 77.1},
        "environment": {"ambient_temp_c": 25.0},
        "vehicle_state": {"starting_soc": 0.80, "protection_soc": 0.15},
    }
    body = request_json("POST", f"{base_url}/api/v1/routing/simulate", payload)
    if "route_edges" not in body or "simulation" not in body:
        raise RuntimeError(f"live routing returned unexpected payload: {body}")
    if body["simulation"].get("status") not in {"route_completed", "depletion_triggered"}:
        raise RuntimeError(f"live routing simulation returned unexpected status: {body}")
    print(f"ok: live Valhalla route generated, edges={len(body['route_edges'])}")


def assert_live_recommendations(base_url: str) -> None:
    payload = {
        "vehicle_id": "IN-2025-0007",
        "start": {"lat": 28.597861, "lon": 77.032485},
        "end": {"lat": 28.556, "lon": 77.1},
        "environment": {"ambient_temp_c": 25.0},
        "vehicle_state": {"starting_soc": 0.80, "protection_soc": 0.15},
        "charger_limit": 3,
        "include_charger_routes": True,
    }
    body = request_json("POST", f"{base_url}/api/v1/routing/recommend", payload)
    required = {"primary_route_edges", "simulation", "charger_search_anchor", "recommended_chargers"}
    if not required <= set(body):
        raise RuntimeError(f"live recommendations returned unexpected payload: {body}")
    print(f"ok: live charger recommendations generated, chargers={len(body['recommended_chargers'])}")


def assert_live_multi_stop_plan(base_url: str) -> None:
    payload = {
        "vehicle_id": "IN-2025-0007",
        "start": {"lat": 28.597861, "lon": 77.032485},
        "end": {"lat": 28.5434438, "lon": 77.2063442},
        "environment": {"ambient_temp_c": 25.0},
        "vehicle_state": {"starting_soc": 0.80, "protection_soc": 0.15},
        "target_soc_after_charge": 0.70,
        "max_charging_stops": 3,
        "charger_limit": 3,
        "include_leg_edges": False,
    }
    body = request_json("POST", f"{base_url}/api/v1/routing/plan", payload)
    required = {"status", "plan_steps", "chargers_considered", "final_soc"}
    if not required <= set(body):
        raise RuntimeError(f"live multi-stop plan returned unexpected payload: {body}")
    print(f"ok: live multi-stop plan generated, status={body['status']}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("SMOKE_BASE_URL", "http://localhost"))
    parser.add_argument(
        "--route-edges",
        default=os.getenv("ROUTE_EDGES_PATH", "route_edges.json"),
        type=Path,
    )
    parser.add_argument(
        "--live-valhalla",
        action="store_true",
        help="Also verify /api/v1/routing/simulate against a running Valhalla service.",
    )
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    assert_health(base_url)
    assert_worst_case_depletion(base_url)
    assert_delhi_route(base_url, args.route_edges)
    assert_confidence_loads(base_url)
    if args.live_valhalla:
        assert_live_valhalla_route(base_url)
        assert_live_recommendations(base_url)
        assert_live_multi_stop_plan(base_url)
    print("all smoke checks passed")


if __name__ == "__main__":
    main()
