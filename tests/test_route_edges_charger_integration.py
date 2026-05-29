"""Integration coverage for the charger-route Valhalla fixture."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.physics.valhalla_adapter import route_edges_from_valhalla_payload, validate_valhalla_edges

ROOT = Path(__file__).resolve().parents[1]
client = TestClient(app)


def charger_route_payload(starting_soc: float = 0.80) -> dict:
    payload = json.loads((ROOT / "route_edges_charger.json").read_text(encoding="utf-8"))
    edges = route_edges_from_valhalla_payload(payload)
    validate_valhalla_edges(edges)
    return {
        "vehicle_id": "IN-2025-0007",
        "environment": {"ambient_temp_c": 25.0},
        "vehicle_state": {"starting_soc": starting_soc, "protection_soc": 0.15},
        "route_edges": [edge.model_dump() for edge in edges],
    }


def test_charger_route_fixture_normalizes_headings() -> None:
    payload = json.loads((ROOT / "route_edges_charger.json").read_text(encoding="utf-8"))
    edges = route_edges_from_valhalla_payload(payload)
    validate_valhalla_edges(edges)

    assert len(edges) == 223
    assert edges[0].heading_deg is not None
    assert edges[-1].heading_deg is not None
    assert sum(edge.distance_m for edge in edges) == 26570.0


def test_charger_route_simulates_to_completion() -> None:
    response = client.post("/api/v1/physics/simulate", json=charger_route_payload())
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "route_completed"
    assert body["route_distance_m"] == 26570.0
    assert body["route_duration_s"] == 1993
    assert body["final_soc"] < 0.80
    assert body["final_soc"] > 0.79
    assert body["depletion_coordinate"] is None


def test_charger_route_low_soc_still_stays_above_buffer() -> None:
    response = client.post("/api/v1/physics/simulate", json=charger_route_payload(0.20))
    body = response.json()

    assert response.status_code == 200, body
    assert body["status"] == "route_completed"
    assert body["final_soc"] > 0.15
    assert body["depletion_coordinate"] is None
