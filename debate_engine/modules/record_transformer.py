"""Transform a pipeline_output record into a PatientPayload for the debate engine.

Parses the comprehensive record format (from photo extraction) and extracts
the fields needed by the debate pipeline: demographics, LFT values, risk factors.
"""
from __future__ import annotations
import re


# ── Lab name aliases ─────────────────────────────────────────────────────
_LAB_ALIASES = {
    "ALT": ["alt", "alanine aminotransferase", "alt (sgpt)", "sgpt", "alt iu/l", "alt u/l"],
    "AST": ["ast", "aspartate aminotransferase", "ast (sgot)", "sgot", "ast iu/l", "ast u/l"],
    "ALP": ["alp", "alkaline phosphatase", "alk phos", "alk. phos.", "alp iu/l", "alp u/l"],
    "GGT": ["ggt", "gamma-glutamyl transferase", "gamma gt", "γ-gt", "ggt iu/l", "ggt u/l"],
    "Bilirubin": ["bilirubin", "bilirubin tot", "bilirubin total", "total bilirubin", "t. bilirubin", "tbil"],
    "Albumin": ["albumin", "alb"],
}


def _parse_number(text: str) -> float | None:
    """Extract the first number from a string like '122 U/L' or '0.9 mg/dL'."""
    m = re.search(r"([\d]+\.?\d*)", text)
    return float(m.group(1)) if m else None


def _match_lab(test_name: str) -> str | None:
    """Match a test name to a canonical lab name."""
    lower = test_name.strip().lower()
    for canonical, aliases in _LAB_ALIASES.items():
        if lower in aliases or lower == canonical.lower():
            return canonical
    return None


def _detect_bilirubin_unit(result_str: str) -> str:
    """Detect if bilirubin is in mg/dL or µmol/L."""
    lower = result_str.lower()
    if "mg" in lower:
        return "mg/dL"
    if "umol" in lower or "µmol" in lower or "μmol" in lower:
        return "umol/L"
    # If no unit specified, guess from value
    val = _parse_number(result_str)
    if val is not None:
        return "mg/dL" if val < 15 else "umol/L"
    return "umol/L"


def _detect_albumin_unit(result_str: str) -> str:
    """Detect if albumin is in g/dL or g/L."""
    lower = result_str.lower()
    if "g/dl" in lower:
        return "g/dL"
    if "g/l" in lower:
        return "g/L"
    # If no unit specified, guess from value
    val = _parse_number(result_str)
    if val is not None:
        return "g/dL" if val < 10 else "g/L"
    return "g/L"


def _parse_alcohol_units(text: str) -> float:
    """Parse alcohol units per week from free text."""
    lower = text.lower().strip()

    # Explicit units pattern: "18 units", "4 units/week", "about 18 units per week"
    m = re.search(r"(\d+\.?\d*)\s*units?", lower)
    if m:
        return float(m.group(1))

    # "< 5 drinks" pattern
    m = re.search(r"<?\s*(\d+\.?\d*)\s*drinks?", lower)
    if m:
        return float(m.group(1))

    # Common descriptions
    if any(w in lower for w in ["none", "nil", "teetotal", "no alcohol", "non-drinker", "does not drink"]):
        return 0.0
    if any(w in lower for w in ["minimal", "rare", "occasional", "social"]):
        return 2.0
    if any(w in lower for w in ["moderate"]):
        return 14.0
    if any(w in lower for w in ["heavy", "excessive", "daily", "bottle", "dependent"]):
        return 40.0

    return 0.0


def _find_sections(record: dict, section_type: str) -> list[dict]:
    """Find all sections of a given type."""
    return [s for s in record.get("sections", []) if s.get("type") == section_type]


def _extract_labs(record: dict) -> dict:
    """Extract LFT values from lab_results sections."""
    labs = {}
    for section in _find_sections(record, "lab_results"):
        for table in section.get("tables", []):
            for row in table.get("rows", []):
                if len(row) < 2:
                    continue
                test_name = row[0]
                result_str = row[1]
                canonical = _match_lab(test_name)
                if canonical and canonical not in labs:
                    val = _parse_number(result_str)
                    if val is not None:
                        # Handle unit conversions
                        if canonical == "Bilirubin":
                            unit = _detect_bilirubin_unit(result_str)
                            if unit == "mg/dL":
                                val = round(val * 17.1, 1)
                        elif canonical == "Albumin":
                            unit = _detect_albumin_unit(result_str)
                            if unit == "g/dL":
                                val = round(val * 10, 1)
                        labs[canonical] = val
    return labs


def _extract_bmi(record: dict) -> float:
    """Extract BMI from vitals section or patient_profile."""
    # Check vitals
    for section in _find_sections(record, "vitals"):
        data = section.get("data", {})
        for key, val in data.items():
            if "bmi" in key.lower():
                num = _parse_number(str(val))
                if num:
                    return num

    # Check patient_profile
    for section in _find_sections(record, "patient_profile"):
        data = section.get("data", {})
        for key, val in data.items():
            if "bmi" in key.lower():
                num = _parse_number(str(val))
                if num:
                    return num

    return 25.0  # default normal


def _extract_alcohol(record: dict) -> float:
    """Extract alcohol units/week from questionnaire, social_history, or lifestyle."""
    # Check questionnaire
    for section in _find_sections(record, "questionnaire"):
        for qa in section.get("qa", []):
            if len(qa) >= 2 and "alcohol" in qa[0].lower():
                return _parse_alcohol_units(qa[1])

    # Check social_history
    for section in _find_sections(record, "social_history"):
        data = section.get("data", {})
        for key, val in data.items():
            if "alcohol" in key.lower():
                return _parse_alcohol_units(str(val))
        # Check items
        for item in section.get("items", []):
            if "alcohol" in item.lower():
                return _parse_alcohol_units(item)

    # Check lifestyle
    for section in _find_sections(record, "lifestyle"):
        data = section.get("data", {})
        for key, val in data.items():
            if "alcohol" in key.lower():
                return _parse_alcohol_units(str(val))

    return 0.0


