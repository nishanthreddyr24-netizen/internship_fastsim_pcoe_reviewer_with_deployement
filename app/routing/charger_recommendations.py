"""Charger catalog loading and route recommendation helpers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Callable

import pandas as pd

from app.confidence.schemas import ConfidenceResult, ReviewStats
from app.confidence.service import StationNotFoundError, haversine_km, score_station
from app.physics.schemas import Coordinate, RouteEdge
from app.routing.schemas import RecommendedCharger
from app.routing.valhalla_client import ValhallaClient, ValhallaError, route_edges_from_valhalla

CATALOG_PATH = Path(
    os.getenv(
        "NORMALIZED_CHARGERS_PATH",
        str(Path(__file__).resolve().parents[2] / "normalized_new_delhi_chargers.csv"),
    ),
)


def _clean_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _clean_int(value: object) -> int | None:
    if value is None or pd.isna(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _clean_float(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


@lru_cache(maxsize=1)
def load_charger_catalog() -> pd.DataFrame:
    """Load normalized charger metadata once per process."""
    df = pd.read_csv(CATALOG_PATH)
    df["station_id"] = df["station_id"].astype(str)
    df["be6_compatible"] = df["be6_compatible"].map(_clean_bool)
    return df


def fallback_confidence(row: pd.Series) -> ConfidenceResult:
    """Return a clearly marked neutral confidence when review rows are absent."""
    return ConfidenceResult(
        station_id=str(row["station_id"]),
        station_name=str(row["name"]),
        latitude=float(row["lat"]),
        longitude=float(row["lon"]),
        operator=None,
        ocpi_status="UNKNOWN",
        equipment_age_days=0,
        p_fail=0.5,
        confidence=0.5,
        review_stats=ReviewStats(
            review_count=0,
            weighted_review_count=0.0,
            average_sentiment=0.5,
            latest_review_date=None,
        ),
    )


def confidence_for_station(row: pd.Series) -> tuple[ConfidenceResult, str]:
    """Score a station from review data, falling back without failing recommendation."""
    try:
        return score_station(str(row["station_id"])), "reviews"
    except StationNotFoundError:
        return fallback_confidence(row), "fallback"


def candidate_chargers(
    anchor: Coordinate,
    radius_km: float,
    limit: int,
    compatible_only: bool = True,
) -> list[tuple[pd.Series, ConfidenceResult, str, float]]:
    """Return charger candidates ranked by confidence, distance, and power."""
    df = load_charger_catalog().copy()
    if compatible_only:
        df = df[df["be6_compatible"]]

    df["distance_from_anchor_km"] = df.apply(
        lambda row: haversine_km(anchor.lat, anchor.lon, float(row["lat"]), float(row["lon"])),
        axis=1,
    )
    df = df[df["distance_from_anchor_km"] <= radius_km]

    candidates = []
    for _, row in df.iterrows():
        confidence, source = confidence_for_station(row)
        distance_km = float(row["distance_from_anchor_km"])
        candidates.append((row, confidence, source, distance_km))

    candidates.sort(
        key=lambda item: (
            -item[1].confidence,
            item[3],
            -float(item[0].get("max_power_kw") or 0.0),
            str(item[0]["station_id"]),
        ),
    )
    return candidates[:limit]


def recommended_chargers(
    anchor: Coordinate,
    radius_km: float,
    limit: int,
    compatible_only: bool,
    include_routes: bool,
    valhalla_client: ValhallaClient,
    costing: str,
    route_builder: Callable[[ValhallaClient, Coordinate, Coordinate, str], list[RouteEdge]]
    = route_edges_from_valhalla,
) -> list[RecommendedCharger]:
    """Return charger recommendations with optional route_edges to each charger."""
    recommendations: list[RecommendedCharger] = []
    for row, confidence, source, distance_km in candidate_chargers(
        anchor,
        radius_km,
        limit,
        compatible_only,
    ):
        charger_coord = Coordinate(lat=float(row["lat"]), lon=float(row["lon"]))
        route_edges = None
        route_status = "skipped"
        route_error = None
        if include_routes:
            try:
                route_edges = route_builder(valhalla_client, anchor, charger_coord, costing)
                route_status = "generated"
            except ValhallaError as err:
                route_status = "unavailable"
                route_error = str(err)

        recommendations.append(
            RecommendedCharger(
                station_id=str(row["station_id"]),
                station_name=str(row["name"]),
                address=_clean_text(row.get("address")),
                lat=float(row["lat"]),
                lon=float(row["lon"]),
                connector_types=_clean_text(row.get("connector_types")),
                total_ports=_clean_int(row.get("total_ports")),
                max_power_kw=_clean_float(row.get("max_power_kw")),
                total_reviews=_clean_int(row.get("total_reviews")),
                be6_compatible=bool(row["be6_compatible"]),
                distance_from_anchor_km=round(distance_km, 6),
                confidence_source=source,
                confidence=confidence,
                route_status=route_status,
                route_to_charger_edges=route_edges,
                route_error=route_error,
            ),
        )
    return recommendations
