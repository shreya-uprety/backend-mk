"""Board Chat Agent — Q&A from patient context + dynamic board navigation.

Answers clinical questions using patient data from GCS. Fetches actual
board item IDs dynamically and caches them for fast focus resolution.
"""
import os
import json
import logging
import httpx
from pathlib import Path
from google import genai

from storage import get_storage

logger = logging.getLogger("chat-agent")

GEMINI_MODEL = "gemini-2.5-flash-lite"
API_KEY = os.getenv("GOOGLE_API_KEY", "")
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "system_prompt.md"
BOARD_BASE_URL = os.getenv("NEXT_PUBLIC_BACKEND_URL", "http://localhost:3000")

# ── Caches ───────────────────────────────────────────────────────────

_context_cache: dict[str, dict] = {}  # patient_id → patient data
_board_cache: dict[str, dict] = {}    # patient_id → { sections, keyword_map }
_gemini_client = None
_system_prompt_cache = None


def _get_client():
    global _gemini_client
    if _gemini_client is None:
        _gemini_client = genai.Client(api_key=API_KEY)
    return _gemini_client


def _get_system_prompt() -> str:
    global _system_prompt_cache
    if _system_prompt_cache is None:
        if SYSTEM_PROMPT_PATH.exists():
            _system_prompt_cache = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        else:
            _system_prompt_cache = "You are a clinical assistant. Answer using only patient data provided."
    return _system_prompt_cache


# ── Topic keywords → section label matching ──────────────────────────

# Maps keywords to the kind of section label they should match
KEYWORD_TO_LABEL_HINTS = {
    # Patient info
    "name": ["patient info", "demographics", "patient profile"],
    "age": ["patient info", "demographics", "patient profile"],
    "dob": ["patient info", "demographics", "patient profile"],
    "sex": ["patient info", "demographics", "patient profile"],
    "gender": ["patient info", "demographics", "patient profile"],
    "mrn": ["patient info", "demographics", "patient profile"],
    "demographics": ["patient info", "demographics", "patient profile"],
    "profile": ["patient info", "demographics", "patient profile"],
    "overview": ["patient info", "demographics", "patient profile"],

    # Problems / allergies
    "problem": ["problem"],
    "allerg": ["allerg"],

    # Medications
    "medication": ["medication"],
    "drug": ["medication"],
    "medicine": ["medication"],
    "prescription": ["medication"],

    # Labs
    "lab": ["lab result", "lab", "biochemistry", "screening"],
    "lft": ["lab result", "biochemistry", "liver"],
    "liver function": ["lab result", "biochemistry", "liver"],
    "blood test": ["lab result", "biochemistry", "screening"],
    "alt": ["lab result", "biochemistry"],
    "ast": ["lab result", "biochemistry"],
    "bilirubin": ["lab result", "biochemistry"],
    "albumin": ["lab result", "biochemistry"],
    "ggt": ["lab result", "biochemistry"],
    "alp": ["lab result", "biochemistry"],
    "platelet": ["lab result", "screening"],

    # Imaging / Scans
    "ultrasound": ["scans", "imaging", "ultrasound", "abdomen"],
    "fibroscan": ["scans", "imaging", "elastography", "fibroscan", "transient"],
    "elastography": ["scans", "imaging", "elastography", "fibroscan"],
    "imaging": ["scans", "imaging"],
    "scan": ["scans", "imaging"],
    "radiology": ["radiology", "diagnostic"],
    "x-ray": ["radiology", "x-ray"],
    "ct scan": ["radiology", "ct"],
    "mri": ["radiology", "mri"],

    # Encounters / consultation
    "encounter": ["consultation", "encounter"],
    "visit": ["consultation", "encounter"],
    "consultation": ["consultation", "encounter", "notes"],
    "clinical notes": ["consultation", "notes"],
    "physical exam": ["consultation", "encounter"],
    "history": ["consultation", "encounter"],

    # Referral
    "referral": ["referral"],
    "referred": ["referral"],
    "gp letter": ["referral"],

    # Diagnosis / assessment
    "diagnosis": ["diagnosis", "assessment", "hepatologist"],
    "differential": ["diagnosis"],
    "assessment": ["assessment", "hepatologist", "diagnosis"],
    "plan": ["assessment", "plan", "hepatologist"],

    # Vitals
    "vital": ["vital", "measurement"],
    "blood pressure": ["vital"],
    "heart rate": ["vital"],
    "bmi": ["vital", "patient profile", "patient info"],
    "weight": ["vital"],

    # Allergies / problems (may be in patient info or separate sections)
    "allerg": ["allerg"],
    "problem": ["problem"],
    "condition": ["problem"],

    # AI analysis
    "red flag": ["ai", "analysis", "red flag"],
    "pattern": ["ai", "analysis", "pattern", "lft pattern"],
    "risk factor": ["ai", "analysis", "risk"],
    "r-factor": ["ai", "analysis", "r-factor", "risk factor", "lab result"],
    "r factor": ["ai", "analysis", "r-factor", "risk factor", "lab result"],

    # Monitoring / follow-up
    "monitoring": ["monitoring", "plan", "assessment"],
    "follow up": ["plan", "assessment"],
    "surveillance": ["surveillance", "monitoring"],
    "investigation": ["investigation", "plan"],
}

