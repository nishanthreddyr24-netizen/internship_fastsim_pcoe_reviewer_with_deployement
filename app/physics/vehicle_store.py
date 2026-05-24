"""Vehicle enrichment CSV lookup and normalization."""

from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from app.physics.schemas import VehicleProfile

DATASET_PATH = Path(__file__).resolve().parents[2] / "vehicles_enrichment_GLOBAL_20260517_0915.csv"


class VehicleNotFoundError(LookupError):
    """Raised when the requested vehicle cannot be found."""


def _clean_number(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return text or None


@lru_cache(maxsize=1)
def load_vehicle_dataset() -> pd.DataFrame:
    """Load the enrichment dataset once per process."""
    return pd.read_csv(DATASET_PATH)


def profile_from_dataset(vehicle_id: str) -> VehicleProfile:
    """Return a normalized vehicle profile from the enrichment CSV."""
    df = load_vehicle_dataset()
    matches = df[df["Vehicle ID"].astype(str) == vehicle_id]
    if matches.empty:
        raise VehicleNotFoundError(f"vehicle_id '{vehicle_id}' was not found")

    row = matches.iloc[0]
    year = _clean_number(row.get("Year From *"))
    return VehicleProfile(
        vehicle_id=str(row["Vehicle ID"]),
        make=_clean_text(row.get("Brand *")),
        model=_clean_text(row.get("Model *")),
        year=int(year) if year is not None else None,
        maxEssKwh=_clean_number(row.get("Battery kWh *")),
        usableEssKwh=_clean_number(row.get("Battery kWh usable"))
        or _clean_number(row.get("Battery kWh *")),
        vehCgM=_clean_number(row.get("Mass kg *")),
        maxMotorKw=_clean_number(row.get("Motor kW")),
        dragCoef=_clean_number(row.get("Drag Cd *")),
        frontalAreaM2=_clean_number(row.get("Frontal A m2 *")),
        wheelRrCoef=_clean_number(row.get("Roll Cr")),
        drivetrainEff=_clean_number(row.get("Drivetrain eff")),
    )


def resolve_vehicle_profile(
    vehicle_id: str | None,
    override: VehicleProfile | None,
) -> VehicleProfile:
    """Merge a dataset profile with optional request-provided overrides."""
    lookup_id = override.vehicle_id if override is not None else vehicle_id
    if lookup_id is None:
        raise VehicleNotFoundError("vehicle_id or vehicle_profile.vehicle_id is required")

    base = profile_from_dataset(lookup_id)
    if override is None:
        return base

    merged = base.model_dump(by_alias=True)
    for key, value in override.model_dump(by_alias=True).items():
        if value is not None:
            merged[key] = value
    return VehicleProfile(**merged)

