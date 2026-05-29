"""Tests for the final route recommendation endpoint."""

from fastapi.testclient import TestClient

from app.main import app
from app.physics.schemas import Coordinate, RouteEdge
from app.routing import endpoints

client = TestClient(app)


def route_edge(start: Coordinate, end: Coordinate, distance_m: float = 1200.0) -> RouteEdge:
    return RouteEdge(
        edge_index=0,
        distance_m=distance_m,
        speed_kph=40.0,
        grade_pct=0.0,
        heading_deg=180.0,
        start_coordinate=start,
        end_coordinate=end,
    )


def fake_primary_route(_client, start: Coordinate, end: Coordinate, _costing: str):
    return [route_edge(start, end)]


def test_recommend_uses_destination_anchor_when_route_completes(monkeypatch) -> None:
    captured = {}

    def fake_recommended_chargers(anchor, *_args, **_kwargs):
        captured["anchor"] = anchor
        return []

    monkeypatch.setattr(endpoints, "client_from_env", lambda: object())
    monkeypatch.setattr(endpoints, "route_edges_from_valhalla", fake_primary_route)
    monkeypatch.setattr(endpoints, "recommended_chargers", fake_recommended_chargers)

    response = client.post(
        "/api/v1/routing/recommend",
        json={
            "vehicle_id": "IN-2025-0007",
            "start": {"lat": 28.597861, "lon": 77.032485},
            "end": {"lat": 28.556, "lon": 77.1},
            "vehicle_state": {"starting_soc": 0.8, "protection_soc": 0.15},
            "include_charger_routes": False,
        },
    )
    body = response.json()

    assert response.status_code == 200, body
    assert body["charger_search_anchor"]["reason"] == "destination"
    assert captured["anchor"].lat == 28.556
    assert body["simulation"]["status"] == "route_completed"
    assert body["recommended_chargers"] == []


def test_recommend_uses_depletion_anchor_when_route_depletes(monkeypatch) -> None:
    captured = {}

    def long_primary_route(_client, start: Coordinate, end: Coordinate, _costing: str):
        return [route_edge(start, end, distance_m=300_000.0)]

    def fake_recommended_chargers(anchor, *_args, **_kwargs):
        captured["anchor"] = anchor
        return []

    monkeypatch.setattr(endpoints, "client_from_env", lambda: object())
    monkeypatch.setattr(endpoints, "route_edges_from_valhalla", long_primary_route)
    monkeypatch.setattr(endpoints, "recommended_chargers", fake_recommended_chargers)

    response = client.post(
        "/api/v1/routing/recommend",
        json={
            "vehicle_id": "IN-2025-0007",
            "start": {"lat": 28.597861, "lon": 77.032485},
            "end": {"lat": 28.556, "lon": 77.1},
            "vehicle_state": {"starting_soc": 0.16, "protection_soc": 0.15},
            "include_charger_routes": False,
        },
    )
    body = response.json()

    assert response.status_code == 200, body
    assert body["charger_search_anchor"]["reason"] == "depletion"
    assert body["simulation"]["status"] == "depletion_triggered"
    assert captured["anchor"].lat == body["simulation"]["depletion_coordinate"]["lat"]
