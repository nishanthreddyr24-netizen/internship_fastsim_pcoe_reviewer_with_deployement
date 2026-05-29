"""FastAPI endpoints for live Valhalla-backed route simulation."""

from fastapi import APIRouter, HTTPException

from app.physics.schemas import SimulateRequest
from app.physics.simulator import VehicleProfileError, simulate_route
from app.physics.vehicle_store import VehicleNotFoundError
from app.routing.charger_recommendations import recommended_chargers
from app.routing.multi_stop_planner import plan_multi_stop_route
from app.routing.schemas import (
    ChargerSearchAnchor,
    RoutingPlanRequest,
    RoutingPlanResponse,
    RoutingRecommendRequest,
    RoutingRecommendResponse,
    RoutingSimulateRequest,
    RoutingSimulateResponse,
)
from app.routing.valhalla_client import ValhallaError, client_from_env, route_edges_from_valhalla

router = APIRouter(prefix="/routing", tags=["routing"])


@router.post("/simulate", response_model=RoutingSimulateResponse)
def route_and_simulate(request: RoutingSimulateRequest) -> RoutingSimulateResponse:
    """Generate route edges with Valhalla, then run the existing physics simulator."""
    try:
        route_edges = route_edges_from_valhalla(
            client_from_env(),
            request.start,
            request.end,
            request.costing,
        )
        simulation = simulate_route(
            SimulateRequest(
                vehicle_id=request.vehicle_id,
                vehicle_profile=request.vehicle_profile,
                custom_ev_profile=request.custom_ev_profile,
                environment=request.environment,
                vehicle_state=request.vehicle_state,
                route_edges=route_edges,
                starting_soc=request.starting_soc,
                protection_soc=request.protection_soc,
            ),
        )
        return RoutingSimulateResponse(route_edges=route_edges, simulation=simulation)
    except ValhallaError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    except VehicleNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except VehicleProfileError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.post("/plan", response_model=RoutingPlanResponse)
def plan_multi_charging_route(request: RoutingPlanRequest) -> RoutingPlanResponse:
    """Build a greedy p_fail-aware multi-charging route plan."""
    try:
        return plan_multi_stop_route(request, client_from_env())
    except ValhallaError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    except VehicleNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except VehicleProfileError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err


@router.post("/recommend", response_model=RoutingRecommendResponse)
def route_simulate_and_recommend(request: RoutingRecommendRequest) -> RoutingRecommendResponse:
    """Generate the primary route, simulate it, and show ranked charger possibilities."""
    try:
        valhalla_client = client_from_env()
        primary_route_edges = route_edges_from_valhalla(
            valhalla_client,
            request.start,
            request.end,
            request.costing,
        )
        simulation = simulate_route(
            SimulateRequest(
                vehicle_id=request.vehicle_id,
                vehicle_profile=request.vehicle_profile,
                custom_ev_profile=request.custom_ev_profile,
                environment=request.environment,
                vehicle_state=request.vehicle_state,
                route_edges=primary_route_edges,
                starting_soc=request.starting_soc,
                protection_soc=request.protection_soc,
            ),
        )
        if simulation.depletion_coordinate is not None:
            anchor = ChargerSearchAnchor(
                coordinate=simulation.depletion_coordinate,
                reason="depletion",
            )
        else:
            anchor = ChargerSearchAnchor(coordinate=request.end, reason="destination")

        chargers = recommended_chargers(
            anchor.coordinate,
            request.charger_radius_km,
            request.charger_limit,
            request.compatible_only,
            request.include_charger_routes,
            valhalla_client,
            request.costing,
        )
        return RoutingRecommendResponse(
            primary_route_edges=primary_route_edges,
            simulation=simulation,
            charger_search_anchor=anchor,
            recommended_chargers=chargers,
        )
    except ValhallaError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    except VehicleNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except VehicleProfileError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
