"""Module 0: Risk Factor Extractor.

Fully deterministic — NO Gemini call. All risk factor classifications
are simple rule-based threshold logic. Derived metrics are computed
mathematically. Runs in <10ms.
"""
from __future__ import annotations
import re
import time
from datetime import datetime, timezone

from debate_engine.config import ULN, GEMINI_MODEL
from debate_engine.schemas import (
    PatientPayload, RiskFactorResponse, Completeness,
    RiskFactors, AlcoholRisk, BMICategory, DiabetesStatus,
    CancerHistory, SymptomSeverity, LiverDiseaseHistory,
    DerivedMetrics, RFactor, ULNMultiples, ASTALTRatio,
    ProcessingMetadata, TokenUsage,
)


# ── Red flag symptom keywords ────────────────────────────────────────────

_JAUNDICE_KW = ["jaundice", "yellowing", "yellow eyes", "yellow skin", "icteric", "icterus"]
_WEIGHT_LOSS_KW = ["weight loss", "lost weight", "unintentional weight"]
_MASS_KW = ["mass", "lump", "palpable", "swelling", "hepatomegaly"]
_DARK_URINE_KW = ["dark urine", "pale stool", "pale stools", "clay-colored", "tea-colored"]
_PAIN_SEVERE_KW = ["severe pain", "intense pain", "acute pain", "excruciating"]
_PAIN_MODERATE_KW = ["pain", "discomfort", "ache", "tenderness"]


def _match_any(text: str, keywords: list[str]) -> bool:
    """Case-insensitive check if any keyword appears in text."""
    lower = text.lower()
    return any(kw in lower for kw in keywords)


def _classify_alcohol(units: float) -> AlcoholRisk:
    if units == 0:
        level = "none"
    elif units <= 7:
        level = "low"
    elif units <= 21:
        level = "moderate"
    elif units <= 35:
        level = "high"
    else:
        level = "very_high"
    return AlcoholRisk(
        units_weekly=units,
        level=level,
        exceeds_guidelines=units > 14,
    )


def _classify_bmi(bmi: float) -> BMICategory:
    if bmi < 18.5:
        cat = "underweight"
    elif bmi < 25:
        cat = "normal"
    elif bmi < 30:
        cat = "overweight"
    elif bmi < 40:
        cat = "obese"
    else:
        cat = "morbidly_obese"
    return BMICategory(value=bmi, category=cat)


def _classify_diabetes(comorbidities: list[str]) -> DiabetesStatus:
    joined = " ".join(comorbidities).lower()
    if "type 2 diabetes" in joined or "t2dm" in joined or "type 2 dm" in joined:
        return DiabetesStatus(present=True, type="type_2")
    if "type 1 diabetes" in joined or "t1dm" in joined or "type 1 dm" in joined:
        return DiabetesStatus(present=True, type="type_1")
    if "gestational diabetes" in joined:
        return DiabetesStatus(present=True, type="gestational")
    if "diabetes" in joined:
        return DiabetesStatus(present=True, type="unspecified")
    return DiabetesStatus(present=False, type="none")


def _classify_cancer(comorbidities: list[str]) -> CancerHistory:
    joined = " ".join(comorbidities).lower()
    cancer_types = []
    # Scan for cancer keywords
    cancer_patterns = [
        "breast cancer", "lung cancer", "colon cancer", "colorectal cancer",
        "liver cancer", "pancreatic cancer", "prostate cancer", "ovarian cancer",
        "lymphoma", "leukaemia", "leukemia", "melanoma", "carcinoma", "cancer",
    ]
    for pat in cancer_patterns:
        if pat in joined:
            cancer_types.append(pat.title())

    if not cancer_types:
        return CancerHistory(present=False, types=[], metastasis_risk="none")

    # Assess remission
    if "remission" in joined:
        # Try to find years
        match = re.search(r"remission\s*(\d+)\s*year", joined)
        if match:
            years = int(match.group(1))
            risk = "low" if years > 5 else "moderate"
        else:
            risk = "moderate"
    elif "active" in joined or "metastatic" in joined or "stage" in joined:
        risk = "high"
    else:
        risk = "moderate"

    return CancerHistory(present=True, types=cancer_types, metastasis_risk=risk)


def _classify_symptoms(symptoms: list[str]) -> SymptomSeverity:
    joined = " ".join(symptoms)
    jaundice = _match_any(joined, _JAUNDICE_KW)
    weight_loss = _match_any(joined, _WEIGHT_LOSS_KW)
    mass = _match_any(joined, _MASS_KW)
    dark_urine = _match_any(joined, _DARK_URINE_KW)

    # Pain severity
    if _match_any(joined, _PAIN_SEVERE_KW):
        pain = "severe"
    elif _match_any(joined, _PAIN_MODERATE_KW):
        pain = "moderate"
    else:
        pain = "none"

    has_red_flag = jaundice or weight_loss or mass or dark_urine

    # Clean symptom list
    cleaned = [s for s in symptoms if s.lower() not in ("none", "")]

    return SymptomSeverity(
        has_red_flag_symptoms=has_red_flag,
        jaundice=jaundice,
        weight_loss=weight_loss,
        abdominal_mass=mass,
        dark_urine_pale_stools=dark_urine,
        pain_severity=pain,
        symptom_list=cleaned if cleaned else ["asymptomatic"],
    )


