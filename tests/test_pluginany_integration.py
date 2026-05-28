"""Offline tests for the PluginAny routing integration protocol."""

import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.physics import vehicle_store
from app.physics.environment import (
    adjusted_rolling_resistance,
    effective_aero_speed_kph,
    estimate_hvac_power_kw,
)
from app.physics.schemas import RouteEdge
from app.physics.valhalla_adapter import route_edges_from_valhalla_payload, validate_valhalla_edges
from app.physics.weather import DEFAULT_TIMEOUT_S, fetch_weather, normalize_weather_payload

client = TestClient(app)
ROOT = Path(__file__).resolve().parents[1]


def pdf_worst_case_payload() -> dict:
    return {
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


def perfect_conditions_payload() -> dict:
    payload = pdf_worst_case_payload()
    payload["environment"] = {
        "ambient_temp_c": 25.0,
        "wind_speed_kph": 0.0,
        "wind_direction_deg": 0.0,
        "precipitation_mm": 0.0,
    }
    payload["vehicle_state"] = {
        "starting_soc": 0.20,
        "protection_soc": 0.15,
        "hvac_power_kw": 0.0,
        "adjusted_rr_coef": 0.012,
    }
    payload["route_edges"][0]["wind_direction_deg"] = 0.0
    return payload


def test_vehicle_db_returns_integration_fields() -> None:
    profile = vehicle_store.profile_from_dataset("IN-2025-0007")

    assert profile.usable_ess_kwh == 55.3
    assert profile.veh_cg_m == 1900.0
    assert profile.max_motor_kw == 210.0
    assert profile.drag_coef == 0.31
    assert profile.frontal_area_m2 == 2.64
    assert profile.wheel_rr_coef == 0.012


def test_vehicle_db_missing_rr_falls_back_and_logs(monkeypatch, caplog) -> None:
    vehicle_store.load_vehicle_dataset.cache_clear()
    monkeypatch.setattr(
        vehicle_store,
        "load_vehicle_dataset",
        lambda: pd.DataFrame(
            [
                {
                    "Vehicle ID": "missing-rr",
                    "Brand *": "Synthetic",
                    "Model *": "Fallback",
                    "Year From *": 2026,
                    "Battery kWh *": 50.0,
                    "Battery kWh usable": 45.0,
                    "Mass kg *": 1600.0,
                    "Motor kW": 120.0,
                    "Drag Cd *": 0.30,
                    "Frontal A m2 *": 2.3,
                    "Roll Cr": None,
                },
            ],
        ),
    )

    with caplog.at_level("WARNING"):
        profile = vehicle_store.profile_from_dataset("missing-rr")

    assert profile.wheel_rr_coef == 0.012
    assert "missing Roll Cr" in caplog.text


def test_weather_wrapper_normalizes_units_and_falls_back() -> None:
    env = normalize_weather_payload(
        {
            "current": {
                "temperature_2m": 31.0,
                "wind_speed_10m": 12.5,
                "wind_direction_10m": 270.0,
                "precipitation": 1.2,
            },
        },
    )

    assert env.ambient_temp_c == 31.0
    assert env.wind_speed_kph == 12.5
    assert env.wind_direction_deg == 270.0
    assert env.precipitation_mm == 1.2

    result = fetch_weather(28.57, 77.05, base_url="https://weather.invalid", fetcher=lambda *_: (_ for _ in ()).throw(TimeoutError()))
    assert result.degraded is True
    assert result.elapsed_ms < DEFAULT_TIMEOUT_S * 1000.0
    assert result.environment.ambient_temp_c == 25.0


def test_weather_wrapper_normalizes_openweather_payload() -> None:
    env = normalize_weather_payload(
        {
            "main": {"temp": 29.4},
            "wind": {"speed": 4.2, "deg": 260.0},
            "rain": {"1h": 2.4},
        },
    )

    assert env.ambient_temp_c == 29.4
    assert env.wind_speed_kph == pytest.approx(15.12)
    assert env.wind_direction_deg == 260.0
    assert env.precipitation_mm == 2.4


def test_weatherapi_url_uses_key_and_coordinate_query() -> None:
    captured = {}

    def fake_fetcher(url: str, timeout_s: float) -> dict:
        captured["url"] = url
        captured["timeout_s"] = timeout_s
        return {
            "current": {
                "temp_c": 39.4,
                "wind_kph": 19.4,
                "wind_degree": 260.0,
                "precip_mm": 0.0,
            },
        }

    result = fetch_weather(
        28.57,
        77.05,
        base_url="https://api.weatherapi.com/v1/current.json",
        api_key="test-key",
        timeout_s=1.5,
        fetcher=fake_fetcher,
    )

    assert result.degraded is False
    assert "key=test-key" in captured["url"]
    assert "q=28.57%2C77.05" in captured["url"]
    assert "aqi=no" in captured["url"]
    assert captured["timeout_s"] == 1.5
    assert result.environment.ambient_temp_c == 39.4


def test_offline_valhalla_route_fixture_validates_edges() -> None:
    payload = json.loads((ROOT / "route_edges.json").read_text())
    edges = route_edges_from_valhalla_payload(payload)
    validate_valhalla_edges(edges)

    assert len(edges) > 1
    assert edges[0].distance_m > 0.0
    assert edges[0].heading_deg is not None
    assert isinstance(edges[0], RouteEdge)


def test_headwind_crosswind_and_weather_adjustments() -> None:
    assert effective_aero_speed_kph(80.0, 0.0, 20.0, 180.0) == pytest.approx(100.0)
    assert effective_aero_speed_kph(80.0, 0.0, 20.0, 90.0) == pytest.approx(80.0)
    assert adjusted_rolling_resistance(0.010, precipitation_mm=5.0) == 0.0115
    assert 3.0 <= estimate_hvac_power_kw(40.0) <= 4.5
    assert estimate_hvac_power_kw(40.0, override_kw=2.25) == 2.25


def test_pdf_worst_case_payload_triggers_depletion_earlier_than_perfect_conditions() -> None:
    perfect = client.post("/api/v1/physics/simulate", json=perfect_conditions_payload()).json()
    worst = client.post("/api/v1/physics/simulate", json=pdf_worst_case_payload()).json()

    assert worst["status"] == "depletion_triggered"
    assert worst["depletion_coordinate"] is not None
    assert worst["depletion_second"] is not None
    assert worst["final_soc"] < perfect["final_soc"]
    assert worst["vehicle"]["wheel_rr_coef"] == 0.014
    assert worst["vehicle"]["hvac_power_kw"] == 4.0
