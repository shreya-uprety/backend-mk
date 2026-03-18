"""Step handlers — auto-execute pipeline functions when a patient reaches certain steps.

Each handler receives the patient_id and the current PatientStatus.
It runs the corresponding pipeline function, stores results in GCS,
and returns a HandlerOutcome with:
    - action: "stay" | "auto_advance" | "decide"
    - decision: the decision string (only for "decide")
    - pathway_decision: human-readable explanation of why this path was chosen
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

from storage import get_storage
from app.models.patient_status import PatientStatus, ProcessStep, LFTPatternType

logger = logging.getLogger(__name__)

PREFIX = "patient_status"


@dataclass
class HandlerOutcome:
    """Result of a step handler execution."""
    action: str  # "stay", "auto_advance", "decide"
    decision: str | None = None
    pathway_decision: str | None = None  # why this path was chosen


# Convenience constructors
def _stay(pathway_decision: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(action="stay", pathway_decision=pathway_decision)

def _auto_advance(pathway_decision: str | None = None) -> HandlerOutcome:
    return HandlerOutcome(action="auto_advance", pathway_decision=pathway_decision)

def _decide(decision: str, pathway_decision: str) -> HandlerOutcome:
    return HandlerOutcome(action="decide", decision=decision, pathway_decision=pathway_decision)


def _gcs_path(patient_id: str, filename: str) -> str:
    return f"{PREFIX}/{patient_id}/{filename}"


def _load_prior(patient_id: str, filename: str) -> dict | None:
    storage = get_storage()
    path = _gcs_path(patient_id, filename)
    if not storage.exists(path):
        return None
    return storage.read_json(path)


def _save_result(patient_id: str, filename: str, data: dict) -> None:
    storage = get_storage()
    storage.write_json(_gcs_path(patient_id, filename), data)


def _save_pathway_decision(patient_id: str, step: str, decision_text: str, decision_value: str | None = None) -> None:
    """Append a pathway decision to the patient's decision log in GCS."""
    storage = get_storage()
    path = _gcs_path(patient_id, "pathway_decisions.json")
    decisions = storage.read_json(path) if storage.exists(path) else []
    decisions.append({
        "step": step,
        "decision": decision_value,
        "reasoning": decision_text,
    })
    storage.write_json(path, decisions)


# ── Phase 0: Existing handlers ────────────────────────────────────────


def handle_extract_risk_factors(patient_id: str, status: PatientStatus) -> HandlerOutcome:
    """Run deterministic risk factor extraction and store enriched payload."""
    existing = _load_prior(patient_id, "enriched_payload.json")
    if existing and "risk_factors" in existing:
        logger.info("Patient %s: risk factors already pre-computed, skipping", patient_id)
        pd = "Risk factors pre-computed from scenario data. R-factor, ULN multiples, and patient risk profile available."
        _save_pathway_decision(patient_id, "EXTRACT_RISK_FACTORS", pd)
        return _auto_advance(pd)

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

    dm = result.derived_metrics
    rf = result.risk_factors
    pd = (
        f"Risk factors extracted. R-factor: {dm.r_factor.value} ({dm.r_factor.zone} zone). "
        f"Key findings: BMI {rf.bmi_category.value} ({rf.bmi_category.category}), "
        f"alcohol {rf.alcohol_risk.units_weekly} units/week ({rf.alcohol_risk.level}), "
        f"overall lab severity: {dm.overall_lab_severity}."
    )
    _save_pathway_decision(patient_id, "EXTRACT_RISK_FACTORS", pd)
    logger.info("Patient %s: risk factors extracted", patient_id)
    return _auto_advance(pd)


