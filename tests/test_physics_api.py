"""Tests for the FastAPI physics simulation service."""

from fastapi.testclient import TestClient

from app.main import app
from app.physics.cycle_bridge import valhalla_to_1hz_cycle
from app.physics.schemas import RouteEdge

client = TestClient(app)


def synthetic_payload(distance_m: float = 1200.0, starting_soc: float = 0.72) -> dict:
    return {
        "vehicle_id": "IN-2025-0001",
        "environment": {"ambient_temp_c": 25.0},
        "starting_soc": starting_soc,
        "route_edges": [
            {
                "edge_index": 0,
                "distance_m": distance_m,
                "speed_kph": 60.0,
                "grade_pct": 1.5,
                "start_coordinate": {"lat": 12.9716, "lon": 77.5946},
                "end_coordinate": {"lat": 12.9816, "lon": 77.6046},
            },
        ],
    }


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cycle_bridge_converts_units_and_coordinates() -> None:
    edge = RouteEdge(**synthetic_payload()["route_edges"][0])
    cycle, coord_map = valhalla_to_1hz_cycle([edge], ambient_temp_c=25.0)
    cycle_dict = cycle.to_pydict(data_fmt="yaml")

    assert cycle_dict["speed_meters_per_second"][1] == 60.0 / 3.6
    assert cycle_dict["grade"][1] == 0.015
    assert coord_map[0].lat == 12.9716
    assert coord_map[max(coord_map)].lat == 12.9816


def test_simulate_route_from_vehicle_dataset() -> None:
    response = client.post("/api/v1/physics/simulate", json=synthetic_payload())
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "route_completed"
    assert body["vehicle"]["vehicle_id"] == "IN-2025-0001"
    assert body["vehicle"]["usable_ess_kwh"] == 28.6
    assert body["route_duration_s"] > 0
    assert body["route_distance_m"] == 1200.0
    assert len(body["soc_timeline"]) == body["route_duration_s"] + 1
    assert body["final_soc"] < 0.72


def test_simulate_route_from_custom_ev_profile() -> None:
    payload = synthetic_payload()
    payload.pop("vehicle_id")
    payload["custom_ev_profile"] = {
        "name": "Tata Nexon EV LR",
        "scenario_name": "Custom BEV Routing",
        "vehPtType": 1,
        "dragCoef": 0.33,
        "frontalAreaM2": 2.4,
        "vehCgM": 1400,
        "maxEssKwh": 40.5,
        "maxMotorKw": 106,
        "wheelRrCoef": 0.008,
    }

    response = client.post("/api/v1/physics/simulate", json=payload)
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "route_completed"
    assert body["vehicle"]["vehicle_id"] == "Tata Nexon EV LR"
    assert body["vehicle"]["effective_kwh"] == 40.5
    assert body["vehicle"]["drag_coef"] == 0.33
    assert body["vehicle"]["max_motor_kw"] == 106.0
    assert body["final_soc"] < 0.72


def test_simulate_route_reports_depletion() -> None:
    response = client.post(
        "/api/v1/physics/simulate",
        json=synthetic_payload(distance_m=300_000.0, starting_soc=0.12),
    )
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "depletion_triggered"
    assert body["depletion_second"] is not None
    assert body["depletion_coordinate"] is not None


def test_unknown_vehicle_returns_404() -> None:
    payload = synthetic_payload()
    payload["vehicle_id"] = "missing-vehicle"

    response = client.post("/api/v1/physics/simulate", json=payload)

    assert response.status_code == 404


def test_vehicle_state_state_of_health_changes_effective_capacity() -> None:
    payload = synthetic_payload(distance_m=1200.0, starting_soc=0.8)
    payload["vehicle_state"] = {
        "starting_soc": 0.8,
        "protection_soc": 0.15,
        "state_of_health": 0.7,
    }

    response = client.post("/api/v1/physics/simulate", json=payload)
    body = response.json()

    assert response.status_code == 200, body
    assert body["battery_correction"]["soh_factor"] == 0.7
    assert body["vehicle"]["effective_kwh"] < body["vehicle"]["usable_ess_kwh"]


def test_runtime_diagnostics_exposes_engine_mode() -> None:
    response = client.get("/diagnostics/runtime")
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "ok"
    assert body["simulation_engine"] in {"fastsim", "synthetic_fallback"}