def _compute_derived_metrics(labs: dict) -> DerivedMetrics:
    alt = labs["ALT_IU_L"]
    ast = labs["AST_IU_L"]
    alp = labs["ALP_IU_L"]
    bili = labs["Bilirubin_umol_L"]
    albumin = labs["Albumin_g_L"]
    ggt = labs["GGT_IU_L"]

    alt_uln = round(alt / ULN["ALT"], 2)
    ast_uln = round(ast / ULN["AST"], 2)
    alp_uln = round(alp / ULN["ALP"], 2)
    bili_uln = round(bili / ULN["Bilirubin"], 2)
    ggt_uln = round(ggt / ULN["GGT"], 2)

    r_value = round(alt_uln / alp_uln, 2) if alp_uln > 0 else 0
    r_zone = "cholestatic" if r_value < 2 else ("hepatitic" if r_value > 5 else "mixed")
    r_formula = (
        f"(ALT/ULN) / (ALP/ULN) = ({alt}/{ULN['ALT']}) / ({alp}/{ULN['ALP']}) "
        f"= {alt_uln} / {alp_uln}"
    )

    ast_alt = round(ast / alt, 2) if alt > 0 else 0
    if ast_alt < 1.0:
        ast_alt_interp = "AST:ALT <1.0 — suggests NAFLD over alcoholic liver disease"
    elif ast_alt > 2.0:
        ast_alt_interp = "AST:ALT >2.0 — suggests alcoholic liver disease or cirrhosis"
    else:
        ast_alt_interp = "AST:ALT 1.0-2.0 — non-specific, could be either aetiology"

    if albumin >= 40:
        alb_status = "normal"
    elif albumin >= 35:
        alb_status = "low_normal"
    elif albumin >= 28:
        alb_status = "low"
    else:
        alb_status = "critically_low"

    max_uln = max(alt_uln, ast_uln, alp_uln, bili_uln, ggt_uln)
    if max_uln <= 1.0:
        severity = "normal"
    elif max_uln <= 2.0:
        severity = "mildly_elevated"
    elif max_uln <= 5.0:
        severity = "moderately_elevated"
    elif max_uln <= 10.0:
        severity = "severely_elevated"
    else:
        severity = "critical"

    return DerivedMetrics(
        r_factor=RFactor(value=r_value, formula=r_formula, zone=r_zone),
        uln_multiples=ULNMultiples(ALT=alt_uln, AST=ast_uln, ALP=alp_uln, Bilirubin=bili_uln, GGT=ggt_uln),
        ast_alt_ratio=ASTALTRatio(value=ast_alt, interpretation=ast_alt_interp),
        albumin_status=alb_status,
        overall_lab_severity=severity,
    )


def _check_completeness(payload: PatientPayload) -> Completeness:
    missing = []
    warnings = []

    if not payload.patient_demographics.age:
        missing.append("patient_demographics.age")
    if not payload.patient_demographics.sex:
        missing.append("patient_demographics.sex")
    if not payload.referral_summary.symptoms:
        missing.append("referral_summary.symptoms")

    labs = payload.lft_blood_results
    for field in ["ALT_IU_L", "AST_IU_L", "ALP_IU_L", "Bilirubin_umol_L", "Albumin_g_L", "GGT_IU_L"]:
        if getattr(labs, field, None) is None:
            missing.append(f"lft_blood_results.{field}")

    bmi = payload.history_risk_factors.bmi
    if bmi > 40:
        warnings.append(f"BMI {bmi} is in morbidly obese range — verify measurement accuracy")
    elif bmi > 35:
        warnings.append(f"BMI {bmi} is in severely obese range")

    alcohol = payload.history_risk_factors.alcohol_units_weekly
    if alcohol > 14:
        warnings.append(f"Alcohol intake at {alcohol} units/week exceeds UK guideline of 14 units")
    if alcohol > 35:
        warnings.append(f"Alcohol intake at {alcohol} units/week is very high risk")

    score = 1.0 if not missing else round(1.0 - (len(missing) * 0.15), 2)
    return Completeness(score=max(0, score), missing_fields=missing, warnings=warnings)


def extract_risk_factors(payload: PatientPayload) -> RiskFactorResponse:
    """Run Module 0: Fully deterministic risk factor extraction. No LLM call."""
    start_time = time.time()

    hist = payload.history_risk_factors
    risk_factors = RiskFactors(
        alcohol_risk=_classify_alcohol(hist.alcohol_units_weekly),
        bmi_category=_classify_bmi(hist.bmi),
        diabetes_status=_classify_diabetes(hist.comorbidities),
        cancer_history=_classify_cancer(hist.comorbidities),
        symptom_severity=_classify_symptoms(payload.referral_summary.symptoms),
        liver_disease_history=LiverDiseaseHistory(
            known_disease=hist.known_liver_disease,
            details="known liver disease" if hist.known_liver_disease else "none",
        ),
    )

    derived = _compute_derived_metrics(payload.lft_blood_results.model_dump())
    completeness = _check_completeness(payload)

    elapsed_ms = int((time.time() - start_time) * 1000)

    return RiskFactorResponse(
        scenario_id=payload.scenario_id,
        timestamp=datetime.now(timezone.utc).isoformat(),
        completeness=completeness,
        risk_factors=risk_factors,
        derived_metrics=derived,
        processing_metadata=ProcessingMetadata(
            model_used="deterministic (no LLM)",
            processing_time_ms=elapsed_ms,
            token_usage=TokenUsage(input=0, output=0, total=0),
        ),
    )
