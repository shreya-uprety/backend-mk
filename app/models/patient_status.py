"""Patient Status tracking through the MedForce MK clinical pathway.

Tracks a patient's progress from GP referral through triage, debate,
consultation, and final disposition (surveillance or discharge).
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ── Enums ─────────────────────────────────────────────────────────────


class ProcessStep(str, Enum):
    """All steps in the MedForce MK clinical pathway."""

    # Entry
    GP_REFERRAL_RECEIVED = "GP_REFERRAL_RECEIVED"

    # Intake
    INTAKE_DIGITIZATION = "INTAKE_DIGITIZATION"
    DASHBOARD_CONFIRMATION = "DASHBOARD_CONFIRMATION"
    EXTRACT_RISK_FACTORS = "EXTRACT_RISK_FACTORS"

    # Red flag decision
    RED_FLAG_ASSESSMENT = "RED_FLAG_ASSESSMENT"
    URGENT_CONSULTANT_PATHWAY = "URGENT_CONSULTANT_PATHWAY"
    PRESENT_TRIAGE_OPTIONS = "PRESENT_TRIAGE_OPTIONS"

    # GP letter & LFT analysis
    GENERATE_GP_LETTER = "GENERATE_GP_LETTER"
    ANALYZE_LFT_PATTERN = "ANALYZE_LFT_PATTERN"

    # LFT pattern decision
    LFT_PATTERN_CLASSIFICATION = "LFT_PATTERN_CLASSIFICATION"
    CHOLESTATIC_PATTERN = "CHOLESTATIC_PATTERN"
    HEPATITIC_PATTERN = "HEPATITIC_PATTERN"

    # Investigation recommendations (after pattern classification)
    CHOLESTATIC_INVESTIGATIONS = "CHOLESTATIC_INVESTIGATIONS"
    HEPATITIC_INVESTIGATIONS = "HEPATITIC_INVESTIGATIONS"

    # Diagnostic dilemma decision
    DIAGNOSTIC_DILEMMA_ASSESSMENT = "DIAGNOSTIC_DILEMMA_ASSESSMENT"

    # Dilemma = YES path (complex case)
    RECOMMEND_MRI_BIOPSY_ESCALATE = "RECOMMEND_MRI_BIOPSY_ESCALATE"
    CONSULTANT_MDT_REVIEW = "CONSULTANT_MDT_REVIEW"
    CONSULTANT_REVIEW_SIGNOFF = "CONSULTANT_REVIEW_SIGNOFF"

    # Dilemma = NO path (straightforward)
    CONDUCT_CONSULTATION = "CONDUCT_CONSULTATION"
    CONFIRM_DIAGNOSIS_EDUCATION = "CONFIRM_DIAGNOSIS_EDUCATION"
    PATIENT_EDUCATION = "PATIENT_EDUCATION"

    # Monitoring decision
    ONGOING_MONITORING_ASSESSMENT = "ONGOING_MONITORING_ASSESSMENT"

    # Surveillance
    AI_SURVEILLANCE_LOOP = "AI_SURVEILLANCE_LOOP"
    FINAL_CONSULTANT_SIGNOFF = "FINAL_CONSULTANT_SIGNOFF"

    # Terminal states
    DISCHARGE_TO_GP = "DISCHARGE_TO_GP"


class StepStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    SKIPPED = "skipped"


class Pathway(str, Enum):
    STANDARD_TRIAGE = "standard_triage"
    URGENT_CONSULTANT = "urgent_consultant"


class FinalDisposition(str, Enum):
    SURVEILLANCE = "surveillance"
    DISCHARGED = "discharged"


class LFTPatternType(str, Enum):
    CHOLESTATIC = "cholestatic"
    HEPATITIC = "hepatitic"
    MIXED = "mixed"


# ── Models ────────────────────────────────────────────────────────────


class StepHistoryEntry(BaseModel):
    step: ProcessStep
    status: StepStatus
    entered_at: str
    completed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PatientStatusMetadata(BaseModel):
    red_flag_detected: bool | None = None
    red_flag_confidence: float | None = None
    triage_probability: float | None = None
    lft_pattern: LFTPatternType | None = None
    lft_pattern_confidence: float | None = None
    diagnostic_dilemma: bool | None = None
    monitoring_required: bool | None = None


class PatientStatus(BaseModel):
    patient_id: str
    current_step: ProcessStep = ProcessStep.GP_REFERRAL_RECEIVED
    step_status: StepStatus = StepStatus.PENDING
    pathway: Pathway = Pathway.STANDARD_TRIAGE
    started_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: PatientStatusMetadata = Field(default_factory=PatientStatusMetadata)
    step_history: list[StepHistoryEntry] = Field(default_factory=list)
    is_archived: bool = False
    final_disposition: FinalDisposition | None = None


# ── Terminal steps ────────────────────────────────────────────────────

TERMINAL_STEPS = {
    ProcessStep.FINAL_CONSULTANT_SIGNOFF,
    ProcessStep.DISCHARGE_TO_GP,
}

# ── Decision steps (require a decision value to advance) ──────────────

DECISION_STEPS = {
    ProcessStep.RED_FLAG_ASSESSMENT,
    ProcessStep.LFT_PATTERN_CLASSIFICATION,
    ProcessStep.DIAGNOSTIC_DILEMMA_ASSESSMENT,
    ProcessStep.ONGOING_MONITORING_ASSESSMENT,
}


# ── State machine: step transitions ──────────────────────────────────

# For non-decision steps, maps current_step → next_step.
# For decision steps, maps current_step → {decision_value: next_step}.

TRANSITIONS: dict[ProcessStep, ProcessStep | dict[str, ProcessStep]] = {
    ProcessStep.GP_REFERRAL_RECEIVED: ProcessStep.INTAKE_DIGITIZATION,
    ProcessStep.INTAKE_DIGITIZATION: ProcessStep.DASHBOARD_CONFIRMATION,
    ProcessStep.DASHBOARD_CONFIRMATION: ProcessStep.EXTRACT_RISK_FACTORS,
    ProcessStep.EXTRACT_RISK_FACTORS: ProcessStep.RED_FLAG_ASSESSMENT,

    # Decision: Red flag
    ProcessStep.RED_FLAG_ASSESSMENT: {
        "yes": ProcessStep.URGENT_CONSULTANT_PATHWAY,
        "no": ProcessStep.PRESENT_TRIAGE_OPTIONS,
    },

    ProcessStep.URGENT_CONSULTANT_PATHWAY: ProcessStep.ONGOING_MONITORING_ASSESSMENT,
    ProcessStep.PRESENT_TRIAGE_OPTIONS: ProcessStep.GENERATE_GP_LETTER,
    ProcessStep.GENERATE_GP_LETTER: ProcessStep.ANALYZE_LFT_PATTERN,
    ProcessStep.ANALYZE_LFT_PATTERN: ProcessStep.LFT_PATTERN_CLASSIFICATION,

    # Decision: LFT pattern
    ProcessStep.LFT_PATTERN_CLASSIFICATION: {
        "cholestatic": ProcessStep.CHOLESTATIC_PATTERN,
        "hepatitic": ProcessStep.HEPATITIC_PATTERN,
        "mixed": ProcessStep.HEPATITIC_PATTERN,  # mixed follows hepatitic path (wider workup)
    },

    ProcessStep.CHOLESTATIC_PATTERN: ProcessStep.CHOLESTATIC_INVESTIGATIONS,
    ProcessStep.HEPATITIC_PATTERN: ProcessStep.HEPATITIC_INVESTIGATIONS,

    # Investigations → diagnostic dilemma
    ProcessStep.CHOLESTATIC_INVESTIGATIONS: ProcessStep.DIAGNOSTIC_DILEMMA_ASSESSMENT,
    ProcessStep.HEPATITIC_INVESTIGATIONS: ProcessStep.DIAGNOSTIC_DILEMMA_ASSESSMENT,

    # Decision: Diagnostic dilemma
    ProcessStep.DIAGNOSTIC_DILEMMA_ASSESSMENT: {
        "yes": ProcessStep.RECOMMEND_MRI_BIOPSY_ESCALATE,
        "no": ProcessStep.CONDUCT_CONSULTATION,
    },

    # Dilemma YES path (complex case)
    ProcessStep.RECOMMEND_MRI_BIOPSY_ESCALATE: ProcessStep.CONSULTANT_MDT_REVIEW,
    ProcessStep.CONSULTANT_MDT_REVIEW: ProcessStep.CONSULTANT_REVIEW_SIGNOFF,
    ProcessStep.CONSULTANT_REVIEW_SIGNOFF: ProcessStep.ONGOING_MONITORING_ASSESSMENT,

    # Dilemma NO path (straightforward)
    ProcessStep.CONDUCT_CONSULTATION: ProcessStep.CONFIRM_DIAGNOSIS_EDUCATION,
    ProcessStep.CONFIRM_DIAGNOSIS_EDUCATION: ProcessStep.PATIENT_EDUCATION,
    ProcessStep.PATIENT_EDUCATION: ProcessStep.ONGOING_MONITORING_ASSESSMENT,

    # Decision: Ongoing monitoring
    ProcessStep.ONGOING_MONITORING_ASSESSMENT: {
        "yes": ProcessStep.AI_SURVEILLANCE_LOOP,
        "no": ProcessStep.DISCHARGE_TO_GP,
    },

    # Surveillance → final consultant sign-off → end
    ProcessStep.AI_SURVEILLANCE_LOOP: ProcessStep.FINAL_CONSULTANT_SIGNOFF,
}


# ── State machine logic ──────────────────────────────────────────────


def advance_step(
    status: PatientStatus,
    decision: str | None = None,
) -> PatientStatus:
    """Advance the patient to the next step in the pathway.

    Args:
        status: Current patient status.
        decision: Required for decision steps (e.g., "yes"/"no", "cholestatic"/"hepatitic").

    Returns:
        Updated PatientStatus with the new step and history entry.

    Raises:
        ValueError: If at a terminal step or missing/invalid decision.
    """
    now = datetime.now(timezone.utc).isoformat()
    current = status.current_step

    if current in TERMINAL_STEPS:
        raise ValueError(f"Cannot advance from terminal step: {current.value}")

    transition = TRANSITIONS.get(current)
    if transition is None:
        raise ValueError(f"No transition defined for step: {current.value}")

    # Decision step — requires a decision value
    if isinstance(transition, dict):
        if decision is None:
            raise ValueError(
                f"Step {current.value} is a decision point. "
                f"Provide a decision: {list(transition.keys())}"
            )
        decision_lower = decision.lower()
        next_step = transition.get(decision_lower)
        if next_step is None:
            raise ValueError(
                f"Invalid decision '{decision}' for step {current.value}. "
                f"Valid options: {list(transition.keys())}"
            )
    else:
        next_step = transition

    # Record completed step in history
    status.step_history.append(
        StepHistoryEntry(
            step=current,
            status=StepStatus.COMPLETED,
            entered_at=status.updated_at,
            completed_at=now,
            metadata=_build_step_metadata(current, decision, status),
        )
    )

    # Apply side effects based on the decision
    _apply_decision_side_effects(status, current, decision, next_step)

    # Update current step
    status.current_step = next_step
    status.step_status = StepStatus.IN_PROGRESS
    status.updated_at = now

    # Check if we reached a terminal state
    if next_step in TERMINAL_STEPS:
        status.step_status = StepStatus.COMPLETED
        status.is_archived = True
        if next_step == ProcessStep.FINAL_CONSULTANT_SIGNOFF:
            status.final_disposition = FinalDisposition.SURVEILLANCE
        elif next_step == ProcessStep.DISCHARGE_TO_GP:
            status.final_disposition = FinalDisposition.DISCHARGED

    return status


def _apply_decision_side_effects(
    status: PatientStatus,
    step: ProcessStep,
    decision: str | None,
    next_step: ProcessStep,
) -> None:
    """Update metadata and pathway based on decision outcomes."""
    if step == ProcessStep.RED_FLAG_ASSESSMENT and decision:
        is_red_flag = decision.lower() == "yes"
        status.metadata.red_flag_detected = is_red_flag
        if is_red_flag:
            status.pathway = Pathway.URGENT_CONSULTANT
            status.step_status = StepStatus.ESCALATED

    elif step == ProcessStep.LFT_PATTERN_CLASSIFICATION and decision:
        try:
            status.metadata.lft_pattern = LFTPatternType(decision.lower())
        except ValueError:
            pass

    elif step == ProcessStep.DIAGNOSTIC_DILEMMA_ASSESSMENT and decision:
        status.metadata.diagnostic_dilemma = decision.lower() == "yes"

    elif step == ProcessStep.ONGOING_MONITORING_ASSESSMENT and decision:
        status.metadata.monitoring_required = decision.lower() == "yes"


def _build_step_metadata(
    step: ProcessStep,
    decision: str | None,
    status: PatientStatus,
) -> dict[str, Any]:
    """Build metadata dict to store in step history."""
    meta: dict[str, Any] = {}
    if decision:
        meta["decision"] = decision.lower()

    if step == ProcessStep.RED_FLAG_ASSESSMENT:
        if status.metadata.red_flag_confidence is not None:
            meta["confidence"] = status.metadata.red_flag_confidence
    elif step == ProcessStep.LFT_PATTERN_CLASSIFICATION:
        if status.metadata.lft_pattern_confidence is not None:
            meta["confidence"] = status.metadata.lft_pattern_confidence
    elif step == ProcessStep.PRESENT_TRIAGE_OPTIONS:
        if status.metadata.triage_probability is not None:
            meta["probability"] = status.metadata.triage_probability

    return meta
