"""Schemas for live route generation and simulation."""

from pydantic import BaseModel, Field

from app.physics.schemas import (
    Coordinate,
    CustomEVProfile,
    Environment,
    RouteEdge,
    SimulateResponse,
    VehicleProfile,
    VehicleState,
)


class RoutingSimulateRequest(BaseModel):
    """Start/end routing request that is converted to a physics simulation."""

    vehicle_id: str | None = None
    vehicle_profile: VehicleProfile | None = None
    custom_ev_profile: CustomEVProfile | None = None
    start: Coordinate
    end: Coordinate
    environment: Environment = Field(default_factory=Environment)
    vehicle_state: VehicleState | None = None
    starting_soc: float | None = Field(default=None, gt=0.0, le=1.0)
    protection_soc: float | None = Field(default=None, ge=0.0, lt=1.0)
    costing: str = "auto"


class RoutingSimulateResponse(BaseModel):
    """Live route edges plus the existing physics response."""

    route_edges: list[RouteEdge]
    simulation: SimulateResponse
