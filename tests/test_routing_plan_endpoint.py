"""Endpoint tests for SOC-aware multi-stop planning."""

from fastapi.testclient import TestClient

from app.main import app
from app.physics.schemas import Coordinate
from app.routing import endpoints
from app.routing.schemas import RoutingPlanResponse

client = TestClient(app)


def test_routing_plan_endpoint_returns_planner_response(monkeypatch) -> None:
    def fake_plan(request, _client):
        return RoutingPlanResponse(
            status="destination_reached",
            plan_steps=[],
            chargers_considered=[],
            final_soc=request.starting_soc or request.vehicle_state.starting_soc,
            total_distance_m=0.0,
            total_drive_time_s=0,
            total_estimated_charge_minutes=0.0,
        )

    monkeypatch.setattr(endpoints, "client_from_env", lambda: object())
    monkeypatch.setattr(endpoints, "plan_multi_stop_route", fake_plan)

    response = client.post(
        "/api/v1/routing/plan",
        json={
            "vehicle_id": "IN-2025-0007",
            "start": {"lat": 28.597861, "lon": 77.032485},
            "end": {"lat": 28.5434438, "lon": 77.2063442},
            "vehicle_state": {"starting_soc": 0.8, "protection_soc": 0.15},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "destination_reached"
