"""JSON contracts shared by the runner and local application, never by candidates."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictInt,
    field_validator,
    model_validator,
)

Mode = Literal["ungrouped", "grouped"]
Scenario = Literal["clean", "overlap", "crossing", "lifecycle", "noisy", "delayed", "turning"]
SCENARIOS = ("clean", "overlap", "crossing", "lifecycle", "noisy", "delayed", "turning")
Number = Annotated[float, Field(strict=True, allow_inf_nan=False)]
Vector = tuple[Number, Number]
Time = Annotated[StrictInt, Field(ge=0)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SensorConfig(Contract):
    sensor_id: Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,40}$")]
    interval_ms: Annotated[StrictInt, Field(ge=100, le=10000)] = 1000
    coverage_m: tuple[Number, Number, Number, Number] = (-20, -50, 140, 150)
    noise_m: Annotated[FiniteFloat, Field(ge=0.1, le=20)] = 2.0
    detection_probability: Annotated[FiniteFloat, Field(ge=0, le=1)] = 0.93
    clutter_per_scan: Annotated[FiniteFloat, Field(ge=0, le=10)] = 0.0
    max_delay_ms: Annotated[StrictInt, Field(ge=0, le=30000)] = 0
    outage_start_ms: Annotated[StrictInt, Field(ge=0, le=60000)] = 30000
    outage_ms: Annotated[StrictInt, Field(ge=0, le=60000)] = 0

    @model_validator(mode="after")
    def valid_coverage(self):
        x0, y0, x1, y1 = self.coverage_m
        if x0 >= x1 or y0 >= y1:
            raise ValueError("Coverage bounds must increase")
        return self


class CaseConfig(Contract):
    scenario: Scenario = "crossing"
    seed: Annotated[StrictInt, Field(ge=0, le=2**32 - 1)] = 100
    partition: Literal["tuning", "evaluation"] = "tuning"
    kind: Literal["fixed", "exploratory"] = "fixed"
    object_count: Annotated[StrictInt, Field(ge=1, le=20)] | None = None
    noise_m: Annotated[FiniteFloat, Field(ge=0.1, le=20)] | None = None
    detection_probability: Annotated[FiniteFloat, Field(ge=0, le=1)] | None = None
    outage_ms: Annotated[StrictInt, Field(ge=0, le=30000)] | None = None
    sensors: Annotated[list[SensorConfig], Field(min_length=1, max_length=8)] | None = None

    @model_validator(mode="after")
    def protect_fixed_conditions(self):
        if (self.partition == "tuning") != (self.seed < 1000):
            raise ValueError(
                "Seeds 0–999 are reserved for tuning; evaluation seeds must be >= 1000"
            )
        if self.kind == "fixed" and any(
            value is not None
            for value in (
                self.object_count,
                self.noise_m,
                self.detection_probability,
                self.outage_ms,
                self.sensors,
            )
        ):
            raise ValueError("Changed conditions must be labeled exploratory")
        if self.sensors and len({sensor.sensor_id for sensor in self.sensors}) != len(self.sensors):
            raise ValueError("Sensor IDs must be unique")
        if self.sensors and any(
            value is not None
            for value in (self.noise_m, self.detection_probability, self.outage_ms)
        ):
            raise ValueError("Use either per-sensor settings or global sensor overrides, not both")
        return self


class Observation(Contract):
    observation_id: Annotated[str, Field(min_length=1, max_length=100)]
    sensor_id: str
    measured_at_ms: Time
    arrived_at_ms: Time
    position_m: Vector
    position_cov_m2: tuple[Vector, Vector]
    group_key: str | None = None

    @model_validator(mode="after")
    def check_times_and_covariance(self):
        if self.arrived_at_ms < self.measured_at_ms:
            raise ValueError("Arrival precedes measurement")
        a, b = self.position_cov_m2
        if a[1] != b[0] or a[0] < 0 or b[1] < 0 or a[0] * b[1] < a[1] ** 2:
            raise ValueError("Covariance must be symmetric positive semidefinite")
        return self


class Track(Contract):
    track_id: Annotated[str, Field(min_length=1, max_length=100)]
    position_m: Vector
    velocity_mps: Vector | None = None


class Snapshot(Contract):
    type: Literal["tracks"]
    schema_version: Literal[1]
    step_id: Time
    time_ms: Time
    tracks: Annotated[list[Track], Field(max_length=1000)]

    @field_validator("schema_version", mode="before")
    @classmethod
    def integer_version(cls, value):
        if type(value) is not int:
            raise ValueError("schema_version must be an integer")
        return value

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [track.track_id for track in self.tracks]
        if len(ids) != len(set(ids)):
            raise ValueError("Track IDs must be unique within each snapshot")
        return self


class SystemSpec(Contract):
    id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")]
    name: Annotated[str, Field(min_length=1, max_length=80)]
    version: Annotated[str, Field(min_length=1, max_length=80)]
    command: Annotated[list[str], Field(min_length=1)]
    modes: list[Mode] = ["ungrouped"]
    description: str = ""


class RunRequest(Contract):
    case_id: Annotated[str, Field(pattern=r"^[a-f0-9]{16}$")]
    system_ids: Annotated[list[str], Field(min_length=1, max_length=6)]
    mode: Mode = "ungrouped"


class ExperimentRequest(Contract):
    config: CaseConfig
    system_ids: Annotated[list[str], Field(min_length=1, max_length=6)]
    mode: Mode = "ungrouped"
    suite: bool = False


class BenchmarkRequest(Contract):
    system_ids: Annotated[list[str], Field(min_length=1, max_length=6)]
