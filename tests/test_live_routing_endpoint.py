"""Tests for live Valhalla-backed routing endpoint wiring."""

from fastapi.testclient import TestClient

from app.main import app
from app.physics.schemas import Coordinate, RouteEdge
from app.routing import endpoints

client = TestClient(app)


def test_routing_simulate_generates_edges_then_runs_physics(monkeypatch) -> None:
    """The live endpoint should turn start/end into route_edges before simulation."""

    def fake_route_edges_from_valhalla(_client, start: Coordinate, end: Coordinate, costing: str):
        assert start.lat == 28.597861
        assert end.lon == 77.1
        assert costing == "auto"
        return [
            RouteEdge(
                edge_index=0,
                distance_m=1200.0,
                speed_kph=40.0,
                grade_pct=0.5,
                heading_deg=180.0,
                start_coordinate=start,
                end_coordinate=end,
            ),
        ]

    monkeypatch.setattr(endpoints, "route_edges_from_valhalla", fake_route_edges_from_valhalla)
    monkeypatch.setattr(endpoints, "client_from_env", lambda: object())

    response = client.post(
        "/api/v1/routing/simulate",
        json={
            "vehicle_id": "IN-2025-0007",
            "start": {"lat": 28.597861, "lon": 77.032485},
            "end": {"lat": 28.556, "lon": 77.1},
            "environment": {"ambient_temp_c": 25.0},
            "vehicle_state": {"starting_soc": 0.8, "protection_soc": 0.15},
        },
    )
    body = response.json()

    assert response.status_code == 200, body
    assert body["route_edges"][0]["distance_m"] == 1200.0
    assert body["simulation"]["status"] == "route_completed"
    assert body["simulation"]["route_distance_m"] == 1200.0


def test_routing_simulate_maps_valhalla_failure_to_502(monkeypatch) -> None:
    """A failed Valhalla service call should not look like a physics error."""

    def fail_route(*_args, **_kwargs):
        from app.routing.valhalla_client import ValhallaError

        raise ValhallaError("Valhalla route request failed")

    monkeypatch.setattr(endpoints, "route_edges_from_valhalla", fail_route)
    monkeypatch.setattr(endpoints, "client_from_env", lambda: object())

    response = client.post(
        "/api/v1/routing/simulate",
        json={
            "vehicle_id": "IN-2025-0007",
            "start": {"lat": 28.597861, "lon": 77.032485},
            "end": {"lat": 28.556, "lon": 77.1},
            "vehicle_state": {"starting_soc": 0.8, "protection_soc": 0.15},
        },
    )

    assert response.status_code == 502
