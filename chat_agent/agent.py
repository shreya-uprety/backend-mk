"""Board Chat Agent — Q&A from patient context + board navigation.

Answers clinical questions using patient data from GCS and returns
which board item to focus on for the answer.
"""
import os
import json
import logging
from pathlib import Path
from google import genai

from storage import get_storage

logger = logging.getLogger("chat-agent")

GEMINI_MODEL = "gemini-2.5-flash-lite"  # Fastest available model
API_KEY = os.getenv("GOOGLE_API_KEY", "")
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"

# Cache patient context in memory to avoid repeated GCS reads
_context_cache: dict[str, dict] = {}
_gemini_client = None

def _get_client():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=API_KEY)
    return _gemini_client

# ── Topic → Board Item ID mapping ───────────────────────────────────

TOPIC_FOCUS_MAP = {
    # Patient profile
    "name": "sidebar-1", "age": "sidebar-1", "dob": "sidebar-1", "sex": "sidebar-1",
    "gender": "sidebar-1", "mrn": "sidebar-1", "nhs": "sidebar-1",
    "profile": "sidebar-1", "overview": "sidebar-1", "demographics": "sidebar-1",
    "medical situation": "sidebar-1", "allerg": "sidebar-1", "problem": "sidebar-1",

    # Encounters
    "encounter": "encounter-track-1", "visit": "encounter-track-1",
    "consultation": "encounter-track-1", "appointment": "encounter-track-1",
    "history": "encounter-track-1", "physical exam": "encounter-track-1",
    "exam finding": "encounter-track-1",

    # Labs
    "lab": "dashboard-item-lab-table", "lft": "dashboard-item-lab-table",
    "liver function": "dashboard-item-lab-table", "blood test": "dashboard-item-lab-table",
    "alt": "dashboard-item-lab-table", "ast": "dashboard-item-lab-table",
    "bilirubin": "dashboard-item-lab-table", "albumin": "dashboard-item-lab-table",
    "inr": "dashboard-item-lab-table", "creatinine": "dashboard-item-lab-table",
    "hemoglobin": "dashboard-item-lab-table", "platelet": "dashboard-item-lab-table",
    "ggt": "dashboard-item-lab-table", "alp": "dashboard-item-lab-table",

    # Lab chart/trend
    "chart": "dashboard-item-lab-chart", "graph": "dashboard-item-lab-chart",
    "trend": "dashboard-item-lab-chart",

    # Medications
    "medication": "medication-track-1", "drug": "medication-track-1",
    "medicine": "medication-track-1", "prescription": "medication-track-1",

    # Diagnosis
    "diagnosis": "differential-diagnosis", "differential": "differential-diagnosis",
    "dili": "differential-diagnosis", "liver injury": "differential-diagnosis",

    # Risk
    "risk": "risk-track-1", "safety": "risk-track-1",

    # Adverse events
    "adverse": "adverse-event-analytics", "causality": "adverse-event-analytics",
    "rucam": "adverse-event-analytics",

    # Key events / timeline
    "event": "key-events-track-1", "timeline": "key-events-track-1",
    "key event": "key-events-track-1", "clinical timeline": "key-events-track-1",

    # Investigations / monitoring / plan
    "investigation": "encounter-track-1", "workup": "encounter-track-1",
    "recommended": "encounter-track-1", "plan": "encounter-track-1",
    "monitoring": "encounter-track-1", "surveillance": "encounter-track-1",
    "follow up": "encounter-track-1", "follow-up": "encounter-track-1",

    # Referral
    "referral": "referral-doctor-info", "referred": "referral-doctor-info",
    "gp letter": "referral-doctor-info", "referring doctor": "referral-doctor-info",

    # Reports / Raw EHR
    "clinical notes": "raw-encounter-image-1", "encounter report": "raw-encounter-image-1",
    "radiology": "raw-lab-image-radiology-1", "imaging": "raw-lab-image-radiology-1",
    "ultrasound": "raw-lab-image-radiology-1", "x-ray": "raw-lab-image-radiology-1",
    "ct scan": "raw-lab-image-radiology-1", "mri": "raw-lab-image-radiology-1",
    "lab report": "raw-lab-image-1", "pathology": "raw-lab-image-1",

    # Patient chat
    "patient chat": "monitoring-patient-chat",
    "patient message": "monitoring-patient-chat",
}

# Keywords that are too generic — only match if nothing specific matches
GENERIC_KEYWORDS = {"patient", "overview", "profile", "report", "reports", "medical situation"}

FRIENDLY_NAMES = {
    "sidebar-1": "patient profile",
    "encounter-track-1": "encounters timeline",
    "dashboard-item-lab-table": "lab results table",
    "dashboard-item-lab-chart": "lab results chart",
    "medication-track-1": "medications timeline",
    "differential-diagnosis": "differential diagnosis",
    "risk-track-1": "risk assessment",
    "adverse-event-analytics": "adverse events analysis",
    "key-events-track-1": "key events timeline",
    "referral-doctor-info": "referral information",
    "raw-encounter-image-1": "clinical notes",
    "raw-lab-image-radiology-1": "imaging reports",
    "raw-lab-image-1": "lab reports",
    "monitoring-patient-chat": "patient chat",
}


