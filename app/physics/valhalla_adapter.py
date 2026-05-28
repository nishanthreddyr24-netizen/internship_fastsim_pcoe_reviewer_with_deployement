"""Offline Valhalla-style route normalization helpers."""

from __future__ import annotations

import math
from typing import Any

from app.physics.schemas import Coordinate, RouteEdge

EARTH_RADIUS_M = 6_371_000.0


def compass_heading_deg(start: Coordinate, end: Coordinate | None) -> float | None:
    """Calculate compass heading from start to end coordinates."""
    if end is None:
        return None

    lat1 = math.radians(start.lat)
    lat2 = math.radians(end.lat)
    delta_lon = math.radians(end.lon - start.lon)
    x = math.sin(delta_lon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta_lon)
    return round((math.degrees(math.atan2(x, y)) + 360.0) % 360.0, 6)


def haversine_distance_m(start: Coordinate, end: Coordinate | None) -> float:
    """Calculate distance between two coordinates."""
    if end is None:
        return 0.0
    lat1 = math.radians(start.lat)
    lat2 = math.radians(end.lat)
    delta_lat = math.radians(end.lat - start.lat)
    delta_lon = math.radians(end.lon - start.lon)
    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    return 2.0 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def route_edges_from_valhalla_payload(payload: dict[str, Any]) -> list[RouteEdge]:
    """Return validated route edges from an offline Valhalla-style fixture."""
    raw_edges = payload.get("route_edges")
    if raw_edges is None:
        raw_edges = payload.get("edges")
    if raw_edges is None:
        raise ValueError("payload does not contain route_edges")

    edges: list[RouteEdge] = []
    for idx, raw_edge in enumerate(raw_edges):
        edge_data = dict(raw_edge)
        edge_data.setdefault("edge_index", idx)
        edge = RouteEdge(**edge_data)
        if edge.heading_deg is None:
            edge = edge.model_copy(update={"heading_deg": compass_heading_deg(edge.start_coordinate, edge.end_coordinate)})
        edges.append(edge)
    return edges


def validate_valhalla_edges(edges: list[RouteEdge]) -> None:
    """Validate the minimum fields needed by the physics bridge."""
    for edge in edges:
        if edge.heading_deg is None:
            raise ValueError(f"route edge {edge.edge_index} is missing heading_deg")
        if not math.isfinite(edge.grade_pct):
            raise ValueError(f"route edge {edge.edge_index} has invalid grade_pct")
        if edge.end_coordinate is None:
            raise ValueError(f"route edge {edge.edge_index} is missing end_coordinate")
