"""Schemas for charger confidence scoring."""

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


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
    ocpi_status: dict[str, str] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("ocpi_status", "ocpi_overrides"),
    )
    equipment_age_days: dict[str, int] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("equipment_age_days", "equipment_age_overrides"),
    )


class RankedConfidenceResponse(BaseModel):
    results: list[ConfidenceResult]
