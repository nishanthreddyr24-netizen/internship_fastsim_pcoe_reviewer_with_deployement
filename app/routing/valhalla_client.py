"""HTTP client and adapter for live Valhalla route generation."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.physics.schemas import Coordinate, RouteEdge
from app.physics.valhalla_adapter import compass_heading_deg


class ValhallaError(RuntimeError):
    """Raised when the Valhalla service is unavailable or returns unusable data."""


@dataclass(frozen=True)
class ValhallaClient:
    """Small stdlib-only Valhalla HTTP client."""

    base_url: str
    timeout_s: float = 10.0

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as err:
            detail = err.read().decode("utf-8", errors="replace")
            raise ValhallaError(f"Valhalla {path} returned HTTP {err.code}: {detail}") from err
        except (URLError, TimeoutError, OSError, ValueError) as err:
            raise ValhallaError(f"Valhalla {path} request failed: {err}") from err

    def route(self, start: Coordinate, end: Coordinate, costing: str = "auto") -> dict[str, Any]:
        """Return a Valhalla route response for start/end coordinates."""
        return self._post(
            "route",
            {
                "locations": [
                    {"lat": start.lat, "lon": start.lon},
                    {"lat": end.lat, "lon": end.lon},
                ],
                "costing": costing,
                "directions_options": {"units": "kilometers"},
            },
        )

    def trace_attributes(self, encoded_shape: str, costing: str = "auto") -> dict[str, Any]:
        """Return per-edge attributes for a Valhalla encoded route shape."""
        return self._post(
            "trace_attributes",
            {
                "encoded_polyline": encoded_shape,
                "costing": costing,
                "shape_match": "map_snap",
                "filters": {
                    "attributes": [
                        "edge.length",
                        "edge.speed",
                        "edge.begin_shape_index",
                        "edge.end_shape_index",
                        "shape",
                    ],
                    "action": "include",
                },
            },
        )

    def height(self, start: Coordinate, end: Coordinate) -> tuple[float, float]:
        """Return Skadi elevation in meters for an edge start/end pair."""
        payload = {
            "shape": [
                {"lat": start.lat, "lon": start.lon},
                {"lat": end.lat, "lon": end.lon},
            ],
            "height_precision": 1,
        }
        data = self._post("height", payload)
        heights = data.get("height", [0.0, 0.0])
        try:
            return float(heights[0]), float(heights[1])
        except (TypeError, ValueError, IndexError) as err:
            raise ValhallaError(f"Valhalla height returned invalid payload: {data}") from err


def client_from_env() -> ValhallaClient:
    """Build a Valhalla client from deployment environment variables."""
    base_url = os.getenv("VALHALLA_URL", "http://valhalla:8002")
    timeout_s = float(os.getenv("VALHALLA_TIMEOUT_S", "10.0"))
    return ValhallaClient(base_url=base_url, timeout_s=timeout_s)


def decode_polyline6(encoded: str) -> list[Coordinate]:
    """Decode Valhalla precision-6 polyline geometry."""
    coords: list[Coordinate] = []
    index = 0
    lat = 0
    lon = 0
    while index < len(encoded):
        for is_lon in (False, True):
            shift = 0
            result = 0
            while True:
                if index >= len(encoded):
                    raise ValhallaError("encoded Valhalla shape ended unexpectedly")
                value = ord(encoded[index]) - 63
                index += 1
                result |= (value & 0x1F) << shift
                shift += 5
                if value < 0x20:
                    break
            delta = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += delta
            else:
                lat += delta
        coords.append(Coordinate(lat=lat / 1e6, lon=lon / 1e6))
    return coords


def _shape_points(trace_data: dict[str, Any]) -> list[Coordinate]:
    raw_shape = trace_data.get("shape", [])
    if isinstance(raw_shape, str):
        return decode_polyline6(raw_shape)
    points = []
    for point in raw_shape:
        points.append(Coordinate(lat=float(point["lat"]), lon=float(point["lon"])))
    return points


def _route_leg_shapes(route_data: dict[str, Any]) -> list[str]:
    try:
        legs = route_data["trip"]["legs"]
    except KeyError as err:
        raise ValhallaError(f"Valhalla route response is missing trip.legs: {route_data}") from err
    shapes = [str(leg["shape"]) for leg in legs if leg.get("shape")]
    if not shapes:
        raise ValhallaError(f"Valhalla route response contains no leg shapes: {route_data}")
    return shapes


def route_edges_from_valhalla(
    client: ValhallaClient,
    start: Coordinate,
    end: Coordinate,
    costing: str = "auto",
) -> list[RouteEdge]:
    """Generate FASTSim-ready route edges from live Valhalla HTTP calls."""
    route_data = client.route(start, end, costing)
    edges: list[RouteEdge] = []
    for encoded_shape in _route_leg_shapes(route_data):
        trace_data = client.trace_attributes(encoded_shape, costing)
        shape_points = _shape_points(trace_data)
        if len(shape_points) < 2:
            raise ValhallaError("Valhalla trace_attributes returned fewer than two shape points")

        for raw_edge in trace_data.get("edges", []):
            begin_idx = int(raw_edge.get("begin_shape_index", 0))
            end_idx = int(raw_edge.get("end_shape_index", min(begin_idx + 1, len(shape_points) - 1)))
            begin_idx = max(0, min(begin_idx, len(shape_points) - 1))
            end_idx = max(0, min(end_idx, len(shape_points) - 1))
            start_coord = shape_points[begin_idx]
            end_coord = shape_points[end_idx]
            distance_m = float(raw_edge.get("length", 0.0)) * 1000.0
            if distance_m <= 0.0 or not math.isfinite(distance_m):
                continue

            elev_start, elev_end = client.height(start_coord, end_coord)
            grade_pct = ((elev_end - elev_start) / distance_m) * 100.0
            edges.append(
                RouteEdge(
                    edge_index=len(edges),
                    distance_m=round(distance_m, 3),
                    speed_kph=round(float(raw_edge.get("speed", 0.0)), 3),
                    grade_pct=round(grade_pct, 6),
                    heading_deg=compass_heading_deg(start_coord, end_coord),
                    start_coordinate=start_coord,
                    end_coordinate=end_coord,
                ),
            )

    if not edges:
        raise ValhallaError("Valhalla trace_attributes returned no routable edges")
    return edges
