"""Greedy SOC-aware multi-stop EV route planner."""

from __future__ import annotations

from typing import Callable

import pandas as pd

from app.physics.schemas import Coordinate, RouteEdge, SimulateRequest
from app.physics.simulator import simulate_route
from app.routing.charger_recommendations import (
    _clean_float,
    _clean_int,
    _clean_text,
    candidate_chargers,
)
from app.routing.schemas import (
    ChargePlanStep,
    ConsideredCharger,
    DrivePlanStep,
    RecommendedCharger,
    RoutingPlanRequest,
    RoutingPlanResponse,
)
from app.routing.valhalla_client import ValhallaClient, ValhallaError, route_edges_from_valhalla


RouteBuilder = Callable[[ValhallaClient, Coordinate, Coordinate, str], list[RouteEdge]]
CandidateBuilder = Callable[
    [Coordinate, float, int, bool],
    list[tuple[pd.Series, object, str, float]],
]


def _simulate_leg(
    request: RoutingPlanRequest,
    route_edges: list[RouteEdge],
    starting_soc: float,
):
    return simulate_route(
        SimulateRequest(
            vehicle_id=request.vehicle_id,
            vehicle_profile=request.vehicle_profile,
            custom_ev_profile=request.custom_ev_profile,
            environment=request.environment,
            vehicle_state=request.vehicle_state,
            route_edges=route_edges,
            starting_soc=starting_soc,
            protection_soc=request.protection_soc,
        ),
    )


def _recommended_from_candidate(
    row: pd.Series,
    confidence,
    source: str,
    distance_km: float,
    route_edges: list[RouteEdge] | None,
    route_status: str,
    route_error: str | None,
) -> RecommendedCharger:
    return RecommendedCharger(
        station_id=str(row["station_id"]),
        station_name=str(row["name"]),
        address=_clean_text(row.get("address")),
        lat=float(row["lat"]),
        lon=float(row["lon"]),
        connector_types=_clean_text(row.get("connector_types")),
        total_ports=_clean_int(row.get("total_ports")),
        max_power_kw=_clean_float(row.get("max_power_kw")),
        total_reviews=_clean_int(row.get("total_reviews")),
        be6_compatible=bool(row["be6_compatible"]),
        distance_from_anchor_km=round(distance_km, 6),
        confidence_source=source,
        confidence=confidence,
        route_status=route_status,
        route_to_charger_edges=route_edges,
        route_error=route_error,
    )


def _charge_step(
    request: RoutingPlanRequest,
    row: pd.Series,
    confidence,
    arrival_soc: float,
    effective_kwh: float,
) -> ChargePlanStep:
    catalog_power = _clean_float(row.get("max_power_kw"))
    if catalog_power is not None and catalog_power > 0.0:
        power_kw = catalog_power
        source = "catalog_power"
    else:
        power_kw = request.fallback_charger_power_kw
        source = "fallback_power"

    departure_soc = max(arrival_soc, request.target_soc_after_charge)
    energy_added_kwh = max(0.0, effective_kwh * (departure_soc - arrival_soc))
    charge_minutes = (energy_added_kwh / power_kw) * 60.0 if power_kw > 0.0 else 0.0

    return ChargePlanStep(
        station_id=str(row["station_id"]),
        station_name=str(row["name"]),
        coordinate=Coordinate(lat=float(row["lat"]), lon=float(row["lon"])),
        arrival_soc=round(arrival_soc, 6),
        departure_soc=round(departure_soc, 6),
        energy_added_kwh=round(energy_added_kwh, 6),
        estimated_charge_minutes=round(charge_minutes, 6),
        charger_power_kw=round(power_kw, 6),
        charge_estimate_source=source,
        confidence=confidence,
    )


