from datetime import date
from decimal import Decimal
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

EDUCATION_ENUM = {
    "HS": "High School",
    "AA": "Associates",
    "BA": "Bachelors",
    "MA": "Masters",
    "PHD": "PhD",
    "": None,
    None: None,
}


class LaborRate(BaseModel):
    # Required
    labor_category: str
    hourly_rate: Decimal

    # Optional
    min_experience: Optional[int] = None
    education_level: Optional[str] = None
    schedule: Optional[str] = None
    sin_number: Optional[str] = None
    vendor_name: Optional[str] = None
    contract_number: Optional[str] = None

    # Computed
    source: str = "gsa_calc"
    collected_date: date = None

    @model_validator(mode="before")
    @classmethod
    def set_collected_date(cls, values):
        if not values.get("collected_date"):
            values["collected_date"] = date.today()
        return values

    @field_validator("labor_category")
    @classmethod
    def clean_category(cls, v):
        v = v.strip()[:200]
        if not v:
            raise ValueError("labor_category cannot be blank")
        return v

    @field_validator("hourly_rate", mode="before")
    @classmethod
    def parse_rate(cls, v):
        return round(Decimal(str(v)), 2)

    @field_validator("education_level", mode="before")
    @classmethod
    def map_education(cls, v):
        key = (v or "").strip().upper()
        return EDUCATION_ENUM.get(key, key or None)

    def to_row(self) -> tuple:
        return (
            self.labor_category,
            self.min_experience,
            self.education_level,
            self.hourly_rate,
            self.schedule,
            self.sin_number,
            self.vendor_name,
            self.contract_number,
            self.source,
            self.collected_date,
        )


def extract_results(data: dict) -> list:
    if "hits" in data:
        hits = data["hits"].get("hits", [])
        return [h.get("_source", h) for h in hits]
    elif "results" in data:
        return data["results"]
    return []


def transform_record(raw: dict) -> LaborRate | None:
    try:
        return LaborRate(
            labor_category=raw.get("labor_category"),
            hourly_rate=raw.get("current_price"),
            min_experience=raw.get("min_years_experience"),
            education_level=raw.get("education_level"),
            schedule=raw.get("schedule"),
            sin_number=raw.get("sin"),
            vendor_name=raw.get("vendor_name"),
            contract_number=raw.get("idv_piid"),
        )
    except Exception:
        return None
