"""Environmental adjustment helpers for FASTSim route inputs."""

from __future__ import annotations

import math

from app.physics.schemas import Environment, RouteEdge, VehicleState

SAFE_DEFAULT_RR_COEF = 0.012
WET_ROAD_RAIN_THRESHOLD_MM = 2.0
WET_ROAD_RR_MULTIPLIER = 1.15


def normalize_degrees(value: float) -> float:
    """Return a compass bearing in the inclusive 0-360 range used by the API."""
    normalized = value % 360.0
    return 360.0 if normalized == 0.0 and value > 0.0 else normalized


def effective_aero_speed_kph(
    vehicle_speed_kph: float,
    heading_deg: float | None,
    wind_speed_kph: float,
    wind_direction_deg: float,
) -> float:
    """Return the air speed seen by the vehicle's frontal area.

    The integration contract treats wind_direction_deg as the direction the wind
    is moving toward. A direct headwind is therefore 180 degrees from the vehicle
    heading.
    """
    if wind_speed_kph <= 0.0 or heading_deg is None:
        return vehicle_speed_kph

    headwind_axis = (heading_deg + 180.0) % 360.0
    angle_delta = math.radians((wind_direction_deg - headwind_axis + 180.0) % 360.0 - 180.0)
    headwind_component = wind_speed_kph * math.cos(angle_delta)
    return max(0.0, vehicle_speed_kph + headwind_component)


def adjusted_rolling_resistance(
    base_rr_coef: float | None,
    precipitation_mm: float,
    override_rr_coef: float | None = None,
) -> float:
    """Apply the vehicle DB fallback, request override, and wet-road penalty."""
    rr_coef = override_rr_coef or base_rr_coef or SAFE_DEFAULT_RR_COEF
    if precipitation_mm > WET_ROAD_RAIN_THRESHOLD_MM and override_rr_coef is None:
        rr_coef *= WET_ROAD_RR_MULTIPLIER
    return round(rr_coef, 6)


def estimate_hvac_power_kw(ambient_temp_c: float, override_kw: float | None = None) -> float:
    """Estimate auxiliary HVAC power from a 22C target cabin temperature."""
    if override_kw is not None:
        return round(override_kw, 4)

    delta_c = abs(ambient_temp_c - 22.0)
    if delta_c <= 3.0:
        return 0.45
    if ambient_temp_c >= 35.0:
        return 4.0
    if ambient_temp_c <= 5.0:
        return 3.5
    return round(min(3.0, 0.45 + (delta_c - 3.0) * 0.12), 4)


def edge_wind_direction(edge: RouteEdge, environment: Environment) -> float:
    """Prefer edge-specific wind direction when provided."""
    return edge.wind_direction_deg if edge.wind_direction_deg is not None else environment.wind_direction_deg


def request_hvac_power_kw(environment: Environment, vehicle_state: VehicleState | None) -> float:
    """Return explicit or estimated HVAC power for a request."""
    override = vehicle_state.hvac_power_kw if vehicle_state is not None else None
    return estimate_hvac_power_kw(environment.ambient_temp_c, override)


def request_rr_override(vehicle_state: VehicleState | None) -> float | None:
    """Return request-level rolling resistance override when supplied."""
    return vehicle_state.adjusted_rr_coef if vehicle_state is not None else None
