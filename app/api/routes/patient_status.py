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
    CONFIRMATION_REQUIRED_STEPS,
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


class ConfirmStepRequest(BaseModel):
    action: str  # "confirm" or "override"
    nurse_notes: str | None = None
    override_decision: str | None = None  # only for "override" on decision steps


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
        import logging
        logger = logging.getLogger(__name__)
        try:
            from debate_engine.modules.risk_factor_extractor import extract_risk_factors
            from debate_engine.schemas import PatientPayload

            # Strip non-payload fields (internal keys, scenario metadata)
            PAYLOAD_KEYS = {"scenario_id", "patient_demographics", "referral_summary",
                            "lft_blood_results", "history_risk_factors"}
            payload_fields = {k: v for k, v in req.scenario.items() if k in PAYLOAD_KEYS}
            payload = PatientPayload(**payload_fields)
            result = extract_risk_factors(payload)

            enriched = payload_fields.copy()
            enriched["risk_factors"] = result.risk_factors.model_dump()
            enriched["derived_metrics"] = result.derived_metrics.model_dump()

            storage = get_storage()
            prefix = f"patient_status/{req.patient_id}"
            storage.write_json(f"{prefix}/enriched_payload.json", enriched)
            storage.write_json(f"{prefix}/risk_factors_result.json", result.model_dump())
            logger.info("Patient %s: scenario pre-computed successfully", req.patient_id)
        except Exception as e:
            logger.error("Patient %s: scenario pre-computation failed: %s", req.patient_id, e)

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
    """Advance the patient one step and run its handler.

    If the step requires nurse confirmation, the step enters
    `awaiting_confirmation` status. The nurse must call /confirm
    before the patient can advance further.

    Decision steps with AI handlers auto-resolve the decision,
    but still pause for confirmation if configured.
    """
    from app.services.step_handlers import run_step_handler

    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")

    # Block if previous step awaiting confirmation
    if status.step_status == StepStatus.AWAITING_CONFIRMATION:
        raise HTTPException(
            400,
            f"Step {status.current_step.value} is awaiting nurse confirmation. "
            f"Call /confirm or /override before advancing."
        )

    try:
        advance_step(status, decision=req.decision)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _save(status)

    # Run handler for the step we landed on
    handler_results = []
    pending_decision = None  # store auto-decision if step needs confirmation

    while True:
        current_step = status.current_step
        current_step_val = current_step.value
        try:
            outcome = run_step_handler(patient_id, status)
        except Exception as e:
            handler_results.append({"step": current_step_val, "error": str(e)})
            _save(status)
            break

        if outcome is None:
            break

        entry = {
            "step": current_step_val,
            "pathway_decision": outcome.pathway_decision,
        }

        needs_confirmation = current_step in CONFIRMATION_REQUIRED_STEPS

        if outcome.action == "stay":
            entry["action"] = "completed"
            if needs_confirmation:
                entry["requires_confirmation"] = True
                status.step_status = StepStatus.AWAITING_CONFIRMATION
            handler_results.append(entry)
            _save(status)
            break

        if outcome.action == "auto_advance":
            entry["action"] = "completed"
            if needs_confirmation:
                entry["requires_confirmation"] = True
                status.step_status = StepStatus.AWAITING_CONFIRMATION
            handler_results.append(entry)
            _save(status)
            break

        if outcome.action == "decide":
            entry["auto_decision"] = outcome.decision

            if needs_confirmation:
                # Pause for confirmation — don't advance yet
                entry["requires_confirmation"] = True
                entry["action"] = "awaiting_confirmation"
                handler_results.append(entry)
                status.step_status = StepStatus.AWAITING_CONFIRMATION
                # Store the pending decision so /confirm can use it
                _store_pending_decision(patient_id, outcome.decision)
                _save(status)
                break
            else:
                # No confirmation needed, advance immediately
                handler_results.append(entry)
                try:
                    advance_step(status, decision=outcome.decision)
                except ValueError as e:
                    entry["error"] = str(e)
                    _save(status)
                    break
                _save(status)
                continue

    resp = status.model_dump()
    if handler_results:
        resp["handler_result"] = handler_results[-1]
        resp["handler_results"] = handler_results
    return resp


def _store_pending_decision(patient_id: str, decision: str) -> None:
    """Store a pending AI decision awaiting nurse confirmation."""
    storage = get_storage()
    storage.write_json(
        f"{STATUS_PREFIX}/{patient_id}/pending_decision.json",
        {"decision": decision},
    )


