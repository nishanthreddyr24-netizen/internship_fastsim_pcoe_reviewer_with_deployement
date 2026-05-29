"""Tests for charger catalog recommendations."""

import pandas as pd

from app.confidence.schemas import ConfidenceResult, ReviewStats
from app.physics.schemas import Coordinate
from app.routing import charger_recommendations as recs
from app.routing.valhalla_client import ValhallaError


def fake_catalog() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "station_id": "reviewed",
                "name": "Reviewed CCS2",
                "address": "Reviewed address",
                "lat": 28.56,
                "lon": 77.10,
                "connector_types": "CCS2",
                "total_ports": 2,
                "max_power_kw": 60.0,
                "total_reviews": 4,
                "be6_compatible": True,
            },
            {
                "station_id": "fallback",
                "name": "Fallback Type2",
                "address": "Fallback address",
                "lat": 28.57,
                "lon": 77.11,
                "connector_types": "Type 2",
                "total_ports": 1,
                "max_power_kw": 22.0,
                "total_reviews": 0,
                "be6_compatible": True,
            },
            {
                "station_id": "incompatible",
                "name": "J1772 Only",
                "address": "Other address",
                "lat": 28.55,
                "lon": 77.09,
                "connector_types": "J-1772",
                "total_ports": 1,
                "max_power_kw": 7.0,
                "total_reviews": 1,
                "be6_compatible": False,
            },
        ],
    )


def reviewed_confidence(station_id: str) -> ConfidenceResult:
    if station_id != "reviewed":
        from app.confidence.service import StationNotFoundError

        raise StationNotFoundError(station_id)
    return ConfidenceResult(
        station_id="reviewed",
        station_name="Reviewed CCS2",
        latitude=28.56,
        longitude=77.10,
        ocpi_status="AVAILABLE",
        equipment_age_days=0,
        p_fail=0.1,
        confidence=0.9,
        review_stats=ReviewStats(
            review_count=4,
            weighted_review_count=3.5,
            average_sentiment=0.9,
            latest_review_date="2026-05-20T00:00:00+00:00",
        ),
    )


def test_candidate_chargers_filters_compatibility_and_uses_fallback(monkeypatch) -> None:
    monkeypatch.setattr(recs, "load_charger_catalog", fake_catalog)
    monkeypatch.setattr(recs, "score_station", reviewed_confidence)

    candidates = recs.candidate_chargers(
        Coordinate(lat=28.556, lon=77.1),
        radius_km=5.0,
        limit=5,
        compatible_only=True,
    )

    station_ids = [row["station_id"] for row, *_ in candidates]
    assert station_ids == ["reviewed", "fallback"]
    assert candidates[0][2] == "reviews"
    assert candidates[1][2] == "fallback"
    assert candidates[1][1].confidence == 0.5


def test_recommended_chargers_keeps_candidate_when_charger_route_fails(monkeypatch) -> None:
    monkeypatch.setattr(recs, "load_charger_catalog", fake_catalog)
    monkeypatch.setattr(recs, "score_station", reviewed_confidence)

    def failing_route(*_args, **_kwargs):
        raise ValhallaError("no route to charger")

    recommendations = recs.recommended_chargers(
        Coordinate(lat=28.556, lon=77.1),
        radius_km=5.0,
        limit=1,
        compatible_only=True,
        include_routes=True,
        valhalla_client=object(),
        costing="auto",
        route_builder=failing_route,
    )

    assert len(recommendations) == 1
    assert recommendations[0].station_id == "reviewed"
    assert recommendations[0].route_status == "unavailable"
    assert recommendations[0].route_to_charger_edges is None
    assert "no route to charger" in recommendations[0].route_error
