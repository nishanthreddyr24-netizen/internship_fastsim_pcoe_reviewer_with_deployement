"""Tests for the greedy SOC-aware multi-stop planner."""

import pandas as pd

from app.confidence.schemas import ConfidenceResult, ReviewStats
from app.physics.schemas import Coordinate, RouteEdge
from app.routing.multi_stop_planner import plan_multi_stop_route
from app.routing.schemas import RoutingPlanRequest


START = Coordinate(lat=28.50, lon=77.00)
DESTINATION = Coordinate(lat=28.90, lon=77.40)
CHARGER_A = Coordinate(lat=28.60, lon=77.10)
CHARGER_B = Coordinate(lat=28.70, lon=77.20)


def route_edge(start: Coordinate, end: Coordinate, distance_m: float) -> RouteEdge:
    return RouteEdge(
        edge_index=0,
        distance_m=distance_m,
        speed_kph=40.0,
        grade_pct=0.0,
        heading_deg=180.0,
        start_coordinate=start,
        end_coordinate=end,
    )


def confidence(station_id: str, p_fail: float) -> ConfidenceResult:
    return ConfidenceResult(
        station_id=station_id,
        station_name=f"Station {station_id}",
        latitude=28.60,
        longitude=77.10,
        ocpi_status="AVAILABLE",
        equipment_age_days=0,
        p_fail=p_fail,
        confidence=round(1.0 - p_fail, 6),
        review_stats=ReviewStats(
            review_count=1,
            weighted_review_count=1.0,
            average_sentiment=0.9,
            latest_review_date=None,
        ),
    )


def charger_row(station_id: str, coord: Coordinate, power_kw: float = 60.0) -> pd.Series:
    return pd.Series(
        {
            "station_id": station_id,
            "name": f"Station {station_id}",
            "address": f"Address {station_id}",
            "lat": coord.lat,
            "lon": coord.lon,
            "connector_types": "CCS2",
            "total_ports": 2,
            "max_power_kw": power_kw,
            "total_reviews": 1,
            "be6_compatible": True,
        },
    )


def request(**overrides) -> RoutingPlanRequest:
    data = {
        "vehicle_id": "IN-2025-0007",
        "start": START,
        "end": DESTINATION,
        "vehicle_state": {"starting_soc": 0.16, "protection_soc": 0.15},
        "target_soc_after_charge": 0.70,
        "max_charging_stops": 3,
        "charger_radius_km": 25.0,
        "charger_limit": 5,
        "include_leg_edges": True,
    }
    data.update(overrides)
    return RoutingPlanRequest(**data)


def direct_route(distance_m: float):
    def builder(_client, start: Coordinate, end: Coordinate, _costing: str):
        return [route_edge(start, end, distance_m)]

    return builder


def test_planner_reaches_destination_with_zero_stops() -> None:
    plan = plan_multi_stop_route(
        request(vehicle_state={"starting_soc": 0.80, "protection_soc": 0.15}),
        valhalla_client=object(),
        route_builder=direct_route(1000.0),
        candidate_builder=lambda *_: [],
    )

    assert plan.status == "destination_reached"
    assert len(plan.plan_steps) == 1
    assert plan.plan_steps[0].step_type == "drive"
    assert plan.total_estimated_charge_minutes == 0.0


def test_planner_adds_one_charging_stop_when_destination_depletes() -> None:
    def builder(_client, start: Coordinate, end: Coordinate, _costing: str):
        if end == DESTINATION and start == START:
            return [route_edge(start, end, 300_000.0)]
        return [route_edge(start, end, 1000.0)]

    def candidates(*_args):
        return [(charger_row("A", CHARGER_A), confidence("A", 0.1), "reviews", 1.0)]

    plan = plan_multi_stop_route(request(), object(), builder, candidates)

    assert plan.status == "destination_reached"
    assert [step.step_type for step in plan.plan_steps] == ["drive", "charge", "drive"]
    assert plan.plan_steps[1].station_id == "A"
    assert plan.plan_steps[1].departure_soc == 0.7


def test_planner_supports_two_charging_stops() -> None:
    def builder(_client, start: Coordinate, end: Coordinate, _costing: str):
        if end == DESTINATION and start != CHARGER_B:
            return [route_edge(start, end, 300_000.0)]
        return [route_edge(start, end, 1000.0)]

    def candidates(anchor, *_args):
        if anchor.lat < 28.65:
            return [(charger_row("A", CHARGER_A), confidence("A", 0.1), "reviews", 1.0)]
        return [(charger_row("B", CHARGER_B), confidence("B", 0.1), "reviews", 1.0)]

    plan = plan_multi_stop_route(request(), object(), builder, candidates)

    assert plan.status == "destination_reached"
    assert [step.step_type for step in plan.plan_steps] == [
        "drive",
        "charge",
        "drive",
        "charge",
        "drive",
    ]
    assert [step.station_id for step in plan.plan_steps if step.step_type == "charge"] == ["A", "B"]


def test_planner_fails_when_no_charger_is_reachable() -> None:
    def builder(_client, start: Coordinate, end: Coordinate, _costing: str):
        return [route_edge(start, end, 300_000.0)]

    def candidates(*_args):
        return [(charger_row("A", CHARGER_A), confidence("A", 0.1), "reviews", 1.0)]

    plan = plan_multi_stop_route(request(), object(), builder, candidates)

    assert plan.status == "planning_failed"
    assert plan.chargers_considered[0][0].reachable is False


def test_planner_respects_max_charging_stops() -> None:
    plan = plan_multi_stop_route(
        request(max_charging_stops=0),
        object(),
        direct_route(300_000.0),
        lambda *_: [],
    )

    assert plan.status == "max_stops_exceeded"


def test_planner_uses_fallback_charger_power_when_catalog_power_missing() -> None:
    def builder(_client, start: Coordinate, end: Coordinate, _costing: str):
        if end == DESTINATION and start == START:
            return [route_edge(start, end, 300_000.0)]
        return [route_edge(start, end, 1000.0)]

    def candidates(*_args):
        return [(charger_row("A", CHARGER_A, power_kw=0.0), confidence("A", 0.1), "reviews", 1.0)]

    plan = plan_multi_stop_route(request(fallback_charger_power_kw=22.0), object(), builder, candidates)
    charge_step = next(step for step in plan.plan_steps if step.step_type == "charge")

    assert charge_step.charge_estimate_source == "fallback_power"
    assert charge_step.charger_power_kw == 22.0
    assert charge_step.estimated_charge_minutes > 0.0


def test_planner_selects_lowest_p_fail_reachable_charger() -> None:
    def builder(_client, start: Coordinate, end: Coordinate, _costing: str):
        if end == DESTINATION and start == START:
            return [route_edge(start, end, 300_000.0)]
        return [route_edge(start, end, 1000.0)]

    def candidates(*_args):
        return [
            (charger_row("high-risk", CHARGER_A), confidence("high-risk", 0.4), "reviews", 1.0),
            (charger_row("low-risk", CHARGER_B), confidence("low-risk", 0.1), "reviews", 2.0),
        ]

    plan = plan_multi_stop_route(request(), object(), builder, candidates)
    charge_step = next(step for step in plan.plan_steps if step.step_type == "charge")

    assert charge_step.station_id == "low-risk"
    assert plan.chargers_considered[0][0].charger.station_id == "high-risk"
    assert plan.chargers_considered[0][1].charger.station_id == "low-risk"