def plan_multi_stop_route(
    request: RoutingPlanRequest,
    valhalla_client: ValhallaClient,
    route_builder: RouteBuilder = route_edges_from_valhalla,
    candidate_builder: CandidateBuilder = candidate_chargers,
) -> RoutingPlanResponse:
    """Build a greedy SOC-aware route with zero or more charging stops."""
    current_point = request.start
    current_soc = request.starting_soc
    if request.vehicle_state is not None and current_soc is None:
        current_soc = request.vehicle_state.starting_soc
    if current_soc is None:
        raise ValueError("starting_soc or vehicle_state.starting_soc is required")

    plan_steps: list[DrivePlanStep | ChargePlanStep] = []
    chargers_considered: list[list[ConsideredCharger]] = []
    visited_station_ids: set[str] = set()
    total_distance_m = 0.0
    total_drive_time_s = 0
    total_charge_minutes = 0.0
    charging_stops = 0

    while True:
        destination_edges = route_builder(valhalla_client, current_point, request.end, request.costing)
        destination_sim = _simulate_leg(request, destination_edges, current_soc)

        if destination_sim.status == "route_completed":
            plan_steps.append(
                DrivePlanStep(
                    from_coordinate=current_point,
                    to_coordinate=request.end,
                    to_label="destination",
                    route_edges=destination_edges if request.include_leg_edges else None,
                    simulation=destination_sim,
                ),
            )
            total_distance_m += destination_sim.route_distance_m
            total_drive_time_s += destination_sim.route_duration_s
            return RoutingPlanResponse(
                status="destination_reached",
                plan_steps=plan_steps,
                chargers_considered=chargers_considered,
                final_soc=destination_sim.final_soc,
                total_distance_m=round(total_distance_m, 6),
                total_drive_time_s=total_drive_time_s,
                total_estimated_charge_minutes=round(total_charge_minutes, 6),
            )

        if charging_stops >= request.max_charging_stops:
            return RoutingPlanResponse(
                status="max_stops_exceeded",
                plan_steps=plan_steps,
                chargers_considered=chargers_considered,
                final_soc=current_soc,
                total_distance_m=round(total_distance_m, 6),
                total_drive_time_s=total_drive_time_s,
                total_estimated_charge_minutes=round(total_charge_minutes, 6),
            )

        anchor = destination_sim.depletion_coordinate or current_point
        considered_this_leg: list[ConsideredCharger] = []
        reachable_options = []

        for row, confidence, source, distance_km in candidate_builder(
            anchor,
            request.charger_radius_km,
            request.charger_limit,
            request.compatible_only,
        ):
            station_id = str(row["station_id"])
            if station_id in visited_station_ids:
                continue

            charger_coord = Coordinate(lat=float(row["lat"]), lon=float(row["lon"]))
            route_status = "generated"
            route_error = None
            charger_edges = None
            charger_sim = None
            reachable = False
            reason = None

            try:
                charger_edges = route_builder(
                    valhalla_client,
                    current_point,
                    charger_coord,
                    request.costing,
                )
                charger_sim = _simulate_leg(request, charger_edges, current_soc)
                reachable = charger_sim.status == "route_completed"
                reason = "reachable" if reachable else "depletes_before_charger"
            except ValhallaError as err:
                route_status = "unavailable"
                route_error = str(err)
                reason = "route_unavailable"

            recommended = _recommended_from_candidate(
                row,
                confidence,
                source,
                distance_km,
                charger_edges if request.include_leg_edges else None,
                route_status,
                route_error,
            )
            considered_this_leg.append(
                ConsideredCharger(
                    charger=recommended,
                    reachable=reachable,
                    arrival_soc=charger_sim.final_soc if charger_sim is not None else None,
                    reason=reason,
                ),
            )

            if reachable and charger_sim is not None and charger_edges is not None:
                reachable_options.append(
                    (row, confidence, distance_km, charger_coord, charger_edges, charger_sim),
                )

        chargers_considered.append(considered_this_leg)

        if not reachable_options:
            return RoutingPlanResponse(
                status="planning_failed",
                plan_steps=plan_steps,
                chargers_considered=chargers_considered,
                final_soc=current_soc,
                total_distance_m=round(total_distance_m, 6),
                total_drive_time_s=total_drive_time_s,
                total_estimated_charge_minutes=round(total_charge_minutes, 6),
            )

        row, confidence, _, charger_coord, charger_edges, charger_sim = min(
            reachable_options,
            key=lambda item: (
                item[1].p_fail,
                item[2],
                -float(item[0].get("max_power_kw") or 0.0),
                str(item[0]["station_id"]),
            ),
        )
        plan_steps.append(
            DrivePlanStep(
                from_coordinate=current_point,
                to_coordinate=charger_coord,
                to_label=str(row["name"]),
                route_edges=charger_edges if request.include_leg_edges else None,
                simulation=charger_sim,
            ),
        )
        charge_step = _charge_step(
            request,
            row,
            confidence,
            charger_sim.final_soc,
            charger_sim.effective_kwh_allocated,
        )
        plan_steps.append(charge_step)

        total_distance_m += charger_sim.route_distance_m
        total_drive_time_s += charger_sim.route_duration_s
        total_charge_minutes += charge_step.estimated_charge_minutes
        visited_station_ids.add(str(row["station_id"]))
        current_point = charger_coord
        current_soc = charge_step.departure_soc
        charging_stops += 1
