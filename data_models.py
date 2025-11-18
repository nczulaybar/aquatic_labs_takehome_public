from pydantic import BaseModel


class Measurement(BaseModel):
    sensor_id: int
    timestamp: str  # ISO format timestamp
    temperature: float
    conductivity: float


class MetricStatistics(BaseModel):
    mean: float
    median: float
    min: float
    max: float


class SummaryStatistics(BaseModel):
    count: int
    temperature: MetricStatistics
    conductivity: MetricStatistics


class SummaryResponse(BaseModel):
    sensor_id: int
    time: int
    window_size: int
    statistics: SummaryStatistics


class SummariesResponse(BaseModel):
    summaries: list[SummaryResponse]


class RawMeasurementsResponse(BaseModel):
    sensor_id: list[int]
    time: list[int]
    temperature: list[float]
    conductivity: list[float]
