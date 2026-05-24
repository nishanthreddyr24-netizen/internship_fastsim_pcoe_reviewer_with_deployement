"""Convert Valhalla-style route edges into FASTSim drive cycles."""

import math
from typing import Any

from app.physics.fastsim_bridge import import_fastsim
from app.physics.schemas import Coordinate, RouteEdge

fsim = import_fastsim()


class SyntheticCycle:
    """Small cycle stand-in used when the native FASTSim package is unavailable."""

    def __init__(self, data: dict[str, list[float] | float]) -> None:
        self._data = data

    def to_pydict(self, data_fmt: str = "yaml") -> dict[str, Any]:
        return self._data


def _interpolate_coordinate(edge: RouteEdge, fraction: float) -> Coordinate:
    if edge.end_coordinate is None:
        return edge.start_coordinate
    lat = edge.start_coordinate.lat + (edge.end_coordinate.lat - edge.start_coordinate.lat) * fraction
    lon = edge.start_coordinate.lon + (edge.end_coordinate.lon - edge.start_coordinate.lon) * fraction
    return Coordinate(lat=lat, lon=lon)


def valhalla_to_1hz_cycle(
    edges: list[RouteEdge],
    ambient_temp_c: float,
) -> tuple[Any, dict[int, Coordinate]]:
    """Expand route edges to a one-second FASTSim cycle and second-coordinate map."""
    time_seconds = [0.0]
    speed_mps = [0.0]
    grade = [0.0]
    pwr_max_chrg_watts = [0.0]
    temp_amb_air_kelvin = [ambient_temp_c + 273.15]
    pwr_solar_load_watts = [0.0]
    sec_to_coord = {0: edges[0].start_coordinate}
    current_time = 0

    for edge in edges:
        v_mps = max(edge.speed_kph / 3.6, 0.5)
        duration = max(1, int(round(edge.distance_m / v_mps)))
        grade_ratio = edge.grade_pct / 100.0

        for step in range(1, duration + 1):
            current_time += 1
            time_seconds.append(float(current_time))
            speed_mps.append(v_mps)
            grade.append(grade_ratio)
            pwr_max_chrg_watts.append(0.0)
            temp_amb_air_kelvin.append(ambient_temp_c + 273.15)
            pwr_solar_load_watts.append(0.0)
            sec_to_coord[current_time] = _interpolate_coordinate(edge, step / duration)

    cycle_data = {
        "init_elev_meters": 0.0,
        "time_seconds": time_seconds,
        "speed_meters_per_second": speed_mps,
        "grade": grade,
        "pwr_max_chrg_watts": pwr_max_chrg_watts,
        "temp_amb_air_kelvin": temp_amb_air_kelvin,
        "pwr_solar_load_watts": pwr_solar_load_watts,
        "grade_interp": 0.0,
        "elev_interp": 0.0,
    }
    cycle = (
        fsim.Cycle.from_pydict(cycle_data, data_fmt="yaml")
        if fsim is not None
        else SyntheticCycle(cycle_data)
    )
    return cycle, sec_to_coord


def route_distance_m(edges: list[RouteEdge]) -> float:
    """Return total route distance in meters."""
    return math.fsum(edge.distance_m for edge in edges)
