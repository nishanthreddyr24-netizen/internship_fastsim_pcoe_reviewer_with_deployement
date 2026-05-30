"""Generate a charger-stop FASTSim route from local Valhalla tiles."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from route import DEFAULT_START, REPO_ROOT, build_route_edges, default_config_path, haversine_m, load_actor


DEFAULT_END = {"lat": 28.5434438, "lon": 77.2063442}


def default_chargers_path() -> Path:
    env_path = os.getenv("VALHALLA_CHARGERS_FILE")
    if env_path:
        return Path(env_path)
    candidates = [
        REPO_ROOT / "valhalla" / "data" / "new_delhi_chargers.json",
        REPO_ROOT / "data" / "new_delhi_chargers.json",
        REPO_ROOT / "new_delhi_chargers.json",
        Path("C:/valhalla/data/new_delhi_chargers.json"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def load_chargers(chargers_file: Path) -> list[dict]:
    if not chargers_file.exists():
        raise FileNotFoundError(f"Charger file not found: {chargers_file}")
    return json.loads(chargers_file.read_text(encoding="utf-8"))


def charger_coordinate(station: dict) -> dict[str, float]:
    coordinates = station.get("coordinates", {})
    if "latitude" in coordinates and "longitude" in coordinates:
        return {"lat": float(coordinates["latitude"]), "lon": float(coordinates["longitude"])}
    if "lat" in coordinates and "lon" in coordinates:
        return {"lat": float(coordinates["lat"]), "lon": float(coordinates["lon"])}
    raise ValueError(f"Station has no supported coordinate shape: {station}")


def charger_near_route(
    chargers: list[dict],
    start: dict[str, float],
    end: dict[str, float],
) -> dict | None:
    best_station = None
    best_score = float("inf")

    for station in chargers:
        coord = charger_coordinate(station)
        score = haversine_m(start["lat"], start["lon"], coord["lat"], coord["lon"]) + haversine_m(
            end["lat"],
            end["lon"],
            coord["lat"],
            coord["lon"],
        )
        if score < best_score:
            best_score = score
            best_station = station

    return best_station


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate charger-stop Valhalla route_edges_charger.json")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--chargers", type=Path, default=default_chargers_path())
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "route_edges_charger.json")
    parser.add_argument("--start-lat", type=float, default=DEFAULT_START["lat"])
    parser.add_argument("--start-lon", type=float, default=DEFAULT_START["lon"])
    parser.add_argument("--end-lat", type=float, default=DEFAULT_END["lat"])
    parser.add_argument("--end-lon", type=float, default=DEFAULT_END["lon"])
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = {"lat": args.start_lat, "lon": args.start_lon}
    end = {"lat": args.end_lat, "lon": args.end_lon}
    chargers = load_chargers(args.chargers)
    charger = charger_near_route(chargers, start, end)
    if charger is None:
        raise RuntimeError("No charging station found near route")

    charger_stop = charger_coordinate(charger)
    print(f"Selected charger: {charger.get('name', charger.get('station_id', 'unknown'))}")
    print(f"Coordinates: {charger_stop}")

    actor = load_actor(args.config)
    result = build_route_edges(actor, [start, charger_stop, end])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f'Done. {len(result["route_edges"])} edges written to {args.output}')


if __name__ == "__main__":
    main()