def handle_red_flag_assessment(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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

    conf = f"{result.confidence_score * 100:.0f}%"
    rationale = result.debate_summary.synthesis_rationale if hasattr(result.debate_summary, 'synthesis_rationale') else ""

    if is_red_flag:
        pd = (
            f"RED FLAG PRESENT ({conf} confidence). "
            f"Patient requires immediate escalation to urgent consultant pathway. "
            f"{rationale}"
        )
        decision = "yes"
    else:
        pd = (
            f"No red flags identified ({conf} confidence). "
            f"Patient continues on standard triage pathway for LFT pattern analysis. "
            f"{rationale}"
        )
        decision = "no"

    _save_pathway_decision(patient_id, "RED_FLAG_ASSESSMENT", pd, decision)
    logger.info("Patient %s: red flag = %s (%.0f%%)", patient_id, result.final_decision, result.confidence_score * 100)
    return _decide(decision, pd)


def handle_analyze_lft_pattern(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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

    conf = f"{result.confidence_score * 100:.0f}%"
    r_val = result.r_factor.value if hasattr(result, 'r_factor') and result.r_factor else "N/A"
    rationale = ""
    if hasattr(result, 'debate_summary') and result.debate_summary:
        rationale = result.debate_summary.synthesis_rationale or ""

    pd = (
        f"LFT pattern classified as {result.final_classification} ({conf} confidence, R-factor: {r_val}). "
        f"{rationale}"
    )
    _save_pathway_decision(patient_id, "ANALYZE_LFT_PATTERN", pd)
    logger.info("Patient %s: pattern = %s (%.0f%%)", patient_id, result.final_classification, result.confidence_score * 100)
    return _auto_advance(pd)


def handle_lft_pattern_classification(patient_id: str, status: PatientStatus) -> HandlerOutcome:
    """Auto-decide LFT pattern classification from stored result."""
    result = _load_prior(patient_id, "pattern_result.json")
    if not result:
        logger.warning("Patient %s: no pattern result, cannot auto-decide", patient_id)
        return _stay()

    classification = result.get("final_classification", "MIXED").lower()
    if classification not in ("cholestatic", "hepatitic", "mixed"):
        classification = "mixed"

    pattern_desc = {
        "cholestatic": "Cholestatic/obstructive pattern — proceeding to hepatic imaging (CT/MRI/MRCP) to investigate biliary tree pathology.",
        "hepatitic": "Hepatitic/inflammatory pattern — proceeding to full liver screen and imaging to identify hepatocellular injury cause.",
        "mixed": "Mixed pattern (both hepatocellular and cholestatic features) — proceeding to full liver screen with wider workup.",
    }

    pd = pattern_desc.get(classification, "")
    _save_pathway_decision(patient_id, "LFT_PATTERN_CLASSIFICATION", pd, classification)
    return _decide(classification, pd)


# ── Phase 1: Investigation Recommendations ─────────────────────────────


def _run_investigation(patient_id: str, status: PatientStatus, prompt_file: str) -> HandlerOutcome:
    """Shared logic for cholestatic/hepatitic investigation handlers."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")
    pattern_result = _load_prior(patient_id, "pattern_result.json")

    result = call_gemini(
        prompt_file=prompt_file,
        patient_data=enriched,
        extra_context={"pattern_analysis": pattern_result},
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "investigation_result.json", result)

    invs = result.get("recommended_investigations", [])
    diffs = result.get("differential_diagnoses", [])
    urgency = result.get("overall_urgency", "routine")
    reasoning = result.get("reasoning", "")

    inv_names = ", ".join(i.get("test_name", "") for i in invs[:4])
    diff_names = ", ".join(diffs[:3])

    pd = (
        f"Investigations recommended ({urgency} priority): {inv_names}. "
        f"Differential diagnoses under investigation: {diff_names}. "
        f"{reasoning}"
    )

    step_name = status.current_step.value
    _save_pathway_decision(patient_id, step_name, pd)
    logger.info("Patient %s: investigations recommended (%s)", patient_id, prompt_file)
    return _auto_advance(pd)


def handle_cholestatic_investigations(patient_id: str, status: PatientStatus) -> HandlerOutcome:
    return _run_investigation(patient_id, status, "investigation_cholestatic.md")


def handle_hepatitic_investigations(patient_id: str, status: PatientStatus) -> HandlerOutcome:
    return _run_investigation(patient_id, status, "investigation_hepatitic.md")


# ── Phase 2: Diagnostic Dilemma Assessment ─────────────────────────────


def handle_diagnostic_dilemma_assessment(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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
    conf = f"{result['confidence_score'] * 100:.0f}%"
    rationale = result.get("debate_summary", {}).get("synthesis_rationale", "")

    if is_dilemma:
        factors = ", ".join(result.get("complexity_factors", [])[:3])
        pd = (
            f"DIAGNOSTIC DILEMMA identified ({conf} confidence). "
            f"Complexity factors: {factors}. "
            f"Case requires MDT escalation with MRI/liver biopsy for further investigation. "
            f"{rationale}"
        )
        decision = "yes"
    else:
        pd = (
            f"Straightforward case ({conf} confidence). "
            f"Diagnosis can be confirmed through standard consultation pathway. "
            f"{rationale}"
        )
        decision = "no"

    _save_pathway_decision(patient_id, "DIAGNOSTIC_DILEMMA_ASSESSMENT", pd, decision)
    logger.info("Patient %s: dilemma = %s (%.0f%%)", patient_id, result["final_decision"], result["confidence_score"] * 100)
    return _decide(decision, pd)


# ── Phase 3: Complex Case Path ─────────────────────────────────────────


def handle_recommend_mri_biopsy_escalate(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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

    proc = result.get("recommended_procedure", "further investigation")
    reasoning = result.get("reasoning", "")
    pd = (
        f"Complex case — recommended procedure: {proc}. "
        f"{reasoning}"
    )
    _save_pathway_decision(patient_id, "RECOMMEND_MRI_BIOPSY_ESCALATE", pd)
    logger.info("Patient %s: complex case recommendation generated", patient_id)
    return _auto_advance(pd)


def handle_consultant_review_signoff(patient_id: str, status: PatientStatus) -> HandlerOutcome:
    """Generate consultant summary for MDT review and sign-off."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")

    prior = {}
    for key, filename in [
        ("risk_factors", "risk_factors_result.json"),
        ("red_flag", "red_flag_result.json"),
        ("pattern_analysis", "pattern_result.json"),
        ("investigations", "investigation_result.json"),
        ("dilemma", "dilemma_result.json"),
        ("complex_case", "complex_case_result.json"),
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

    summary = result.get("clinical_summary", "")
    pd = f"Consultant MDT summary generated for review. {summary}"
    _save_pathway_decision(patient_id, "CONSULTANT_REVIEW_SIGNOFF", pd)
    logger.info("Patient %s: consultant summary generated", patient_id)
    return _auto_advance(pd)


# ── Phase 4: Straightforward Path ──────────────────────────────────────


def handle_conduct_consultation(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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

    primary = result.get("primary_diagnosis", "unknown")
    reasoning = result.get("reasoning", "")
    pd = f"Primary diagnosis suggested: {primary}. {reasoning}"
    _save_pathway_decision(patient_id, "CONDUCT_CONSULTATION", pd)
    logger.info("Patient %s: diagnosis suggested: %s", patient_id, primary)
    return _auto_advance(pd)


def handle_patient_education(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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

    explanation = result.get("condition_explanation", "")
    pd = f"Patient education material generated. {explanation}"
    _save_pathway_decision(patient_id, "PATIENT_EDUCATION", pd)
    logger.info("Patient %s: patient education generated", patient_id)
    return _auto_advance(pd)


# ── Phase 5: Monitoring & Discharge ────────────────────────────────────


def handle_ongoing_monitoring_assessment(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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
    reasoning = result.get("reasoning", "")
    schedule = result.get("monitoring_schedule", "")

    if monitoring:
        pd = (
            f"Ongoing monitoring required ({schedule.replace('_', ' ')} schedule). "
            f"Patient enters AI surveillance loop with automated LFT tracking. "
            f"{reasoning}"
        )
        decision = "yes"
    else:
        pd = (
            f"No ongoing monitoring needed. Patient can be safely discharged to GP. "
            f"{reasoning}"
        )
        decision = "no"

    _save_pathway_decision(patient_id, "ONGOING_MONITORING_ASSESSMENT", pd, decision)
    logger.info("Patient %s: monitoring = %s", patient_id, monitoring)
    return _decide(decision, pd)


def handle_ai_surveillance_loop(patient_id: str, status: PatientStatus) -> HandlerOutcome:
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

    interval = result.get("schedule_interval", "").replace("_", " ")
    duration = result.get("total_duration", "")
    reasoning = result.get("reasoning", "")
    pd = f"AI surveillance configured: {interval} for {duration}. {reasoning}"
    _save_pathway_decision(patient_id, "AI_SURVEILLANCE_LOOP", pd)
    logger.info("Patient %s: surveillance loop configured", patient_id)
    return _auto_advance(pd)


def handle_final_consultant_signoff(patient_id: str, status: PatientStatus) -> HandlerOutcome:
    """Generate comprehensive AI summary for consultant final review and sign-off."""
    from debate_engine.single_call import call_gemini

    enriched = _load_prior(patient_id, "enriched_payload.json")

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
        ("monitoring", "monitoring_result.json"),
        ("surveillance", "surveillance_result.json"),
        ("consultant_summary_mdt", "consultant_summary_result.json"),
    ]:
        data = _load_prior(patient_id, filename)
        if data:
            prior[key] = data

    prior["pathway_history"] = [
        {"step": h.step.value, "metadata": h.metadata}
        for h in status.step_history
    ]

    result = call_gemini(
        prompt_file="final_consultant_signoff.md",
        patient_data=enriched,
        extra_context=prior,
    )
    result.pop("_token_usage", None)
    result.pop("_processing_time_ms", None)

    _save_result(patient_id, "final_signoff_result.json", result)

    signoff = result.get("sign_off_statement", "")
    pd = f"Final consultant sign-off summary generated. {signoff}"
    _save_pathway_decision(patient_id, "FINAL_CONSULTANT_SIGNOFF", pd)
    logger.info("Patient %s: final consultant sign-off summary generated", patient_id)
    return _stay(pd)  # terminal step


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
    ProcessStep.FINAL_CONSULTANT_SIGNOFF: handle_final_consultant_signoff,
}


def run_step_handler(patient_id: str, status: PatientStatus) -> HandlerOutcome | None:
    """Run the handler for the current step, if one exists."""
    handler = STEP_HANDLERS.get(status.current_step)
    if handler is None:
        return None

    logger.info("Patient %s: running handler for %s", patient_id, status.current_step.value)
    return handler(patient_id, status)
