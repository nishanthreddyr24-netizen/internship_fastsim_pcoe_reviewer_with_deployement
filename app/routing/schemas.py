"""Schemas for live route generation and simulation."""

from typing import Literal

from pydantic import BaseModel, Field

from app.confidence.schemas import ConfidenceResult

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


class RoutingRecommendRequest(RoutingSimulateRequest):
    """Route, simulate, and return charger recommendations around the route."""

    charger_radius_km: float = Field(default=25.0, gt=0.0)
    charger_limit: int = Field(default=5, ge=1, le=20)
    compatible_only: bool = True
    include_charger_routes: bool = True


class ChargerSearchAnchor(BaseModel):
    """Coordinate used to find charger options."""

    coordinate: Coordinate
    reason: Literal["depletion", "destination"]


class RecommendedCharger(BaseModel):
    """One charger candidate plus confidence and optional Valhalla path."""

    station_id: str
    station_name: str
    address: str | None = None
    lat: float
    lon: float
    connector_types: str | None = None
    total_ports: int | None = None
    max_power_kw: float | None = None
    total_reviews: int | None = None
    be6_compatible: bool
    distance_from_anchor_km: float
    confidence_source: Literal["reviews", "fallback"]
    confidence: ConfidenceResult
    route_status: Literal["generated", "unavailable", "skipped"]
    route_to_charger_edges: list[RouteEdge] | None = None
    route_error: str | None = None


class RoutingRecommendResponse(BaseModel):
    """Primary route, physics result, and ranked charger possibilities."""

    primary_route_edges: list[RouteEdge]
    simulation: SimulateResponse
    charger_search_anchor: ChargerSearchAnchor
    recommended_chargers: list[RecommendedCharger]