GENERIC_KEYWORDS = {"patient", "overview", "profile", "report"}


# ── Board item fetching and caching ──────────────────────────────────


def _fetch_board_items(patient_id: str) -> dict:
    """Fetch board sections and nodes from the frontend board data file or API.

    Returns a dict with:
        sections: list of { id, label, nodes: [{ id, label, type }] }
        keyword_map: { keyword → { sectionId, nodeId, label } }
    """
    board_data = None

    # Try loading from local board-events file first
    events_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "data" / "board-events" / f"{patient_id}.json"
    if events_path.exists():
        try:
            with open(events_path, "r", encoding="utf-8") as f:
                events = json.load(f)
            # Get latest board-sync event
            for event in reversed(events):
                if event.get("type") == "board-sync" and event.get("payload", {}).get("sections"):
                    board_data = event["payload"]
                    break
            # If all events are board-sync with payload at top level
            if not board_data and events and events[0].get("payload", {}).get("sections"):
                board_data = events[0]["payload"]
        except Exception as e:
            logger.warning(f"Failed to load board events file: {e}")

    # Try boards file
    if not board_data:
        boards_path = Path(__file__).resolve().parent.parent.parent / "frontend" / "data" / "boards" / f"{patient_id}.json"
        if boards_path.exists():
            try:
                with open(boards_path, "r", encoding="utf-8") as f:
                    board_data = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to load boards file: {e}")

    if not board_data or "sections" not in board_data:
        logger.warning(f"No board data found for {patient_id}")
        return {"sections": [], "keyword_map": {}}

    # Parse sections and build keyword map
    sections = []
    keyword_map = {}

    for section in board_data["sections"]:
        sid = section.get("id", "")
        slabel = section.get("label", "")
        nodes = []

        for node in section.get("nodes", []):
            nid = node.get("id", "")
            ntype = node.get("type", "")
            nlabel = node.get("data", {}).get("label", "") if isinstance(node.get("data"), dict) else ""
            nodes.append({"id": nid, "label": nlabel, "type": ntype})

        sections.append({"id": sid, "label": slabel, "nodes": nodes})

        # Build keyword map: match section/node labels against keywords
        slabel_lower = slabel.lower()
        for keyword, hints in KEYWORD_TO_LABEL_HINTS.items():
            for hint in hints:
                if hint in slabel_lower:
                    # Match section
                    if keyword not in keyword_map:
                        keyword_map[keyword] = {"sectionId": sid, "nodeId": None, "label": slabel}
                    break

            # Also check node labels
            for node in nodes:
                nlabel_lower = node["label"].lower()
                for hint in hints:
                    if hint in nlabel_lower:
                        keyword_map[keyword] = {"sectionId": sid, "nodeId": node["id"], "label": node["label"]}
                        break

    return {"sections": sections, "keyword_map": keyword_map}


def _get_board_cache(patient_id: str, force_refresh: bool = False) -> dict:
    """Get cached board data, fetching if needed."""
    if not force_refresh and patient_id in _board_cache:
        return _board_cache[patient_id]

    board = _fetch_board_items(patient_id)
    _board_cache[patient_id] = board
    logger.info(f"Board cache loaded for {patient_id}: {len(board['sections'])} sections, {len(board['keyword_map'])} keywords")
    return board


def detect_focus_topic(query: str, patient_id: str) -> dict | None:
    """Detect which board section/node to focus based on query keywords.

    Returns { sectionId, nodeId, label } or None.
    """
    board = _get_board_cache(patient_id)
    keyword_map = board.get("keyword_map", {})
    q = query.lower()

    # First pass: specific keywords (longest first, skip generic)
    for kw in sorted(keyword_map.keys(), key=len, reverse=True):
        if kw in GENERIC_KEYWORDS:
            continue
        if kw in q:
            return keyword_map[kw]

    # Second pass: generic keywords
    for kw in sorted(GENERIC_KEYWORDS, key=len, reverse=True):
        if kw in q and kw in keyword_map:
            return keyword_map[kw]

    # Third pass: fuzzy match against section labels directly
    sections = board.get("sections", [])
    for section in sections:
        slabel = section["label"].lower()
        # Check if any word from the query appears in the section label
        query_words = [w for w in q.split() if len(w) > 3]
        for word in query_words:
            if word in slabel:
                return {"sectionId": section["id"], "nodeId": None, "label": section["label"]}

    return None


