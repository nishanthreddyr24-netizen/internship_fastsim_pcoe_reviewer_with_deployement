"""FastAPI routes for charger confidence scoring."""

from fastapi import APIRouter, HTTPException, Query

from app.confidence.schemas import ConfidenceResult, RankConfidenceRequest, RankedConfidenceResponse
from app.confidence.service import StationNotFoundError, score_nearby, score_ranked, score_station

router = APIRouter(prefix="/confidence", tags=["confidence"])


@router.get("/stations/{station_id}", response_model=ConfidenceResult)
def station_confidence(station_id: str) -> ConfidenceResult:
    """Return confidence details for one station."""
    try:
        return score_station(station_id)
    except StationNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


@router.get("/nearby", response_model=RankedConfidenceResponse)
def nearby_confidence(
    lat: float = Query(ge=-90.0, le=90.0),
    lon: float = Query(ge=-180.0, le=180.0),
    radius_km: float = Query(default=20.0, gt=0.0),
    limit: int = Query(default=20, ge=1, le=100),
) -> RankedConfidenceResponse:
    """Return stations within radius ranked by lowest failure probability."""
    return RankedConfidenceResponse(results=score_nearby(lat, lon, radius_km, limit))


@router.post("/rank", response_model=RankedConfidenceResponse)
def rank_confidence(request: RankConfidenceRequest) -> RankedConfidenceResponse:
    """Rank explicitly requested stations by confidence."""
    try:
        return RankedConfidenceResponse(
            results=score_ranked(
                request.station_ids,
                request.ocpi_status,
                request.equipment_age_days,
            ),
        )
    except StationNotFoundError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
