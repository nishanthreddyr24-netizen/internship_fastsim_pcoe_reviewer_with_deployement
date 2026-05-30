"""Generate FASTSim route edges from local Valhalla tiles.

This helper uses the Python Valhalla binding directly. It is useful for creating
static `route_edges.json` fixtures from a local `custom_files/` bundle, but the
Docker deployment uses the Valhalla HTTP container instead.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
from typing import Iterable

import valhalla


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_START = {"lat": 28.597861, "lon": 77.032485}
DEFAULT_END = {"lat": 28.556000, "lon": 77.100000}


def first_existing(candidates: Iterable[Path], fallback: Path) -> Path:
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return fallback


def default_config_path() -> Path:
    env_path = os.getenv("VALHALLA_CONFIG_FILE")
    if env_path:
        return Path(env_path)
    return first_existing(
        [
            REPO_ROOT / "custom_files" / "valhalla.json",
            REPO_ROOT / "valhalla" / "custom_files" / "valhalla.json",
            Path("C:/valhalla/custom_files/valhalla.json"),
        ],
        REPO_ROOT / "custom_files" / "valhalla.json",
    )


def load_actor(config_file: Path) -> valhalla.Actor:
    if not config_file.exists():
        raise FileNotFoundError(
            f"Valhalla config not found: {config_file}. "
            "Copy valhalla/custom_files into root custom_files/ first."
        )
    return valhalla.Actor(str(config_file))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6_371_000
    radians = math.pi / 180
    delta = (
        math.sin((lat2 - lat1) * radians / 2) ** 2
        + math.cos(lat1 * radians)
        * math.cos(lat2 * radians)
        * math.sin((lon2 - lon1) * radians / 2) ** 2
    )
    return 2 * radius_m * math.asin(math.sqrt(delta))


def decode_polyline6(encoded: str) -> list[dict[str, float]]:
    coords = []
    index = 0
    lat = 0
    lon = 0

    while index < len(encoded):
        for is_lon in (False, True):
            shift = 0
            result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            value = ~(result >> 1) if result & 1 else result >> 1
            if is_lon:
                lon += value
            else:
                lat += value
        coords.append({"lat": lat / 1e6, "lon": lon / 1e6})

    return coords


def valhalla_route(actor: valhalla.Actor, locations: list[dict[str, float]]) -> dict:
    payload = {
        "locations": locations,
        "costing": "auto",
        "directions_options": {"units": "kilometers"},
    }
    return json.loads(actor.route(json.dumps(payload)))


def valhalla_trace(actor: valhalla.Actor, encoded_shape: str) -> dict:
    payload = {
        "encoded_polyline": encoded_shape,
        "costing": "auto",
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
    }
    return json.loads(actor.trace_attributes(json.dumps(payload)))


def get_elevation(
    actor: valhalla.Actor,
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
) -> tuple[float, float]:
    payload = {
        "shape": [{"lat": lat1, "lon": lon1}, {"lat": lat2, "lon": lon2}],
        "height_precision": 1,
    }
    result = json.loads(actor.height(json.dumps(payload)))
    heights = result.get("height", [0.0, 0.0])
    start_height = heights[0] if heights and heights[0] is not None else 0.0
    end_height = heights[1] if len(heights) > 1 and heights[1] is not None else 0.0
    return float(start_height), float(end_height)


def build_route_edges(actor: valhalla.Actor, locations: list[dict[str, float]]) -> dict:
    print(f"Routing through {len(locations)} waypoint(s)")
    route_data = valhalla_route(actor, locations)
    all_edges = []

    for leg_num, leg in enumerate(route_data["trip"]["legs"]):
        print(f"  Processing leg {leg_num + 1}...")
        trace_data = valhalla_trace(actor, leg["shape"])
        edges = trace_data.get("edges", [])
        raw_shape = trace_data.get("shape", "")
        shape_points = decode_polyline6(raw_shape) if raw_shape else []

        for edge in edges:
            start_index = edge.get("begin_shape_index", 0)
            end_index = edge.get("end_shape_index", min(start_index + 1, len(shape_points) - 1))
            start_coord = shape_points[start_index]
            end_coord = shape_points[end_index]

            distance_m = round(edge.get("length", 0) * 1000, 1)
            speed_kph = round(edge.get("speed", 0), 1)
            height_start, height_end = get_elevation(
                actor,
                start_coord["lat"],
                start_coord["lon"],
                end_coord["lat"],
                end_coord["lon"],
            )
            grade_pct = round(((height_end - height_start) / distance_m) * 100, 2) if distance_m else 0.0

            all_edges.append(
                {
                    "edge_index": len(all_edges),
                    "distance_m": distance_m,
                    "speed_kph": speed_kph,
                    "grade_pct": grade_pct,
                    "start_coordinate": start_coord,
                    "end_coordinate": end_coord,
                }
            )

    return {"route_edges": all_edges}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate direct Valhalla route_edges.json")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "route_edges.json")
    parser.add_argument("--start-lat", type=float, default=DEFAULT_START["lat"])
    parser.add_argument("--start-lon", type=float, default=DEFAULT_START["lon"])
    parser.add_argument("--end-lat", type=float, default=DEFAULT_END["lat"])
    parser.add_argument("--end-lon", type=float, default=DEFAULT_END["lon"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    actor = load_actor(args.config)
    result = build_route_edges(
        actor,
        [
            {"lat": args.start_lat, "lon": args.start_lon},
            {"lat": args.end_lat, "lon": args.end_lon},
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f'Done. {len(result["route_edges"])} edges written to {args.output}')


if __name__ == "__main__":
    main()
