"""API routes for patient status tracking.

Persists patient status to GCS at: patient_status/{patient_id}/status.json
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from storage import get_storage
from app.models.patient_status import (
    PatientStatus,
    ProcessStep,
    StepStatus,
    advance_step,
    TRANSITIONS,
    DECISION_STEPS,
    TERMINAL_STEPS,
)

router = APIRouter(prefix="/api/v1/patient-status", tags=["patient-status"])

STATUS_PREFIX = "patient_status"


def _status_path(patient_id: str) -> str:
    return f"{STATUS_PREFIX}/{patient_id}/status.json"


def _load(patient_id: str) -> PatientStatus | None:
    storage = get_storage()
    path = _status_path(patient_id)
    if not storage.exists(path):
        return None
    data = storage.read_json(path)
    return PatientStatus(**data)


def _save(status: PatientStatus) -> None:
    storage = get_storage()
    storage.write_json(_status_path(status.patient_id), status.model_dump())


class CreatePatientRequest(BaseModel):
    patient_id: str


class AdvanceStepRequest(BaseModel):
    decision: str | None = None


class UpdateMetadataRequest(BaseModel):
    red_flag_confidence: float | None = None
    triage_probability: float | None = None
    lft_pattern_confidence: float | None = None


@router.post("/create")
async def create_patient_status(req: CreatePatientRequest):
    """Create a new patient status tracker at the entry point."""
    if _load(req.patient_id) is not None:
        raise HTTPException(400, f"Patient {req.patient_id} already exists")

    status = PatientStatus(patient_id=req.patient_id)
    status.step_status = StepStatus.IN_PROGRESS
    _save(status)
    return status.model_dump()


@router.get("/{patient_id}")
async def get_patient_status(patient_id: str):
    """Get the current status for a patient."""
    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")
    return status.model_dump()


@router.post("/{patient_id}/advance")
async def advance_patient_step(patient_id: str, req: AdvanceStepRequest):
    """Advance the patient to the next step.

    For decision steps (red_flag, lft_pattern, diagnostic_dilemma, monitoring),
    a `decision` value must be provided.
    """
    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")

    try:
        advance_step(status, decision=req.decision)
    except ValueError as e:
        raise HTTPException(400, str(e))

    _save(status)
    return status.model_dump()


@router.patch("/{patient_id}/metadata")
async def update_metadata(patient_id: str, req: UpdateMetadataRequest):
    """Update confidence/probability metadata for the current step."""
    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")

    if req.red_flag_confidence is not None:
        status.metadata.red_flag_confidence = req.red_flag_confidence
    if req.triage_probability is not None:
        status.metadata.triage_probability = req.triage_probability
    if req.lft_pattern_confidence is not None:
        status.metadata.lft_pattern_confidence = req.lft_pattern_confidence

    _save(status)
    return status.model_dump()


@router.get("/{patient_id}/next-options")
async def get_next_options(patient_id: str):
    """Get the available next steps from the current position."""
    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")

    current = status.current_step

    if current in TERMINAL_STEPS:
        return {"current_step": current.value, "is_terminal": True, "options": []}

    transition = TRANSITIONS.get(current)
    if transition is None:
        return {"current_step": current.value, "is_terminal": False, "options": []}

    if isinstance(transition, dict):
        return {
            "current_step": current.value,
            "is_terminal": False,
            "is_decision": True,
            "options": [
                {"decision": k, "next_step": v.value}
                for k, v in transition.items()
            ],
        }

    return {
        "current_step": current.value,
        "is_terminal": False,
        "is_decision": False,
        "next_step": transition.value,
    }


@router.get("/")
async def list_all_patients():
    """List all tracked patients."""
    storage = get_storage()
    blobs = storage.list_blobs(STATUS_PREFIX)
    status_files = [b for b in blobs if b.endswith("/status.json")]

    patients = []
    for path in status_files:
        data = storage.read_json(path)
        patients.append({
            "patient_id": data["patient_id"],
            "current_step": data["current_step"],
            "step_status": data["step_status"],
            "pathway": data["pathway"],
            "is_archived": data["is_archived"],
        })

    return {"patients": patients}


@router.delete("/{patient_id}")
async def delete_patient_status(patient_id: str):
    """Remove a patient status."""
    storage = get_storage()
    path = _status_path(patient_id)
    if not storage.exists(path):
        raise HTTPException(404, f"Patient {patient_id} not found")

    storage.delete(path)
    return {"deleted": patient_id}
