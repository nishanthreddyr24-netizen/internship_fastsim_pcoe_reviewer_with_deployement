"""Request and response schemas for route simulation."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.physics.battery import BatteryCorrection


class Coordinate(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)


class RouteEdge(BaseModel):
    edge_index: int = Field(ge=0)
    distance_m: float = Field(gt=0.0)
    speed_kph: float = Field(ge=0.0)
    grade_pct: float = 0.0
    start_coordinate: Coordinate
    end_coordinate: Coordinate | None = None


class VehicleProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    vehicle_id: str
    make: str | None = None
    model: str | None = None
    year: int | None = None
    max_ess_kwh: float | None = Field(default=None, alias="maxEssKwh", gt=0.0)
    usable_ess_kwh: float | None = Field(default=None, alias="usableEssKwh", gt=0.0)
    veh_cg_m: float | None = Field(default=None, alias="vehCgM", gt=0.0)
    max_motor_kw: float | None = Field(default=None, alias="maxMotorKw", gt=0.0)
    drag_coef: float | None = Field(default=None, alias="dragCoef", gt=0.0)
    frontal_area_m2: float | None = Field(default=None, alias="frontalAreaM2", gt=0.0)
    wheel_rr_coef: float | None = Field(default=None, alias="wheelRrCoef", gt=0.0)
    drivetrain_eff: float | None = Field(default=None, alias="drivetrainEff", gt=0.0, le=1.0)
    state_of_health: float = Field(default=1.0, ge=0.0, le=1.0)


class CustomEVProfile(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    scenario_name: str | None = Field(default=None, alias="scenarioName")
    veh_pt_type: int = Field(default=1, alias="vehPtType")
    drag_coef: float = Field(alias="dragCoef", gt=0.0)
    frontal_area_m2: float = Field(alias="frontalAreaM2", gt=0.0)
    veh_cg_m: float = Field(alias="vehCgM", gt=0.0)
    max_ess_kwh: float = Field(alias="maxEssKwh", gt=0.0)
    max_motor_kw: float = Field(alias="maxMotorKw", gt=0.0)
    wheel_rr_coef: float = Field(default=0.008, alias="wheelRrCoef", gt=0.0)
    state_of_health: float = Field(default=1.0, alias="stateOfHealth", ge=0.0, le=1.0)

    def to_vehicle_profile(self) -> VehicleProfile:
        """Convert the FASTSim-style custom profile into the service profile."""
        return VehicleProfile(
            vehicle_id=self.name,
            make=None,
            model=self.name,
            maxEssKwh=self.max_ess_kwh,
            usableEssKwh=self.max_ess_kwh,
            vehCgM=self.veh_cg_m,
            maxMotorKw=self.max_motor_kw,
            dragCoef=self.drag_coef,
            frontalAreaM2=self.frontal_area_m2,
            wheelRrCoef=self.wheel_rr_coef,
            state_of_health=self.state_of_health,
        )


class Environment(BaseModel):
    ambient_temp_c: float = 25.0


class SimulateRequest(BaseModel):
    vehicle_id: str | None = None
    vehicle_profile: VehicleProfile | None = None
    custom_ev_profile: CustomEVProfile | None = None
    environment: Environment = Field(default_factory=Environment)
    route_edges: list[RouteEdge] = Field(min_length=1)
    starting_soc: float = Field(gt=0.0, le=1.0)
    protection_soc: float = Field(default=0.10, ge=0.0, lt=1.0)


class VehicleSummary(BaseModel):
    vehicle_id: str
    make: str | None
    model: str | None
    year: int | None
    usable_ess_kwh: float
    effective_kwh: float
    mass_kg: float
    max_motor_kw: float
    drag_coef: float
    frontal_area_m2: float
    wheel_rr_coef: float


class SimulateResponse(BaseModel):
    status: Literal["route_completed", "depletion_triggered"]
    depletion_coordinate: Coordinate | None
    depletion_second: int | None
    effective_kwh_allocated: float
    final_soc: float
    min_soc: float
    route_duration_s: int
    route_distance_m: float
    soc_timeline: list[float]
    vehicle: VehicleSummary
    battery_correction: BatteryCorrection
