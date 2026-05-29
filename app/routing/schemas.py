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


class RoutingPlanRequest(RoutingRecommendRequest):
    """SOC-aware multi-stop route planning request."""

    target_soc_after_charge: float = Field(default=0.70, gt=0.0, le=1.0)
    max_charging_stops: int = Field(default=3, ge=0, le=10)
    fallback_charger_power_kw: float = Field(default=22.0, gt=0.0)
    include_leg_edges: bool = True


class ConsideredCharger(BaseModel):
    """Candidate charger considered during one failed leg."""

    charger: RecommendedCharger
    reachable: bool
    arrival_soc: float | None = None
    reason: str | None = None


class DrivePlanStep(BaseModel):
    """One drive leg in a multi-stop plan."""

    step_type: Literal["drive"] = "drive"
    from_coordinate: Coordinate
    to_coordinate: Coordinate
    to_label: str
    route_edges: list[RouteEdge] | None = None
    simulation: SimulateResponse


class ChargePlanStep(BaseModel):
    """One charging stop in a multi-stop plan."""

    step_type: Literal["charge"] = "charge"
    station_id: str
    station_name: str
    coordinate: Coordinate
    arrival_soc: float
    departure_soc: float
    energy_added_kwh: float
    estimated_charge_minutes: float
    charger_power_kw: float
    charge_estimate_source: Literal["catalog_power", "fallback_power"]
    confidence: ConfidenceResult


class RoutingPlanResponse(BaseModel):
    """SOC-aware multi-stop route plan."""

    status: Literal["destination_reached", "planning_failed", "max_stops_exceeded"]
    plan_steps: list[DrivePlanStep | ChargePlanStep]
    chargers_considered: list[list[ConsideredCharger]]
    final_soc: float
    total_distance_m: float
    total_drive_time_s: int
    total_estimated_charge_minutes: float
