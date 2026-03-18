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
    scenario: dict | None = None


class AdvanceStepRequest(BaseModel):
    decision: str | None = None


class UpdateMetadataRequest(BaseModel):
    red_flag_confidence: float | None = None
    triage_probability: float | None = None
    lft_pattern_confidence: float | None = None


@router.post("/create")
async def create_patient_status(req: CreatePatientRequest):
    """Create a new patient status tracker at the entry point.

    If `scenario` is provided (a PatientPayload-format dict), the enriched payload
    is pre-computed and stored so the pipeline handlers work without needing a
    pipeline_output record in GCS.
    """
    if _load(req.patient_id) is not None:
        raise HTTPException(400, f"Patient {req.patient_id} already exists")

    status = PatientStatus(patient_id=req.patient_id)
    status.step_status = StepStatus.IN_PROGRESS
    _save(status)

    if req.scenario:
        try:
            from debate_engine.modules.risk_factor_extractor import extract_risk_factors
            from debate_engine.schemas import PatientPayload

            payload_fields = {k: v for k, v in req.scenario.items() if not k.startswith("_")}
            payload = PatientPayload(**payload_fields)
            result = extract_risk_factors(payload)

            enriched = payload_fields.copy()
            enriched["risk_factors"] = result.risk_factors.model_dump()
            enriched["derived_metrics"] = result.derived_metrics.model_dump()

            storage = get_storage()
            prefix = f"patient_status/{req.patient_id}"
            storage.write_json(f"{prefix}/enriched_payload.json", enriched)
            storage.write_json(f"{prefix}/risk_factors_result.json", result.model_dump())
        except Exception:
            pass

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
    """Advance the patient exactly one step.

    Runs the step handler if one exists for the new step.
    For decision steps with handlers (red_flag, lft_classification),
    the handler auto-resolves the decision and advances past it.

    For manual decision steps (diagnostic_dilemma, monitoring), provide `decision`.
    """
    from app.services.step_handlers import run_step_handler, _AUTO_ADVANCE

    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")

    try:
        advance_step(status, decision=req.decision)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _save(status)

    # Run handlers — if a handler auto-decides, run the next step's handler too
    from app.services.step_handlers import STEP_HANDLERS as _all_handlers

    handler_results = []
    while True:
        current_step = status.current_step.value
        try:
            result = run_step_handler(patient_id, status)
        except Exception as e:
            handler_results.append({"step": current_step, "error": str(e)})
            _save(status)
            break

        if result is None:
            # No handler, or terminal step handler completed
            if status.current_step in _all_handlers:
                handler_results.append({"step": current_step, "action": "completed"})
                _save(status)
            break

        if result == _AUTO_ADVANCE:
            handler_results.append({"step": current_step, "action": "completed"})
            _save(status)
            break

        # Decision step — handler auto-decided, advance and check next handler
        handler_results.append({"step": current_step, "auto_decision": result})
        try:
            advance_step(status, decision=result)
        except ValueError as e:
            handler_results[-1]["error"] = str(e)
            _save(status)
            break
        _save(status)
        continue

    resp = status.model_dump()
    if handler_results:
        resp["handler_result"] = handler_results[-1]
        resp["handler_results"] = handler_results
    return resp


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


@router.get("/{patient_id}/pathway-map")
async def get_pathway_map(patient_id: str):
    """Get the full pathway map showing traversed, current, upcoming, and ruled-out nodes.

    The frontend uses this to render the flowchart with correct node states.
    """
    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")

    traversed = [h.step for h in status.step_history]
    current = status.current_step
    meta = status.metadata

    # All possible steps in the flowchart
    ALL_STEPS = [s.value for s in ProcessStep]

    # Build the active path this patient is on / will be on
    active_path = set(traversed)
    active_path.add(current)

    # Determine upcoming steps based on decisions made so far
    upcoming = []

    # Common steps before first decision
    common_start = [
        "GP_REFERRAL_RECEIVED", "INTAKE_DIGITIZATION", "DASHBOARD_CONFIRMATION",
        "EXTRACT_RISK_FACTORS", "RED_FLAG_ASSESSMENT",
    ]
    for s in common_start:
        active_path.add(s)

    if meta.red_flag_detected is True:
        # Urgent path
        active_path.add("URGENT_CONSULTANT_PATHWAY")
    elif meta.red_flag_detected is False:
        # Standard triage path
        for s in ["PRESENT_TRIAGE_OPTIONS", "GENERATE_GP_LETTER",
                   "ANALYZE_LFT_PATTERN", "LFT_PATTERN_CLASSIFICATION"]:
            active_path.add(s)

        if meta.lft_pattern and meta.lft_pattern.value == "cholestatic":
            active_path.add("CHOLESTATIC_PATTERN")
        elif meta.lft_pattern and meta.lft_pattern.value in ("hepatitic", "mixed"):
            active_path.add("HEPATITIC_PATTERN")

        active_path.add("DIAGNOSTIC_DILEMMA_ASSESSMENT")

        if meta.diagnostic_dilemma is True:
            for s in ["RECOMMEND_MRI_BIOPSY_ESCALATE", "CONSULTANT_MDT_REVIEW",
                       "CONSULTANT_REVIEW_SIGNOFF"]:
                active_path.add(s)
        elif meta.diagnostic_dilemma is False:
            for s in ["CONDUCT_CONSULTATION", "CONFIRM_DIAGNOSIS_EDUCATION"]:
                active_path.add(s)

    active_path.add("ONGOING_MONITORING_ASSESSMENT")

    if meta.monitoring_required is True:
        active_path.add("AI_SURVEILLANCE_LOOP")
    elif meta.monitoring_required is False:
        active_path.add("DISCHARGE_TO_GP")

    # Categorize each step
    traversed_set = set(s.value if hasattr(s, 'value') else s for s in traversed)
    nodes = []
    for step_val in ALL_STEPS:
        if step_val == current.value:
            state = "current"
        elif step_val in traversed_set:
            state = "traversed"
        elif step_val in active_path:
            state = "upcoming"
        else:
            state = "ruled_out"

        nodes.append({"step": step_val, "state": state})

    return {
        "patient_id": status.patient_id,
        "pathway": status.pathway.value,
        "is_archived": status.is_archived,
        "final_disposition": status.final_disposition.value if status.final_disposition else None,
        "nodes": nodes,
    }


@router.get("/{patient_id}/step-result/{step_name}")
async def get_step_result(patient_id: str, step_name: str):
    """Get the stored AI result for a specific step (for popups)."""
    storage = get_storage()
    prefix = f"patient_status/{patient_id}"

    file_map = {
        "risk_factors": f"{prefix}/risk_factors_result.json",
        "red_flag": f"{prefix}/red_flag_result.json",
        "pattern": f"{prefix}/pattern_result.json",
        "investigation": f"{prefix}/investigation_result.json",
        "dilemma": f"{prefix}/dilemma_result.json",
        "complex_case": f"{prefix}/complex_case_result.json",
        "consultant_summary": f"{prefix}/consultant_summary_result.json",
        "diagnosis": f"{prefix}/diagnosis_result.json",
        "education": f"{prefix}/education_result.json",
        "monitoring": f"{prefix}/monitoring_result.json",
        "surveillance": f"{prefix}/surveillance_result.json",
    }

    path = file_map.get(step_name)
    if not path:
        raise HTTPException(400, f"Unknown step result: {step_name}")
    if not storage.exists(path):
        raise HTTPException(404, f"No result found for {step_name}")

    return storage.read_json(path)


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
