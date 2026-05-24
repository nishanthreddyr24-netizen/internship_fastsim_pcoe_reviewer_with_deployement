"""Tests for charger confidence scoring."""

from datetime import UTC, datetime

import pandas as pd
from fastapi.testclient import TestClient

from app.confidence import service
from app.main import app

client = TestClient(app)


class FakeScorer:
    def score(self, comment: str) -> float:
        return 0.9 if "great" in comment.lower() else 0.1


def fake_reviews() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "station_id": "alpha",
                "station_name": "Alpha Charge",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "operator": "TestCo",
                "rating": 1,
                "comment": "great charging",
                "review_date": pd.Timestamp("2026-05-20T00:00:00Z"),
            },
            {
                "station_id": "alpha",
                "station_name": "Alpha Charge",
                "latitude": 12.9716,
                "longitude": 77.5946,
                "operator": "TestCo",
                "rating": -1,
                "comment": "broken charger",
                "review_date": pd.Timestamp("2026-03-01T00:00:00Z"),
            },
            {
                "station_id": "beta",
                "station_name": "Beta Charge",
                "latitude": 12.9816,
                "longitude": 77.6046,
                "operator": "OtherCo",
                "rating": 1,
                "comment": None,
                "review_date": pd.Timestamp("2026-05-19T00:00:00Z"),
            },
            {
                "station_id": "gamma",
                "station_name": "Gamma Charge",
                "latitude": 14.0,
                "longitude": 79.0,
                "operator": "FarCo",
                "rating": -1,
                "comment": None,
                "review_date": pd.Timestamp("2026-05-19T00:00:00Z"),
            },
        ],
    )


def install_fake_reviews(monkeypatch) -> None:
    monkeypatch.setattr(service, "load_reviews", fake_reviews)
    monkeypatch.setattr(service, "_default_scorer", lambda: FakeScorer())


def test_sentiment_and_rating_fallback(monkeypatch) -> None:
    install_fake_reviews(monkeypatch)
    rows = fake_reviews()

    assert service.review_sentiment_score(rows.iloc[0]) == 0.9
    assert service.review_sentiment_score(rows.iloc[1]) == 0.1
    assert service.review_sentiment_score(rows.iloc[2]) == 0.85
    assert service.rating_fallback_score(0) == 0.50
    assert service.rating_fallback_score(-1) == 0.15


def test_time_decay_gives_newer_reviews_more_weight() -> None:
    now = datetime(2026, 5, 21, tzinfo=UTC)
    newer = service.decay_weight(pd.Timestamp("2026-05-20T00:00:00Z"), now)
    older = service.decay_weight(pd.Timestamp("2026-03-01T00:00:00Z"), now)

    assert newer > older


def test_station_lookup_returns_metadata(monkeypatch) -> None:
    install_fake_reviews(monkeypatch)

    response = client.get("/api/v1/confidence/stations/alpha")
    body = response.json()

    assert response.status_code == 200, body
    assert body["station_name"] == "Alpha Charge"
    assert body["operator"] == "TestCo"
    assert body["latitude"] == 12.9716
    assert body["review_stats"]["review_count"] == 2


def test_nearby_returns_within_radius_sorted_by_confidence(monkeypatch) -> None:
    install_fake_reviews(monkeypatch)

    response = client.get("/api/v1/confidence/nearby?lat=12.9716&lon=77.5946&radius_km=5")
    body = response.json()

    assert response.status_code == 200, body
    assert [item["station_id"] for item in body["results"]] == ["beta", "alpha"]
    assert body["results"][0]["p_fail"] <= body["results"][1]["p_fail"]


def test_rank_accepts_ocpi_and_age_overrides(monkeypatch) -> None:
    install_fake_reviews(monkeypatch)

    response = client.post(
        "/api/v1/confidence/rank",
        json={
            "station_ids": ["alpha", "beta"],
            "ocpi_status": {"beta": "UNAVAILABLE"},
            "equipment_age_days": {"beta": 400},
        },
    )
    body = response.json()

    assert response.status_code == 200, body
    assert body["results"][-1]["station_id"] == "beta"
    assert body["results"][-1]["ocpi_status"] == "UNAVAILABLE"
    assert body["results"][-1]["equipment_age_days"] == 400


def test_unknown_station_returns_404(monkeypatch) -> None:
    install_fake_reviews(monkeypatch)

    response = client.get("/api/v1/confidence/stations/missing")

    assert response.status_code == 404
