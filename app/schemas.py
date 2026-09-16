from typing import Optional, List
from pydantic import BaseModel, Field

class Change(BaseModel):
    type: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None

class CandidateIndicator(BaseModel):
    indicator_id: str
    standard_name: str
    score: float = Field(ge=0, le=1)

class FinancialRecord(BaseModel):
    raw_indicator: Optional[str] = None
    indicator_id: Optional[str] = None
    standard_indicator: Optional[str] = None
    category: Optional[str] = None
    date: Optional[str] = None
    value: Optional[float] = None
    original_value: Optional[str] = None
    unit: Optional[str] = None
    frequency: Optional[str] = None
    change: Optional[Change] = None
    market: Optional[str] = None
    region: Optional[str] = None
    source: Optional[str] = None
    evidence: Optional[str] = None
    confidence: float = Field(ge=0, le=1)
    status: str = 'pending_review'
    warnings: List[str] = []
    candidates: List[CandidateIndicator] = []

class ExtractionResult(BaseModel):
    input_type: str
    raw_text: Optional[str] = None
    records: List[FinancialRecord] = []
    global_warnings: List[str] = []
    model: Optional[str] = None
    prompt_version: str = 'v1.1'
