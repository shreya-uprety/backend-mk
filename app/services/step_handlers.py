"""Step handlers — auto-execute pipeline functions when a patient reaches certain steps.

Each handler receives the patient_id and the current PatientStatus.
It runs the corresponding pipeline function, stores results in GCS,
and returns one of:
    - None: no handler, stay on this step
    - _AUTO_ADVANCE: handler completed, advance past (no popup needed)
    - a decision string: auto-advance with this decision (for decision steps)
"""
from __future__ import annotations

import json
import logging

from storage import get_storage
from app.models.patient_status import PatientStatus, ProcessStep, LFTPatternType

logger = logging.getLogger(__name__)

_AUTO_ADVANCE = "__auto_advance__"

PREFIX = "patient_status"


def _gcs_path(patient_id: str, filename: str) -> str:
    return f"{PREFIX}/{patient_id}/{filename}"


def _load_prior(patient_id: str, filename: str) -> dict | None:
    """Load a prior result from GCS, returning None if not found."""
    storage = get_storage()
    path = _gcs_path(patient_id, filename)
    if not storage.exists(path):
        return None
    return storage.read_json(path)


def _save_result(patient_id: str, filename: str, data: dict) -> None:
    storage = get_storage()
    storage.write_json(_gcs_path(patient_id, filename), data)


# ── Phase 0: Existing handlers ────────────────────────────────────────


def handle_extract_risk_factors(patient_id: str, status: PatientStatus) -> str | None:
    """Run deterministic risk factor extraction and store enriched payload.

    If enriched_payload.json already exists (pre-computed from scenario), skip.
    """
    existing = _load_prior(patient_id, "enriched_payload.json")
    if existing and "risk_factors" in existing:
        logger.info("Patient %s: risk factors already pre-computed, skipping", patient_id)
        return _AUTO_ADVANCE

    from debate_engine.modules.risk_factor_extractor import extract_risk_factors
    from debate_engine.modules.record_transformer import transform_record_to_payload
    from debate_engine.schemas import PatientPayload

    storage = get_storage()
    record = storage.read_json(f"pipeline_output/{patient_id}/record.json")

    payload_dict = transform_record_to_payload(record)
    payload = PatientPayload(**payload_dict)
    result = extract_risk_factors(payload)

    enriched = payload_dict.copy()
    enriched["risk_factors"] = result.risk_factors.model_dump()
    enriched["derived_metrics"] = result.derived_metrics.model_dump()
    _save_result(patient_id, "enriched_payload.json", enriched)
    _save_result(patient_id, "risk_factors_result.json", result.model_dump())

    logger.info("Patient %s: risk factors extracted", patient_id)
    return _AUTO_ADVANCE


def handle_red_flag_assessment(patient_id: str, status: PatientStatus) -> str | None:
    """Run red flag debate and auto-decide yes/no."""
    from debate_engine.modules.red_flag import analyze_red_flags
    from debate_engine.schemas import PatientPayload

    enriched = _load_prior(patient_id, "enriched_payload.json")
    payload = PatientPayload(**enriched)

    result = analyze_red_flags(payload)
    _save_result(patient_id, "red_flag_result.json", result.model_dump())

    is_red_flag = result.final_decision == "RED_FLAG_PRESENT"
    status.metadata.red_flag_detected = is_red_flag
    status.metadata.red_flag_confidence = result.confidence_score

    logger.info("Patient %s: red flag = %s (%.0f%%)", patient_id, result.final_decision, result.confidence_score * 100)
    return "yes" if is_red_flag else "no"


def handle_analyze_lft_pattern(patient_id: str, status: PatientStatus) -> str | None:
    """Run LFT pattern debate and store result."""
    from debate_engine.modules.pattern_analysis import analyze_pattern
    from debate_engine.schemas import PatientPayload

    enriched = _load_prior(patient_id, "enriched_payload.json")
    payload = PatientPayload(**enriched)

    result = analyze_pattern(payload)
    _save_result(patient_id, "pattern_result.json", result.model_dump())

    classification = result.final_classification.lower()
    try:
        status.metadata.lft_pattern = LFTPatternType(classification)
    except ValueError:
        status.metadata.lft_pattern = LFTPatternType.MIXED
    status.metadata.lft_pattern_confidence = result.confidence_score

    logger.info("Patient %s: pattern = %s (%.0f%%)", patient_id, result.final_classification, result.confidence_score * 100)
    return _AUTO_ADVANCE


