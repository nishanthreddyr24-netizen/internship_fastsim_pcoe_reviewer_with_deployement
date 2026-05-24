"""Battery capacity correction rules for route simulation."""

from pydantic import BaseModel


class BatteryCorrection(BaseModel):
    base_kwh: float
    soh_factor: float
    thermal_factor: float
    effective_kwh: float
    ambient_temp_c: float


def thermal_capacity_factor(ambient_temp_c: float) -> float:
    """Return the NASA-calibrated thermal battery capacity factor."""
    if ambient_temp_c >= 25.0:
        return 1.0
    if ambient_temp_c <= -25.0:
        return 0.58

    raw_factor = -0.000114 * ambient_temp_c**2 + 0.005720 * ambient_temp_c + 0.924
    return min(1.0, max(0.58, raw_factor))


def battery_correction(
    usable_kwh: float,
    state_of_health: float,
    ambient_temp_c: float,
) -> BatteryCorrection:
    """Compute adjusted available battery energy for simulation."""
    thermal_factor = thermal_capacity_factor(ambient_temp_c)
    effective_kwh = usable_kwh * state_of_health * thermal_factor
    return BatteryCorrection(
        base_kwh=round(usable_kwh, 4),
        soh_factor=round(state_of_health, 6),
        thermal_factor=round(thermal_factor, 6),
        effective_kwh=round(effective_kwh, 4),
        ambient_temp_c=ambient_temp_c,
    )
