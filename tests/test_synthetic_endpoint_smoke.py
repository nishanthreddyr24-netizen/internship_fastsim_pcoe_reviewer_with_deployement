"""Synthetic endpoint smoke tests for the current API surface."""

import pandas as pd
from fastapi.testclient import TestClient

from app.confidence import service
from app.main import app

client = TestClient(app)


class SyntheticScorer:
    """Small deterministic scorer used to avoid loading external NLP models."""

    def score(self, comment: str) -> float:
        lowered = comment.lower()
        if "blocked" in lowered or "fault" in lowered:
            return 0.12
        if "working" in lowered or "fast" in lowered:
            return 0.92
        return 0.55


def synthetic_reviews() -> pd.DataFrame:
    """Return synthetic station reviews as of 2026-05-21."""
    return pd.DataFrame(
        [
            {
                "station_id": "synthetic-alpha",
                "station_name": "Synthetic Alpha Charge",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "operator": "Synthetic Grid",
                "rating": 1,
                "comment": "Working fast charger today",
                "review_date": pd.Timestamp("2026-05-21T08:00:00Z"),
            },
            {
                "station_id": "synthetic-alpha",
                "station_name": "Synthetic Alpha Charge",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "operator": "Synthetic Grid",
                "rating": -1,
                "comment": "Connector fault yesterday",
                "review_date": pd.Timestamp("2026-05-20T08:00:00Z"),
            },
            {
                "station_id": "synthetic-beta",
                "station_name": "Synthetic Beta Charge",
                "latitude": 12.9766,
                "longitude": 77.5996,
                "operator": "Synthetic Grid",
                "rating": 1,
                "comment": "Working well",
                "review_date": pd.Timestamp("2026-05-21T09:00:00Z"),
            },
        ],
    )


def install_synthetic_confidence(monkeypatch) -> None:
    monkeypatch.setattr(service, "load_reviews", synthetic_reviews)
    monkeypatch.setattr(service, "_default_scorer", lambda: SyntheticScorer())


def synthetic_route_payload() -> dict:
    return {
        "custom_ev_profile": {
            "name": "Synthetic EV",
            "scenario_name": "Synthetic Endpoint Smoke",
            "vehPtType": 1,
            "dragCoef": 0.31,
            "frontalAreaM2": 2.25,
            "vehCgM": 1380,
            "maxEssKwh": 42.0,
            "maxMotorKw": 110,
            "wheelRrCoef": 0.008,
        },
        "environment": {"ambient_temp_c": 30.0},
        "starting_soc": 0.80,
        "route_edges": [
            {
                "edge_index": 0,
                "distance_m": 800.0,
                "speed_kph": 45.0,
                "grade_pct": 0.5,
                "start_coordinate": {"lat": 12.9716, "lon": 77.5946},
                "end_coordinate": {"lat": 12.9766, "lon": 77.5996},
            },
            {
                "edge_index": 1,
                "distance_m": 650.0,
                "speed_kph": 35.0,
                "grade_pct": -0.2,
                "start_coordinate": {"lat": 12.9766, "lon": 77.5996},
                "end_coordinate": {"lat": 12.9816, "lon": 77.6046},
            },
        ],
    }


def test_synthetic_health_endpoint() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_synthetic_physics_simulation_endpoint() -> None:
    response = client.post("/api/v1/physics/simulate", json=synthetic_route_payload())
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "route_completed"
    assert body["vehicle"]["vehicle_id"] == "Synthetic EV"
    assert body["route_distance_m"] == 1450.0
    assert body["route_duration_s"] > 0
    assert body["final_soc"] < 0.80


def test_synthetic_confidence_station_endpoint(monkeypatch) -> None:
    install_synthetic_confidence(monkeypatch)

    response = client.get("/api/v1/confidence/stations/synthetic-alpha")
    body = response.json()

    assert response.status_code == 200, body
    assert body["station_name"] == "Synthetic Alpha Charge"
    assert body["review_stats"]["review_count"] == 2
    assert 0.0 <= body["p_fail"] <= 1.0


def test_synthetic_confidence_nearby_endpoint(monkeypatch) -> None:
    install_synthetic_confidence(monkeypatch)

    response = client.get(
        "/api/v1/confidence/nearby?lat=12.9716&lon=77.5946&radius_km=5&limit=5",
    )
    body = response.json()

    assert response.status_code == 200, body
    assert {item["station_id"] for item in body["results"]} == {
        "synthetic-alpha",
        "synthetic-beta",
    }


def test_synthetic_confidence_rank_endpoint(monkeypatch) -> None:
    install_synthetic_confidence(monkeypatch)

    response = client.post(
        "/api/v1/confidence/rank",
        json={
            "station_ids": ["synthetic-alpha", "synthetic-beta"],
            "ocpi_status": {"synthetic-alpha": "UNAVAILABLE"},
            "equipment_age_days": {"synthetic-alpha": 500},
        },
    )
    body = response.json()

    assert response.status_code == 200, body
    assert body["results"][-1]["station_id"] == "synthetic-alpha"
    assert body["results"][-1]["ocpi_status"] == "UNAVAILABLE"
