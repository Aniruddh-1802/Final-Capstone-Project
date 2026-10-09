"""Analytics response schemas. Every response carries meta that states the denominator and that dates are simulated."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

DENOMINATOR = ("eligible encounters (is_readmission_eligible = 1: expired and hospice discharges excluded); "
               "volumes (encounters, average length of stay) use all active encounters")


class AnalyticsMeta(BaseModel):
    filters: dict[str, Any] = Field(description="shared filters that were applied")
    denominator: str = DENOMINATOR
    dates_simulated: bool = Field(True, description="admission and discharge dates are SIMULATED, so trends are illustrative")
    generated_at: datetime


class GroupRow(BaseModel):
    """One group. readmission_rate is 0-1, or null when the group has no eligible encounters."""

    id: int | None = None
    label: str
    encounters: int
    eligible_encounters: int
    readmitted_30d: int
    readmission_rate: float | None
    small_n: bool = Field(description="true when the group has fewer than 11 encounters; do not over-interpret")
    avg_length_of_stay: float | None = None


class LengthOfStayRow(BaseModel):
    id: int | None = None
    label: str
    encounters: int
    avg_length_of_stay: float | None
    min_length_of_stay: int | None
    max_length_of_stay: int | None
    histogram: list[int] = Field(description="encounters with length of stay 1..14 days (index 0 = 1 day)")
    small_n: bool


class SummaryRow(BaseModel):
    total_encounters: int
    unique_patients: int
    avg_length_of_stay: float | None
    avg_num_medications: float | None
    eligible_encounters: int
    readmitted_30d: int
    readmission_rate_30d: float | None
    any_readmission_rate: float | None


class SummaryResponse(BaseModel):
    data: SummaryRow
    meta: AnalyticsMeta


class GroupResponse(BaseModel):
    data: list[GroupRow]
    meta: AnalyticsMeta


class LengthOfStayResponse(BaseModel):
    data: list[LengthOfStayRow]
    meta: AnalyticsMeta


class MedicationsData(BaseModel):
    top_drugs: list[GroupRow]
    insulin_status: list[GroupRow]
    a1c_result: list[GroupRow]


class MedicationsResponse(BaseModel):
    data: MedicationsData
    meta: AnalyticsMeta