def handle_lft_pattern_classification(patient_id: str, status: PatientStatus) -> str | None:
    """Auto-decide LFT pattern classification from stored result."""
    result = _load_prior(patient_id, "pattern_result.json")
    if not result:
        logger.warning("Patient %s: no pattern result, cannot auto-decide", patient_id)
        return None

    classification = result.get("final_classification", "MIXED").lower()
    if classification in ("cholestatic", "hepatitic", "mixed"):
        return classification
    return "mixed"


# ── Phase 1: Investigation Recommendations ─────────────────────────────


def _run_investigation(patient_id: str, status: PatientStatus, prompt_file: str) -> str | None:
    """Shared logic for cholestatic/hepatitic investigation handlers."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")
    pattern_result = _load_prior(patient_id, "pattern_result.json")

    result = call_gemini(
        prompt_file=prompt_file,
        patient_data=enriched,
        extra_context={"pattern_analysis": pattern_result},
    )

    # Clean internal keys
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "investigation_result.json", result)
    logger.info("Patient %s: investigations recommended (%s)", patient_id, prompt_file)
    return _AUTO_ADVANCE


def handle_cholestatic_investigations(patient_id: str, status: PatientStatus) -> str | None:
    """AI recommends imaging and serology for cholestatic pattern."""
    return _run_investigation(patient_id, status, "investigation_cholestatic.md")


def handle_hepatitic_investigations(patient_id: str, status: PatientStatus) -> str | None:
    """AI recommends full liver screen and imaging for hepatitic pattern."""
    return _run_investigation(patient_id, status, "investigation_hepatitic.md")


# ── Phase 2: Diagnostic Dilemma Assessment ─────────────────────────────


def handle_diagnostic_dilemma_assessment(patient_id: str, status: PatientStatus) -> str | None:
    """Run 3-agent diagnostic dilemma debate and auto-decide yes/no."""
    from debate_engine.modules.diagnostic_dilemma import assess_dilemma
    from debate_engine.schemas import PatientPayload

    enriched = _load_prior(patient_id, "enriched_payload.json")
    payload = PatientPayload(**enriched)

    pattern_result = _load_prior(patient_id, "pattern_result.json")
    investigation_result = _load_prior(patient_id, "investigation_result.json")

    extra = {}
    if pattern_result:
        extra["pattern_analysis"] = pattern_result
    if investigation_result:
        extra["investigation_recommendations"] = investigation_result

    result = assess_dilemma(payload, extra_context=extra)
    _save_result(patient_id, "dilemma_result.json", result)

    is_dilemma = result["final_decision"] == "DIAGNOSTIC_DILEMMA"
    status.metadata.diagnostic_dilemma = is_dilemma

    logger.info("Patient %s: dilemma = %s (%.0f%%)", patient_id, result["final_decision"], result["confidence_score"] * 100)
    return "yes" if is_dilemma else "no"


# ── Phase 3: Complex Case Path ─────────────────────────────────────────


def handle_recommend_mri_biopsy_escalate(patient_id: str, status: PatientStatus) -> str | None:
    """AI recommends MRI/biopsy for complex case."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")
    dilemma_result = _load_prior(patient_id, "dilemma_result.json")
    pattern_result = _load_prior(patient_id, "pattern_result.json")
    investigation_result = _load_prior(patient_id, "investigation_result.json")

    result = call_gemini(
        prompt_file="complex_case_recommendation.md",
        patient_data=enriched,
        extra_context={
            "dilemma_assessment": dilemma_result,
            "pattern_analysis": pattern_result,
            "investigations": investigation_result,
        },
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "complex_case_result.json", result)
    logger.info("Patient %s: complex case recommendation generated", patient_id)
    return _AUTO_ADVANCE


def handle_consultant_review_signoff(patient_id: str, status: PatientStatus) -> str | None:
    """Generate consultant summary for MDT review and sign-off."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")

    # Gather all prior results
    prior = {}
    for key, filename in [
        ("risk_factors", "risk_factors_result.json"),
        ("red_flag", "red_flag_result.json"),
        ("pattern_analysis", "pattern_result.json"),
        ("investigations", "investigation_result.json"),
        ("dilemma", "dilemma_result.json"),
        ("complex_case", "complex_case_result.json"),
        ("diagnosis", "diagnosis_result.json"),
        ("education", "education_result.json"),
    ]:
        data = _load_prior(patient_id, filename)
        if data:
            prior[key] = data

    result = call_gemini(
        prompt_file="consultant_summary.md",
        patient_data=enriched,
        extra_context=prior,
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "consultant_summary_result.json", result)
    logger.info("Patient %s: consultant summary generated", patient_id)
    return _AUTO_ADVANCE


# ── Phase 4: Straightforward Path ──────────────────────────────────────


def handle_conduct_consultation(patient_id: str, status: PatientStatus) -> str | None:
    """AI suggests diagnosis for nurse consultation."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")
    pattern_result = _load_prior(patient_id, "pattern_result.json")
    investigation_result = _load_prior(patient_id, "investigation_result.json")

    result = call_gemini(
        prompt_file="diagnosis_suggestion.md",
        patient_data=enriched,
        extra_context={
            "pattern_analysis": pattern_result,
            "investigations": investigation_result,
        },
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "diagnosis_result.json", result)
    logger.info("Patient %s: diagnosis suggested: %s", patient_id, result.get("primary_diagnosis", "unknown"))
    return _AUTO_ADVANCE


