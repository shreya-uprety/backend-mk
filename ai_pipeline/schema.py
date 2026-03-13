from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class PatientIdentifiers(BaseModel):
    name: str | None = None
    dob: str | None = None
    mrn: str | None = None
    age: str | None = None
    sex: str | None = None


class Section(BaseModel):
    """A flexible section that can represent any type of clinical data.

    Known types: demographics, social_history, lifestyle, referral, lab_results,
    imaging, medications, vitals, consultation_notes, questionnaire,
    assessment_plan, procedure, biopsy — but any string is valid.
    """
    type: str
    title: str = ""
    date: str | None = None
    data: dict[str, Any] | None = None
    items: list[Any] | None = None
    tables: list[dict[str, Any]] | None = None
    findings: dict[str, str] | None = None
    impression: list[str] | None = None
    diagnosis: str | None = None
    summary: str | None = None
    rationale: str | None = None
    immediate_issues: list[str] | None = None
    plan: list[str] | None = None
    qa: list[list[str]] | None = None


class ExtractionMetadata(BaseModel):
    source_images: list[str]
    extraction_date: str
    model_used: str
    confidence: str = "medium"


class PatientRecord(BaseModel):
    """The flexible, unified patient data object produced by the pipeline."""
    patient: PatientIdentifiers
    extraction_metadata: ExtractionMetadata
    sections: list[Section]


class ImageExtraction(BaseModel):
    """Raw extraction from a single image before merging."""
    source_image: str
    sections_found: list[str]
    patient_identifiers: PatientIdentifiers | None = None
    extracted_data: dict[str, Any]
    confidence: str = "medium"
    notes: str | None = None
