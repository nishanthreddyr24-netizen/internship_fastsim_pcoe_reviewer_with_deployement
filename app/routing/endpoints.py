"""FastAPI endpoints for live Valhalla-backed route simulation."""

from fastapi import APIRouter, HTTPException

from app.physics.schemas import SimulateRequest
from app.physics.simulator import VehicleProfileError, simulate_route
from app.physics.vehicle_store import VehicleNotFoundError
from app.routing.schemas import RoutingSimulateRequest, RoutingSimulateResponse
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