def handle_patient_education(patient_id: str, status: PatientStatus) -> str | None:
    """Generate patient education content."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")
    diagnosis_result = _load_prior(patient_id, "diagnosis_result.json")

    result = call_gemini(
        prompt_file="patient_education.md",
        patient_data=enriched,
        extra_context={"diagnosis": diagnosis_result},
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "education_result.json", result)
    logger.info("Patient %s: patient education generated", patient_id)
    return _AUTO_ADVANCE


# ── Phase 5: Monitoring & Discharge ────────────────────────────────────


def handle_ongoing_monitoring_assessment(patient_id: str, status: PatientStatus) -> str | None:
    """AI assesses whether ongoing monitoring is required."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")

    prior = {}
    for key, filename in [
        ("pattern_analysis", "pattern_result.json"),
        ("investigations", "investigation_result.json"),
        ("diagnosis", "diagnosis_result.json"),
        ("consultant_summary", "consultant_summary_result.json"),
    ]:
        data = _load_prior(patient_id, filename)
        if data:
            prior[key] = data

    result = call_gemini(
        prompt_file="monitoring_assessment.md",
        patient_data=enriched,
        extra_context=prior,
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "monitoring_result.json", result)

    monitoring = result.get("monitoring_required", False)
    status.metadata.monitoring_required = monitoring

    logger.info("Patient %s: monitoring = %s", patient_id, monitoring)
    return "yes" if monitoring else "no"


def handle_ai_surveillance_loop(patient_id: str, status: PatientStatus) -> str | None:
    """Configure the AI surveillance monitoring schedule."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")
    monitoring_result = _load_prior(patient_id, "monitoring_result.json")

    result = call_gemini(
        prompt_file="surveillance_setup.md",
        patient_data=enriched,
        extra_context={"monitoring_assessment": monitoring_result},
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "surveillance_result.json", result)
    logger.info("Patient %s: surveillance loop configured", patient_id)
    return None  # terminal step, no advance


# ── Handler registry ──────────────────────────────────────────────────

STEP_HANDLERS: dict[ProcessStep, callable] = {
    # Phase 0: existing
    ProcessStep.EXTRACT_RISK_FACTORS: handle_extract_risk_factors,
    ProcessStep.RED_FLAG_ASSESSMENT: handle_red_flag_assessment,
    ProcessStep.ANALYZE_LFT_PATTERN: handle_analyze_lft_pattern,
    ProcessStep.LFT_PATTERN_CLASSIFICATION: handle_lft_pattern_classification,
    # Phase 1: investigations
    ProcessStep.CHOLESTATIC_INVESTIGATIONS: handle_cholestatic_investigations,
    ProcessStep.HEPATITIC_INVESTIGATIONS: handle_hepatitic_investigations,
    # Phase 2: diagnostic dilemma
    ProcessStep.DIAGNOSTIC_DILEMMA_ASSESSMENT: handle_diagnostic_dilemma_assessment,
    # Phase 3: complex case
    ProcessStep.RECOMMEND_MRI_BIOPSY_ESCALATE: handle_recommend_mri_biopsy_escalate,
    ProcessStep.CONSULTANT_REVIEW_SIGNOFF: handle_consultant_review_signoff,
    # Phase 4: straightforward
    ProcessStep.CONDUCT_CONSULTATION: handle_conduct_consultation,
    ProcessStep.PATIENT_EDUCATION: handle_patient_education,
    # Phase 5: monitoring
    ProcessStep.ONGOING_MONITORING_ASSESSMENT: handle_ongoing_monitoring_assessment,
    ProcessStep.AI_SURVEILLANCE_LOOP: handle_ai_surveillance_loop,
}


def run_step_handler(patient_id: str, status: PatientStatus) -> str | None:
    """Run the handler for the current step, if one exists."""
    handler = STEP_HANDLERS.get(status.current_step)
    if handler is None:
        return None

    logger.info("Patient %s: running handler for %s", patient_id, status.current_step.value)
    return handler(patient_id, status)
