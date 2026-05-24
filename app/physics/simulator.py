"""FASTSim-backed route simulation."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from app.physics.battery import BatteryCorrection, battery_correction
from app.physics.cycle_bridge import route_distance_m, valhalla_to_1hz_cycle
from app.physics.fastsim_bridge import import_fastsim
from app.physics.schemas import (
    Coordinate,
    SimulateRequest,
    SimulateResponse,
    VehicleProfile,
    VehicleSummary,
)
from app.physics.vehicle_store import resolve_vehicle_profile

fsim = import_fastsim()

JOULES_PER_KWH = 3_600_000.0
BEV_TEMPLATE = "2022_Renault_Zoe_ZE50_R135.yaml"
ENERGY_KEY = "veh.pt_type.BEV.res.history.energy_out_chemical_joules"


class VehicleProfileError(ValueError):
    """Raised when a vehicle profile lacks required simulation fields."""


def _required_float(profile: VehicleProfile, attr: str) -> float:
    value = getattr(profile, attr)
    if value is None or not math.isfinite(float(value)) or float(value) <= 0.0:
        raise VehicleProfileError(f"vehicle profile is missing required field '{attr}'")
    return float(value)


def _usable_kwh(profile: VehicleProfile) -> float:
    usable = profile.usable_ess_kwh or profile.max_ess_kwh
    if usable is None:
        raise VehicleProfileError("vehicle profile is missing usable_ess_kwh/max_ess_kwh")
    return float(usable)


def build_fastsim_vehicle(
    profile: VehicleProfile,
    ambient_temp_c: float = 25.0,
) -> tuple[Any, VehicleSummary, BatteryCorrection]:
    """Patch a BEV FASTSim template with enrichment-dataset vehicle values."""
    if fsim is None:
        raise VehicleProfileError("FASTSim is not installed")

    usable_kwh = _usable_kwh(profile)
    correction = battery_correction(usable_kwh, profile.state_of_health, ambient_temp_c)
    effective_kwh = correction.effective_kwh
    mass_kg = _required_float(profile, "veh_cg_m")
    max_motor_kw = _required_float(profile, "max_motor_kw")
    drag_coef = _required_float(profile, "drag_coef")
    frontal_area_m2 = _required_float(profile, "frontal_area_m2")
    wheel_rr_coef = float(profile.wheel_rr_coef or 0.008)

    template = fsim.Vehicle.from_resource(BEV_TEMPLATE)
    data = template.to_pydict(data_fmt="yaml")
    bev = data["pt_type"]["BEV"]

    data["mass_kilograms"] = mass_kg
    data["chassis"]["drag_coef"] = drag_coef
    data["chassis"]["frontal_area_square_meters"] = frontal_area_m2
    data["chassis"]["wheel_rr_coef"] = wheel_rr_coef
    bev["em"]["pwr_out_max_watts"] = max_motor_kw * 1000.0
    bev["res"]["energy_capacity_joules"] = effective_kwh * JOULES_PER_KWH
    bev["res"]["pwr_out_max_watts"] = max(bev["res"]["pwr_out_max_watts"], max_motor_kw * 1500.0)
    bev["res"]["state"]["soh"] = profile.state_of_health
    bev["res"]["min_soc"] = 0.0
    bev["res"]["max_soc"] = 1.0

    vehicle = fsim.Vehicle.from_pydict(data, data_fmt="yaml")
    vehicle.set_save_interval(1)
    return vehicle, VehicleSummary(
        vehicle_id=profile.vehicle_id,
        make=profile.make,
        model=profile.model,
        year=profile.year,
        usable_ess_kwh=usable_kwh,
        effective_kwh=round(effective_kwh, 4),
        mass_kg=mass_kg,
        max_motor_kw=max_motor_kw,
        drag_coef=drag_coef,
        frontal_area_m2=frontal_area_m2,
        wheel_rr_coef=wheel_rr_coef,
    ), correction


def _sim_params() -> fsim.SimParams:
    if fsim is None:
        raise VehicleProfileError("FASTSim is not installed")
    params = fsim.SimParams.default().to_pydict(data_fmt="yaml")
    params["trace_miss_opts"] = "Allow"
    return fsim.SimParams.from_pydict(params, data_fmt="yaml")


def _soc_timeline_from_energy(
    starting_soc: float,
    effective_kwh: float,
    energy_out_joules: list[float],
) -> list[float]:
    capacity_joules = effective_kwh * JOULES_PER_KWH
    soc = starting_soc - (np.array(energy_out_joules, dtype=float) / capacity_joules)
    return np.clip(soc, 0.0, 1.0).round(6).tolist()


def _depletion(
    soc_timeline: list[float],
    coord_map: dict[int, Coordinate],
    protection_soc: float,
) -> tuple[str, int | None, Coordinate | None]:
    for idx, active_soc in enumerate(soc_timeline):
        if active_soc <= protection_soc:
            fallback_second = max(coord_map)
            return "depletion_triggered", idx, coord_map.get(idx, coord_map[fallback_second])
    return "route_completed", None, None


def _history_energy(sim_drive: fsim.SimDrive) -> list[float]:
    data = sim_drive.to_pydict(flatten=True)
    values = data.get(ENERGY_KEY)
    if not values:
        raise RuntimeError("FASTSim produced no battery energy history")
    return values


def _vehicle_summary_from_profile(
    profile: VehicleProfile,
    ambient_temp_c: float,
) -> tuple[VehicleSummary, BatteryCorrection]:
    usable_kwh = _usable_kwh(profile)
    correction = battery_correction(usable_kwh, profile.state_of_health, ambient_temp_c)
    return VehicleSummary(
        vehicle_id=profile.vehicle_id,
        make=profile.make,
        model=profile.model,
        year=profile.year,
        usable_ess_kwh=usable_kwh,
        effective_kwh=round(correction.effective_kwh, 4),
        mass_kg=_required_float(profile, "veh_cg_m"),
        max_motor_kw=_required_float(profile, "max_motor_kw"),
        drag_coef=_required_float(profile, "drag_coef"),
        frontal_area_m2=_required_float(profile, "frontal_area_m2"),
        wheel_rr_coef=float(profile.wheel_rr_coef or 0.008),
    ), correction


def _synthetic_energy_history(
    request: SimulateRequest,
    summary: VehicleSummary,
) -> tuple[list[float], dict[int, Coordinate]]:
    """Estimate cumulative battery output per second without FASTSim installed."""
    _, coord_map = valhalla_to_1hz_cycle(
        request.route_edges,
        request.environment.ambient_temp_c,
    )
    energy_out_joules = [0.0]
    cumulative_joules = 0.0
    air_density = 1.184
    gravity = 9.80665
    drivetrain_eff = 0.88
    regen_eff = 0.55
    aux_watts = 450.0 + max(0.0, abs(request.environment.ambient_temp_c - 22.0) - 3.0) * 35.0

    for edge in request.route_edges:
        v_mps = max(edge.speed_kph / 3.6, 0.5)
        duration = max(1, int(round(edge.distance_m / v_mps)))
        grade_ratio = edge.grade_pct / 100.0
        rolling_watts = summary.mass_kg * gravity * summary.wheel_rr_coef * v_mps
        aero_watts = (
            0.5
            * air_density
            * summary.drag_coef
            * summary.frontal_area_m2
            * v_mps**3
        )
        grade_watts = summary.mass_kg * gravity * grade_ratio * v_mps
        tractive_watts = rolling_watts + aero_watts + grade_watts + aux_watts
        if tractive_watts >= 0.0:
            battery_watts = tractive_watts / drivetrain_eff
        else:
            battery_watts = tractive_watts * regen_eff

        for _ in range(duration):
            cumulative_joules = max(0.0, cumulative_joules + battery_watts)
            energy_out_joules.append(cumulative_joules)

    return energy_out_joules, coord_map


def _simulate_route_synthetic(
    request: SimulateRequest,
    profile: VehicleProfile,
) -> SimulateResponse:
    summary, correction = _vehicle_summary_from_profile(
        profile,
        request.environment.ambient_temp_c,
    )
    energy_out_joules, coord_map = _synthetic_energy_history(request, summary)
    soc_timeline = _soc_timeline_from_energy(
        request.starting_soc,
        summary.effective_kwh,
        energy_out_joules,
    )
    status, depletion_second, depletion_coordinate = _depletion(
        soc_timeline,
        coord_map,
        request.protection_soc,
    )

    return SimulateResponse(
        status=status,
        depletion_coordinate=depletion_coordinate,
        depletion_second=depletion_second,
        effective_kwh_allocated=summary.effective_kwh,
        final_soc=soc_timeline[-1],
        min_soc=min(soc_timeline),
        route_duration_s=max(coord_map),
        route_distance_m=route_distance_m(request.route_edges),
        soc_timeline=soc_timeline,
        vehicle=summary,
        battery_correction=correction,
    )


def simulate_route(request: SimulateRequest) -> SimulateResponse:
    """Run a route simulation and return depletion/SOC outputs."""
    if request.custom_ev_profile is not None:
        profile = request.custom_ev_profile.to_vehicle_profile()
    else:
        profile = resolve_vehicle_profile(request.vehicle_id, request.vehicle_profile)

    if fsim is None:
        return _simulate_route_synthetic(request, profile)

    vehicle, summary, correction = build_fastsim_vehicle(
        profile,
        request.environment.ambient_temp_c,
    )
    cycle, coord_map = valhalla_to_1hz_cycle(
        request.route_edges,
        request.environment.ambient_temp_c,
    )

    sim_drive = fsim.SimDrive(vehicle, cycle, _sim_params())
    try:
        sim_drive.walk()
    except RuntimeError:
        # Very long synthetic corridors can physically deplete before the route ends.
        # FASTSim raises once the vehicle can no longer solve the next step; the
        # completed history up to that second is still the signal the router needs.
        pass

    soc_timeline = _soc_timeline_from_energy(
        request.starting_soc,
        summary.effective_kwh,
        _history_energy(sim_drive),
    )
    status, depletion_second, depletion_coordinate = _depletion(
        soc_timeline,
        coord_map,
        request.protection_soc,
    )

    return SimulateResponse(
        status=status,
        depletion_coordinate=depletion_coordinate,
        depletion_second=depletion_second,
        effective_kwh_allocated=summary.effective_kwh,
        final_soc=soc_timeline[-1],
        min_soc=min(soc_timeline),
        route_duration_s=max(coord_map),
        route_distance_m=route_distance_m(request.route_edges),
        soc_timeline=soc_timeline,
        vehicle=summary,
        battery_correction=correction,
    )
