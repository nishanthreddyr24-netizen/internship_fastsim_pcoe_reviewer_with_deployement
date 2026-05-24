"""In-process charger confidence scoring backed by India EV reviews."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Protocol

import pandas as pd

from app.confidence.schemas import ConfidenceResult, ReviewStats

REVIEWS_PATH = Path(__file__).resolve().parents[2] / "india_ev_reviews.xlsx"
REVIEWS_SHEET = "india_ev_reviews"
DECAY_HALF_LIFE_DAYS = 30.0


class StationNotFoundError(LookupError):
    """Raised when a station id is absent from the review workbook."""


class SentimentScorer(Protocol):
    def score(self, comment: str) -> float:
        """Return positive sentiment probability in [0, 1]."""


class DistilBertSentimentScorer:
    """Lazy DistilBERT sentiment scorer."""

    def __init__(self) -> None:
        self._pipeline = None

    def _load(self):
        if self._pipeline is None:
            from transformers import pipeline

            self._pipeline = pipeline(
                "sentiment-analysis",
                model="distilbert-base-uncased-finetuned-sst-2-english",
            )
        return self._pipeline

    def score(self, comment: str) -> float:
        result = self._load()(comment, truncation=True)[0]
        label = str(result["label"]).upper()
        model_score = float(result["score"])
        if label == "NEGATIVE":
            return 1.0 - model_score
        return model_score


class SyntheticSentimentScorer:
    """Deterministic scorer for opt-in synthetic endpoint smoke checks."""

    def score(self, comment: str) -> float:
        lowered = comment.lower()
        if "blocked" in lowered or "fault" in lowered:
            return 0.12
        if "working" in lowered or "fast" in lowered:
            return 0.92
        return 0.55


@dataclass(frozen=True)
class ConfidenceInputs:
    ocpi_status: str = "AVAILABLE"
    equipment_age_days: int = 0


@lru_cache(maxsize=1)
def load_reviews() -> pd.DataFrame:
    """Load and normalize the review workbook once per process."""
    if os.getenv("FASTSIM_SYNTHETIC_DATA") == "1":
        return pd.DataFrame(
            [
                {
                    "station_id": "synthetic-alpha",
                    "station_name": "Synthetic Alpha Charge",
                    "latitude": 12.9716,
                    "longitude": 77.5946,
                    "operator": "Synthetic Grid",
                    "rating": 1,
                    "comment": "Working fast charger today",
                    "review_date": pd.Timestamp("2026-05-21T08:00:00Z"),
                },
                {
                    "station_id": "synthetic-alpha",
                    "station_name": "Synthetic Alpha Charge",
                    "latitude": 12.9716,
                    "longitude": 77.5946,
                    "operator": "Synthetic Grid",
                    "rating": -1,
                    "comment": "Connector fault yesterday",
                    "review_date": pd.Timestamp("2026-05-20T08:00:00Z"),
                },
                {
                    "station_id": "synthetic-beta",
                    "station_name": "Synthetic Beta Charge",
                    "latitude": 12.9766,
                    "longitude": 77.5996,
                    "operator": "Synthetic Grid",
                    "rating": 1,
                    "comment": "Working well",
                    "review_date": pd.Timestamp("2026-05-21T09:00:00Z"),
                },
            ],
        )
    df = pd.read_excel(REVIEWS_PATH, sheet_name=REVIEWS_SHEET)
    df["station_id"] = df["station_id"].astype(str)
    df["review_date"] = pd.to_datetime(df["review_date"], errors="coerce", utc=True)
    return df


@lru_cache(maxsize=1)
def _default_scorer() -> DistilBertSentimentScorer | SyntheticSentimentScorer:
    if os.getenv("FASTSIM_SYNTHETIC_DATA") == "1":
        return SyntheticSentimentScorer()
    return DistilBertSentimentScorer()


def rating_fallback_score(rating: float | int | None) -> float:
    """Map explicit rating labels to sentiment probability."""
    if rating is None or pd.isna(rating):
        return 0.50
    if int(rating) == 1:
        return 0.85
    if int(rating) == -1:
        return 0.15
    return 0.50


def review_sentiment_score(row: pd.Series, scorer: SentimentScorer | None = None) -> float:
    """Return transformer sentiment score, falling back to rating when comments are missing."""
    comment = row.get("comment")
    if isinstance(comment, str) and comment.strip():
        active_scorer = scorer or _default_scorer()
        return float(active_scorer.score(comment.strip()))
    return rating_fallback_score(row.get("rating"))


def decay_weight(review_date: pd.Timestamp | None, now: datetime | None = None) -> float:
    """Return the 30-day exponential decay weight for a review timestamp."""
    if review_date is None or pd.isna(review_date):
        return 1.0
    active_now = now or datetime.now(UTC)
    if active_now.tzinfo is None:
        active_now = active_now.replace(tzinfo=UTC)
    delta_days = max(0.0, (active_now - review_date.to_pydatetime()).total_seconds() / 86400.0)
    return math.exp(-(math.log(2.0) / DECAY_HALF_LIFE_DAYS) * delta_days)


def sigmoid(value: float) -> float:
    return 1.0 / (1.0 + math.exp(-value))


def ocpi_failure_signal(ocpi_status: str) -> float:
    return 0.0 if ocpi_status.upper() == "AVAILABLE" else 1.0


def p_fail_from_features(
    ocpi_status: str,
    sentiment_score: float,
    equipment_age_days: int,
) -> float:
    """Apply the charger failure logistic model."""
    x_ocpi = ocpi_failure_signal(ocpi_status)
    x_sentiment_penalty = 1.0 - sentiment_score
    x_age = max(0, equipment_age_days)
    return sigmoid(2.15 * x_ocpi + 1.65 * x_sentiment_penalty + 0.006 * x_age - 1.45)


def _station_rows(station_id: str) -> pd.DataFrame:
    df = load_reviews()
    rows = df[df["station_id"] == str(station_id)]
    if rows.empty:
        raise StationNotFoundError(f"station_id '{station_id}' was not found")
    return rows


def _station_metadata(rows: pd.DataFrame) -> dict:
    first = rows.iloc[0]
    return {
        "station_id": str(first["station_id"]),
        "station_name": str(first["station_name"]),
        "latitude": float(first["latitude"]),
        "longitude": float(first["longitude"]),
        "operator": None if pd.isna(first.get("operator")) else str(first.get("operator")),
    }


def station_review_stats(
    rows: pd.DataFrame,
    scorer: SentimentScorer | None = None,
    now: datetime | None = None,
) -> ReviewStats:
    weighted_scores = []
    weights = []
    for _, row in rows.iterrows():
        weight = decay_weight(row.get("review_date"), now)
        weighted_scores.append(review_sentiment_score(row, scorer) * weight)
        weights.append(weight)

    weighted_review_count = math.fsum(weights)
    average_sentiment = (
        math.fsum(weighted_scores) / weighted_review_count if weighted_review_count else 0.50
    )
    latest = rows["review_date"].max()
    return ReviewStats(
        review_count=int(len(rows)),
        weighted_review_count=round(weighted_review_count, 6),
        average_sentiment=round(average_sentiment, 6),
        latest_review_date=None if pd.isna(latest) else latest.isoformat(),
    )


def score_station(
    station_id: str,
    inputs: ConfidenceInputs | None = None,
    scorer: SentimentScorer | None = None,
    now: datetime | None = None,
) -> ConfidenceResult:
    """Score a single station by id."""
    active_inputs = inputs or ConfidenceInputs()
    rows = _station_rows(station_id)
    metadata = _station_metadata(rows)
    stats = station_review_stats(rows, scorer, now)
    p_fail = p_fail_from_features(
        active_inputs.ocpi_status,
        stats.average_sentiment,
        active_inputs.equipment_age_days,
    )
    return ConfidenceResult(
        **metadata,
        ocpi_status=active_inputs.ocpi_status,
        equipment_age_days=max(0, active_inputs.equipment_age_days),
        p_fail=round(p_fail, 6),
        confidence=round(1.0 - p_fail, 6),
        review_stats=stats,
    )


def haversine_km(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    radius_km = 6371.0088
    phi_a = math.radians(lat_a)
    phi_b = math.radians(lat_b)
    delta_phi = math.radians(lat_b - lat_a)
    delta_lambda = math.radians(lon_b - lon_a)
    hav = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi_a) * math.cos(phi_b) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2.0 * radius_km * math.asin(math.sqrt(hav))


def nearby_station_ids(lat: float, lon: float, radius_km: float, limit: int) -> list[str]:
    """Return unique station ids within a radius, nearest first before scoring."""
    df = load_reviews()
    stations = df.drop_duplicates("station_id").copy()
    stations["distance_km"] = stations.apply(
        lambda row: haversine_km(lat, lon, float(row["latitude"]), float(row["longitude"])),
        axis=1,
    )
    matches = stations[stations["distance_km"] <= radius_km].sort_values("distance_km")
    return matches["station_id"].head(limit).astype(str).tolist()


def score_nearby(
    lat: float,
    lon: float,
    radius_km: float,
    limit: int,
    scorer: SentimentScorer | None = None,
    now: datetime | None = None,
) -> list[ConfidenceResult]:
    station_ids = nearby_station_ids(lat, lon, radius_km, limit)
    results = [score_station(station_id, scorer=scorer, now=now) for station_id in station_ids]
    return sorted(results, key=lambda result: (result.p_fail, result.station_id))[:limit]


def score_ranked(
    station_ids: list[str | int],
    ocpi_status: dict[str, str] | None = None,
    equipment_age_days: dict[str, int] | None = None,
    scorer: SentimentScorer | None = None,
    now: datetime | None = None,
) -> list[ConfidenceResult]:
    statuses = ocpi_status or {}
    ages = equipment_age_days or {}
    results = [
        score_station(
            station_id,
            ConfidenceInputs(
                ocpi_status=statuses.get(str(station_id), "AVAILABLE"),
                equipment_age_days=ages.get(str(station_id), 0),
            ),
            scorer=scorer,
            now=now,
        )
        for station_id in station_ids
    ]
    return sorted(results, key=lambda result: (result.p_fail, result.station_id))