# ── Patient context loading ──────────────────────────────────────────


def _load_patient_context(patient_id: str, force_refresh: bool = False) -> dict:
    """Load patient data from GCS with caching."""
    if not force_refresh and patient_id in _context_cache:
        return _context_cache[patient_id]

    storage = get_storage()
    context = {"patient_id": patient_id, "data": {}}

    status_prefix = f"patient_status/{patient_id}"
    enriched_path = f"{status_prefix}/enriched_payload.json"
    if storage.exists(enriched_path):
        context["data"]["enriched_payload"] = storage.read_json(enriched_path)

    key_files = {
        "diagnosis": "diagnosis_result.json",
        "monitoring": "monitoring_result.json",
        "gp_letter": "gp_letter_result.json",
    }
    for key, filename in key_files.items():
        path = f"{status_prefix}/{filename}"
        if storage.exists(path):
            context["data"][key] = storage.read_json(path)

    record_path = f"pipeline_output/{patient_id}/record.json"
    if storage.exists(record_path):
        context["data"]["patient_record"] = storage.read_json(record_path)

    _context_cache[patient_id] = context
    return context


def _extract_relevant_context(context: dict, focus: dict | None) -> dict | None:
    """Extract relevant context section based on the focused section label."""
    if not focus:
        return None

    data = context.get("data", {})
    label = (focus.get("label") or "").lower()

    # Always include patient_record as it has everything
    if "patient_record" in data:
        return {"patient_record": data["patient_record"]}

    # Fallback: include enriched_payload
    if "enriched_payload" in data:
        return {"enriched_payload": data["enriched_payload"]}

    return None


def invalidate_cache(patient_id: str = None):
    """Clear all caches."""
    if patient_id:
        _context_cache.pop(patient_id, None)
        _board_cache.pop(patient_id, None)
    else:
        _context_cache.clear()
        _board_cache.clear()


# ── Main chat function ───────────────────────────────────────────────


async def chat(patient_id: str, query: str, conversation_history: list[dict] | None = None) -> dict:
    """Process a chat query — answer from context + detect board navigation."""

    # 1. Detect focus from board items
    focus = detect_focus_topic(query, patient_id)

    # If no match found, refresh board cache and try again
    if not focus:
        _board_cache.pop(patient_id, None)
        focus = detect_focus_topic(query, patient_id)

    focus_section = focus.get("sectionId") if focus else None
    focus_node = focus.get("nodeId") if focus else None
    focus_label = focus.get("label") if focus else None

    # 2. Load patient context
    context = _load_patient_context(patient_id)
    context_str = json.dumps(context["data"], indent=2, default=str)

    if len(context_str) > 30000:
        context_str = context_str[:30000] + "\n... (truncated)"

    # Only send relevant context if possible
    if focus and len(context_str) > 5000:
        relevant = _extract_relevant_context(context, focus)
        if relevant:
            context_str = json.dumps(relevant, indent=1, default=str)[:15000]

    # 3. Build prompt
    system = _get_system_prompt()

    history_str = ""
    if conversation_history:
        for msg in conversation_history[-2:]:
            history_str += f"\n{msg.get('role','')}: {msg.get('content','')}"

    prompt = f"""{system}

---CONTEXT---
{context_str[:20000]}
{f'---HISTORY---{history_str}' if history_str else ''}
---QUERY---
{query}"""

    # 4. Call Gemini with fallback
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

    # 5. Call board focus API if we have a target
    if focus_section or focus_node:
        try:
            board_url = f"{BOARD_BASE_URL}/api/board/{patient_id}/focus"
            focus_body = {}
            if focus_section:
                focus_body["sectionId"] = focus_section
            if focus_node:
                focus_body["nodeId"] = focus_node
            focus_body["zoom"] = 1.2

            async with httpx.AsyncClient(timeout=3.0) as client:
                await client.post(board_url, json=focus_body)
            logger.info(f"Board focus: {focus_label} ({focus_section})")
        except Exception as e:
            logger.debug(f"Board focus API not available: {e}")

    return {
        "answer": answer,
        "focus_item": focus_node or focus_section,
        "focus_section": focus_section,
        "focus_node": focus_node,
        "focus_label": focus_label,
    }