def detect_focus_topic(query: str) -> str | None:
    """Detect which board item to focus based on query keywords."""
    q = query.lower()

    # First pass: specific keywords (longest first)
    for kw in sorted(TOPIC_FOCUS_MAP.keys(), key=len, reverse=True):
        if kw in GENERIC_KEYWORDS:
            continue
        if kw in q:
            return TOPIC_FOCUS_MAP[kw]

    # Second pass: generic keywords
    for kw in sorted(GENERIC_KEYWORDS, key=len, reverse=True):
        if kw in q:
            return TOPIC_FOCUS_MAP.get(kw)

    return None


def _load_patient_context(patient_id: str, force_refresh: bool = False) -> dict:
    """Load patient data from GCS with in-memory caching.

    Uses a cache to avoid repeated GCS round-trips. Cache is refreshed
    when force_refresh=True or when a new patient is loaded.
    """
    if not force_refresh and patient_id in _context_cache:
        return _context_cache[patient_id]

    storage = get_storage()
    context = {"patient_id": patient_id, "data": {}}

    # Load enriched payload first (has most of what we need)
    status_prefix = f"patient_status/{patient_id}"
    enriched_path = f"{status_prefix}/enriched_payload.json"
    if storage.exists(enriched_path):
        context["data"]["enriched_payload"] = storage.read_json(enriched_path)

    # Load key results only (skip verbose debate results)
    key_files = {
        "diagnosis": "diagnosis_result.json",
        "monitoring": "monitoring_result.json",
        "gp_letter": "gp_letter_result.json",
    }
    for key, filename in key_files.items():
        path = f"{status_prefix}/{filename}"
        if storage.exists(path):
            context["data"][key] = storage.read_json(path)

    # Load extracted record
    record_path = f"pipeline_output/{patient_id}/record.json"
    if storage.exists(record_path):
        context["data"]["patient_record"] = storage.read_json(record_path)

    # Cache it
    _context_cache[patient_id] = context
    return context


def _extract_relevant_context(context: dict, focus_item: str) -> dict | None:
    """Extract only the relevant section of context based on focus item."""
    data = context.get("data", {})
    focus_to_keys = {
        "sidebar-1": ["enriched_payload", "patient_record"],
        "dashboard-item-lab-table": ["enriched_payload", "patient_record"],
        "dashboard-item-lab-chart": ["enriched_payload", "patient_record"],
        "medication-track-1": ["patient_record"],
        "encounter-track-1": ["patient_record", "monitoring"],
        "differential-diagnosis": ["diagnosis", "enriched_payload", "patient_record"],
        "risk-track-1": ["enriched_payload", "patient_record"],
        "referral-doctor-info": ["patient_record"],
        "adverse-event-analytics": ["patient_record"],
        "key-events-track-1": ["patient_record"],
    }
    keys = focus_to_keys.get(focus_item)
    if not keys:
        return None
    relevant = {k: data[k] for k in keys if k in data}
    return relevant if relevant else None


def invalidate_cache(patient_id: str = None):
    """Clear cached context. Called when patient data changes."""
    if patient_id:
        _context_cache.pop(patient_id, None)
    else:
        _context_cache.clear()


_system_prompt_cache = None

def _get_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        if SYSTEM_PROMPT_PATH.exists():
            _system_prompt_cache = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            _system_prompt_cache = (
                "You are a clinical assistant. Answer questions using only the patient data "
                "provided in the Context section. Be brief, professional, and accurate."
            )
    return _system_prompt_cache


async def chat(patient_id: str, query: str, conversation_history: list[dict] | None = None) -> dict:
    """Process a chat query — answer from context + detect board navigation.

    Returns:
        {
            "answer": str,
            "focus_item": str | None,  # board item ID to navigate to
            "focus_label": str | None,  # friendly name of the focused item
        }
    """
    # 1. Detect which board item to focus
    focus_item = detect_focus_topic(query)
    focus_label = FRIENDLY_NAMES.get(focus_item) if focus_item else None

    # 2. Load patient context from GCS
    context = _load_patient_context(patient_id)
    context_str = json.dumps(context["data"], indent=2, default=str)

    # Truncate if too long
    if len(context_str) > 30000:
        context_str = context_str[:30000] + "\n... (truncated)"

    # 3. Build minimal prompt — less tokens = faster response
    system = _get_system_prompt()

    # Only last 2 messages for history
    history_str = ""
    if conversation_history:
        for msg in conversation_history[-2:]:
            history_str += f"\n{msg.get('role','')}: {msg.get('content','')}"

    # Only send relevant context section based on focus topic
    if focus_item and len(context_str) > 5000:
        relevant = _extract_relevant_context(context, focus_item)
        if relevant:
            context_str = json.dumps(relevant, indent=1, default=str)[:15000]

    prompt = f"""{system}

---CONTEXT---
{context_str[:20000]}
{f'---HISTORY---{history_str}' if history_str else ''}
---QUERY---
{query}"""

    # 4. Call Gemini with fallback model
    import time as _time
    _t0 = _time.time()
    client = _get_client()

    answer = None
    for model in [GEMINI_MODEL, "gemini-2.5-flash"]:
        try:
            response = client.models.generate_content(
                model=model,
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                config={"temperature": 0, "max_output_tokens": 2000},
            )
            answer = response.text.strip()
            logger.info(f"Chat agent: {model} took {_time.time()-_t0:.2f}s")
            break
        except Exception as e:
            logger.warning(f"Chat agent: {model} failed: {e}. Trying fallback...")
            continue

    if not answer:
        answer = "Sorry, the AI service is temporarily unavailable. Please try again in a moment."

    return {
        "answer": answer,
        "focus_item": focus_item,
        "focus_label": focus_label,
    }