def _extract_symptoms(record: dict) -> tuple[list[str], str]:
    """Extract symptoms and urgency from referral section."""
    symptoms = []
    urgency = "routine"

    for section in _find_sections(record, "referral"):
        data = section.get("data", {})

        # Urgency
        for key, val in data.items():
            k = key.lower()
            if "urgency" in k or "priority" in k:
                val_lower = str(val).lower()
                if "immediate" in val_lower or "emergency" in val_lower:
                    urgency = "immediate"
                elif "urgent" in val_lower:
                    urgency = "urgent"

        # Symptoms from reason_for_referral or history
        for key, val in data.items():
            k = key.lower()
            if any(w in k for w in ["reason", "presenting", "complaint", "symptom", "history_of_presenting"]):
                if isinstance(val, str) and val.strip():
                    symptoms.append(val.strip())
                elif isinstance(val, list):
                    symptoms.extend([str(v).strip() for v in val if str(v).strip()])

    # Also check consultation_notes for chief complaint
    if not symptoms:
        for section in _find_sections(record, "consultation_notes"):
            data = section.get("data", {})
            for key, val in data.items():
                if "chief" in key.lower() or "complaint" in key.lower() or "hpi" in key.lower():
                    if isinstance(val, str) and val.strip():
                        symptoms.append(val.strip())

    # Check questionnaire for main symptoms
    if not symptoms:
        for section in _find_sections(record, "questionnaire"):
            for qa in section.get("qa", []):
                if len(qa) >= 2 and "symptom" in qa[0].lower():
                    if qa[1].strip():
                        symptoms.append(qa[1].strip())

    if not symptoms:
        symptoms = ["not specified"]

    return symptoms, urgency


def _extract_comorbidities(record: dict) -> tuple[list[str], bool]:
    """Extract comorbidities and known_liver_disease from problems section."""
    comorbidities = []
    known_liver = False

    liver_keywords = [
        "liver", "hepat", "cirrho", "steatosis", "fibrosis", "masld", "nafld",
        "nash", "fatty liver", "wilson", "haemochromatosis", "hemochromatosis",
        "biliary", "cholangitis",
    ]

    for section in _find_sections(record, "problems"):
        for item in section.get("items", []):
            item_lower = item.lower()
            if any(kw in item_lower for kw in liver_keywords):
                known_liver = True
            else:
                comorbidities.append(item)

    # Also check referral for past medical history
    for section in _find_sections(record, "referral"):
        data = section.get("data", {})
        for key, val in data.items():
            if "past" in key.lower() and "medical" in key.lower():
                if isinstance(val, list):
                    for item in val:
                        item_str = str(item)
                        item_lower = item_str.lower()
                        if any(kw in item_lower for kw in liver_keywords):
                            known_liver = True
                        elif item_str not in comorbidities:
                            comorbidities.append(item_str)

    # Check questionnaire for metabolic risk factors
    for section in _find_sections(record, "questionnaire"):
        for qa in section.get("qa", []):
            if len(qa) >= 2 and "metabolic" in qa[0].lower():
                text = qa[1]
                if "diabetes" in text.lower() and not any("diabet" in c.lower() for c in comorbidities):
                    comorbidities.append("Type 2 Diabetes")
                if "hypertension" in text.lower() or "blood pressure" in text.lower():
                    if not any("hypertension" in c.lower() or "htn" in c.lower() for c in comorbidities):
                        comorbidities.append("Hypertension")

    return comorbidities, known_liver


def transform_record_to_payload(record: dict) -> dict:
    """Transform a pipeline_output record into a PatientPayload dict.

    Args:
        record: The full record from pipeline_output (with patient, sections, etc.)

    Returns:
        Dict matching the PatientPayload schema, ready to send to debate endpoints.
    """
    patient = record.get("patient", {})

    # Demographics
    age = int(_parse_number(str(patient.get("age", "0"))) or 0)
    sex = (patient.get("sex") or "unknown").lower()

    # Labs
    labs = _extract_labs(record)

    # Risk factors
    bmi = _extract_bmi(record)
    alcohol = _extract_alcohol(record)
    comorbidities, known_liver = _extract_comorbidities(record)
    symptoms, urgency = _extract_symptoms(record)

    # Build scenario_id from MRN or patient name
    mrn = patient.get("mrn", "")
    name = patient.get("name", "unknown")
    scenario_id = mrn if mrn else name.lower().replace(" ", "_")

    return {
        "scenario_id": scenario_id,
        "patient_demographics": {
            "age": age,
            "sex": sex,
        },
        "referral_summary": {
            "symptoms": symptoms,
            "urgency_requested": urgency,
        },
        "lft_blood_results": {
            "ALT_IU_L": labs.get("ALT", 0),
            "AST_IU_L": labs.get("AST", 0),
            "ALP_IU_L": labs.get("ALP", 0),
            "Bilirubin_umol_L": labs.get("Bilirubin", 0),
            "Albumin_g_L": labs.get("Albumin", 0),
            "GGT_IU_L": labs.get("GGT", 0),
        },
        "history_risk_factors": {
            "alcohol_units_weekly": alcohol,
            "bmi": bmi,
            "known_liver_disease": known_liver,
            "comorbidities": comorbidities,
        },
    }
