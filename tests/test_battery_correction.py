"""Tests for temperature-adjusted battery capacity."""

from fastapi.testclient import TestClient

from app.main import app
from app.physics.battery import battery_correction, thermal_capacity_factor

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


def test_thermal_factor_keeps_full_capacity_at_25c() -> None:
    correction = battery_correction(usable_kwh=50.0, state_of_health=0.9, ambient_temp_c=25.0)

    assert thermal_capacity_factor(25.0) == 1.0
    assert correction.thermal_factor == 1.0
    assert correction.effective_kwh == 45.0


def test_negative_temperature_reduces_effective_capacity() -> None:
    warm = battery_correction(usable_kwh=50.0, state_of_health=1.0, ambient_temp_c=25.0)
    cold = battery_correction(usable_kwh=50.0, state_of_health=1.0, ambient_temp_c=-10.0)

    assert cold.thermal_factor < warm.thermal_factor
    assert cold.effective_kwh < warm.effective_kwh


def test_very_cold_temperature_clamps_to_minimum_factor() -> None:
    correction = battery_correction(usable_kwh=50.0, state_of_health=1.0, ambient_temp_c=-30.0)

    assert correction.thermal_factor == 0.58
    assert correction.effective_kwh == 29.0


def test_cold_route_consumes_more_soc_than_warm_route() -> None:
    warm_payload = synthetic_payload(distance_m=5000.0, starting_soc=0.72)
    cold_payload = synthetic_payload(distance_m=5000.0, starting_soc=0.72)
    cold_payload["environment"]["ambient_temp_c"] = -10.0

    warm = client.post("/api/v1/physics/simulate", json=warm_payload).json()
    cold = client.post("/api/v1/physics/simulate", json=cold_payload).json()

    assert cold["battery_correction"]["thermal_factor"] < 1.0
    assert cold["final_soc"] < warm["final_soc"]