def _load_pending_decision(patient_id: str) -> str | None:
    """Load the pending AI decision."""
    storage = get_storage()
    path = f"{STATUS_PREFIX}/{patient_id}/pending_decision.json"
    if not storage.exists(path):
        return None
    data = storage.read_json(path)
    return data.get("decision")


def _clear_pending_decision(patient_id: str) -> None:
    storage = get_storage()
    path = f"{STATUS_PREFIX}/{patient_id}/pending_decision.json"
    if storage.exists(path):
        storage.delete(path)


def _save_confirmation(patient_id: str, record: dict) -> None:
    """Append a confirmation record to the patient's confirmations log."""
    storage = get_storage()
    path = f"{STATUS_PREFIX}/{patient_id}/confirmations.json"
    records = storage.read_json(path) if storage.exists(path) else []
    records.append(record)
    storage.write_json(path, records)


@router.post("/{patient_id}/confirm")
async def confirm_step(patient_id: str, req: ConfirmStepRequest):
    """Nurse confirms or overrides the AI result for the current step.

    For decision steps, confirming uses the AI's decision. Overriding
    uses the nurse's override_decision instead.

    After confirmation, the patient advances past the step.
    """
    from datetime import datetime, timezone

    status = _load(patient_id)
    if status is None:
        raise HTTPException(404, f"Patient {patient_id} not found")

    if status.step_status != StepStatus.AWAITING_CONFIRMATION:
        raise HTTPException(400, f"Step {status.current_step.value} is not awaiting confirmation")

    now = datetime.now(timezone.utc).isoformat()
    step_val = status.current_step.value
    pending = _load_pending_decision(patient_id)

    if req.action == "confirm":
        decision = pending  # use AI's decision (None for non-decision steps)
    elif req.action == "override":
        if not req.override_decision:
            raise HTTPException(400, "override_decision is required when action is 'override'")
        decision = req.override_decision
    else:
        raise HTTPException(400, f"Invalid action: {req.action}. Use 'confirm' or 'override'")

    # Record the confirmation
    confirmation = {
        "step": step_val,
        "action": req.action,
        "ai_decision": pending,
        "final_decision": decision,
        "nurse_notes": req.nurse_notes,
        "timestamp": now,
    }
    _save_confirmation(patient_id, confirmation)

    # Set status back to in_progress
    status.step_status = StepStatus.IN_PROGRESS

    # Advance if this was a decision step with a pending decision
    if decision is not None:
        try:
            advance_step(status, decision=decision)
        except ValueError as e:
            _save(status)
            raise HTTPException(400, str(e))

    _clear_pending_decision(patient_id)
    _save(status)

    resp = status.model_dump()
    resp["confirmation"] = confirmation
    return resp


@router.get("/{patient_id}/confirmations")
async def get_confirmations(patient_id: str):
    """Get all nurse confirmations for this patient."""
    storage = get_storage()
    path = f"{STATUS_PREFIX}/{patient_id}/confirmations.json"
    if not storage.exists(path):
        return {"patient_id": patient_id, "confirmations": []}
    records = storage.read_json(path)
    return {"patient_id": patient_id, "confirmations": records}


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
        active_path.add("FINAL_CONSULTANT_SIGNOFF")
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


@router.get("/{patient_id}/pathway-decisions")
async def get_pathway_decisions(patient_id: str):
    """Get all pathway decisions with reasoning for this patient.

    Returns a chronological list of every AI decision made during triage,
    with human-readable explanations of why each path was chosen.
    """
    storage = get_storage()
    path = f"patient_status/{patient_id}/pathway_decisions.json"
    if not storage.exists(path):
        return {"patient_id": patient_id, "decisions": []}
    decisions = storage.read_json(path)
    return {"patient_id": patient_id, "decisions": decisions}


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
        "final_signoff": f"{prefix}/final_signoff_result.json",
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
    """Remove a patient status and all associated GCS artifacts."""
    storage = get_storage()
    path = _status_path(patient_id)
    if not storage.exists(path):
        raise HTTPException(404, f"Patient {patient_id} not found")

    # Delete all files under this patient's prefix
    prefix = f"{STATUS_PREFIX}/{patient_id}/"
    blobs = storage.list_blobs(prefix)
    for blob in blobs:
        storage.delete(blob)

    return {"deleted": patient_id}
