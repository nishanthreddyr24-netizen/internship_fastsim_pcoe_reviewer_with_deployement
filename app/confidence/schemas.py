"""Schemas for charger confidence scoring."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StationMetadata(BaseModel):
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    operator: str | None = None


class ReviewStats(BaseModel):
    review_count: int
    weighted_review_count: float
    average_sentiment: float
    latest_review_date: str | None = None


class ConfidenceResult(BaseModel):
    station_id: str
    station_name: str
    latitude: float
    longitude: float
    operator: str | None = None
    ocpi_status: str
    equipment_age_days: int
    p_fail: float
    confidence: float
    review_stats: ReviewStats


class RankConfidenceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    station_ids: list[str | int] = Field(min_length=1)
    ocpi_status: dict[str, str] = Field(default_factory=dict)
    equipment_age_days: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_override_keys(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        if "ocpi_status" not in normalized and "ocpi_overrides" in normalized:
            normalized["ocpi_status"] = normalized["ocpi_overrides"]
        if "equipment_age_days" not in normalized and "equipment_age_overrides" in normalized:
            normalized["equipment_age_days"] = normalized["equipment_age_overrides"]
        return normalized


class RankedConfidenceResponse(BaseModel):
    results: list[ConfidenceResult]
