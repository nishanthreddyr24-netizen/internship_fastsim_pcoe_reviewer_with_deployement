"""FastAPI endpoints for physics simulation."""

from fastapi import APIRouter, HTTPException

from app.physics.schemas import SimulateRequest, SimulateResponse
from app.physics.simulator import VehicleProfileError, simulate_route
from app.physics.vehicle_store import VehicleNotFoundError

router = APIRouter(prefix="/physics", tags=["physics"])


@router.post("/simulate", response_model=SimulateResponse)
def simulate(request: SimulateRequest) -> SimulateResponse:
    """Run a FASTSim-backed route simulation."""
    try:
        return simulate_route(request)
    except VehicleNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except VehicleProfileError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err

