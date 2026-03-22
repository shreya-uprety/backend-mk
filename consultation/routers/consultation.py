"""Consultation API routes.

Provides endpoints for:
- Simulation (WebSocket-based pre-recorded scenario playback)
- Pre-consultation (patient registration, chat history)
- Consultation data retrieval
"""
import json
import uuid
import logging
import traceback
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from storage import get_storage

router = APIRouter(prefix="/api/v1/consultation", tags=["consultation"])
logger = logging.getLogger("consultation")

CONSULTATION_PREFIX = "consultation_data"


# ── Models ──────────────────────────────────────────────────────────


class PatientRegistrationRequest(BaseModel):
    first_name: str
    last_name: str
    dob: str
    gender: str
    email: str | None = None
    phone: str | None = None
    complaint: str | None = None


class ChatMessage(BaseModel):
    patient_id: str
    message: str
    sender: str = "patient"  # "patient" or "nurse"


# ── Simulation WebSocket ────────────────────────────────────────────


@router.websocket("/ws/simulation/audio")
async def websocket_simulation_audio(websocket: WebSocket):
    """WebSocket for scripted/audio-only simulation.

    Client sends: { "type": "start", "patient_id": "...", "script_file": "..." }
    Server streams: audio (base64), transcript, questions, diagnosis, education, analytics, checklist, report
    """
    await websocket.accept()

    manager = None
    try:
        data = await websocket.receive_json()
        if isinstance(data, dict) and data.get("type") == "start":
            patient_id = data.get("patient_id", "P0001")
            logger.info(f"Starting Audio Simulation for {patient_id}")

            from consultation.simulation import SimulationAudioManager
            manager = SimulationAudioManager(websocket, patient_id)
            await manager.run()

    except WebSocketDisconnect:
        logger.info("Audio Simulation client disconnected")
        if manager:
            manager.stop()
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Audio Simulation error: {e}")
        if manager:
            manager.stop()


# ── Patient Registration ────────────────────────────────────────────


@router.post("/register")
async def register_patient(req: PatientRegistrationRequest):
    """Register a new patient for consultation."""
    patient_id = f"PT-{uuid.uuid4().hex[:8].upper()}"
    now = datetime.now(timezone.utc).isoformat()

    patient_data = {
        "patient_id": patient_id,
        "first_name": req.first_name,
        "last_name": req.last_name,
        "name": f"{req.first_name} {req.last_name}",
        "dob": req.dob,
        "gender": req.gender,
        "email": req.email,
        "phone": req.phone,
        "complaint": req.complaint,
        "registered_at": now,
        "status": "registered",
    }

    storage = get_storage()
    storage.write_json(f"{CONSULTATION_PREFIX}/{patient_id}/basic_info.json", patient_data)

    return {"patient_id": patient_id, "status": "registered"}


# ── Chat ────────────────────────────────────────────────────────────


@router.post("/chat")
async def send_chat_message(msg: ChatMessage):
    """Send a chat message in the pre-consultation flow."""
    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{msg.patient_id}/chat_history.json"

    history = storage.read_json(path) if storage.exists(path) else []
    history.append({
        "sender": msg.sender,
        "message": msg.message,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    storage.write_json(path, history)

    return {"status": "sent", "message_count": len(history)}


@router.get("/chat/{patient_id}")
async def get_chat_history(patient_id: str):
    """Get chat history for a patient."""
    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{patient_id}/chat_history.json"

    if not storage.exists(path):
        return {"patient_id": patient_id, "messages": []}

    return {"patient_id": patient_id, "messages": storage.read_json(path)}


# ── Patient Data ────────────────────────────────────────────────────


@router.get("/patients")
async def list_patients():
    """List all registered consultation patients."""
    storage = get_storage()
    blobs = storage.list_blobs(CONSULTATION_PREFIX)
    info_files = [b for b in blobs if b.endswith("basic_info.json")]

    patients = []
    for path in info_files:
        data = storage.read_json(path)
        patients.append(data)

    return {"patients": patients}


@router.get("/patient/{patient_id}")
async def get_patient(patient_id: str):
    """Get patient details."""
    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{patient_id}/basic_info.json"

    if not storage.exists(path):
        raise HTTPException(404, f"Patient {patient_id} not found")

    return storage.read_json(path)


# ── Consultation Results ────────────────────────────────────────────


@router.post("/complete/{patient_id}")
async def complete_consultation(patient_id: str):
    """Mark consultation as complete and aggregate all data."""
    storage = get_storage()
    prefix = f"{CONSULTATION_PREFIX}/{patient_id}"
    info_path = f"{prefix}/basic_info.json"

    if not storage.exists(info_path):
        raise HTTPException(404, f"Patient {patient_id} not found")

    now = datetime.now(timezone.utc).isoformat()

    # Aggregate all data
    basic_info = storage.read_json(info_path)
    chat_path = f"{prefix}/chat_history.json"
    chat = storage.read_json(chat_path) if storage.exists(chat_path) else []

    bundle = {
        **basic_info,
        "chat_history": chat,
        "consultation_ready": True,
        "completed_at": now,
    }

    storage.write_json(f"{prefix}/consultation_info.json", bundle)

    # Update patient status
    basic_info["status"] = "consultation_ready"
    storage.write_json(info_path, basic_info)

    return {"patient_id": patient_id, "status": "completed"}


@router.get("/consultation-info/{patient_id}")
async def get_consultation_info(patient_id: str):
    """Get the full consultation bundle."""
    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{patient_id}/consultation_info.json"

    if not storage.exists(path):
        raise HTTPException(404, f"No consultation info for {patient_id}")

    return storage.read_json(path)


# ── Simulation Results (saved to GCS after simulation completes) ─────


@router.get("/simulation/{patient_id}/results")
async def get_simulation_results(patient_id: str):
    """Get all saved simulation results from GCS."""
    storage = get_storage()
    prefix = f"{CONSULTATION_PREFIX}/{patient_id}/simulation"

    session_path = f"{prefix}/session_info.json"
    if not storage.exists(session_path):
        raise HTTPException(404, f"No simulation results for {patient_id}")

    results = {}
    for name in ["session_info", "transcript", "questions", "diagnosis",
                  "education", "analytics", "checklist", "report"]:
        path = f"{prefix}/{name}.json"
        if storage.exists(path):
            results[name] = storage.read_json(path)

    return results


@router.get("/simulation/{patient_id}/transcript")
async def get_simulation_transcript(patient_id: str):
    """Get saved simulation transcript from GCS."""
    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{patient_id}/simulation/transcript.json"

    if not storage.exists(path):
        raise HTTPException(404, "No simulation transcript found")

    return storage.read_json(path)


@router.get("/simulation/{patient_id}/report")
async def get_simulation_report(patient_id: str):
    """Get saved simulation report from GCS."""
    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{patient_id}/simulation/report.json"

    if not storage.exists(path):
        raise HTTPException(404, "No simulation report found")

    return storage.read_json(path)


@router.get("/simulation/{patient_id}/diagnosis")
async def get_simulation_diagnosis(patient_id: str):
    """Get saved simulation diagnoses from GCS."""
    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{patient_id}/simulation/diagnosis.json"

    if not storage.exists(path):
        raise HTTPException(404, "No simulation diagnosis found")

    return storage.read_json(path)


@router.get("/simulation/{patient_id}/{result_type}")
async def get_simulation_result(patient_id: str, result_type: str):
    """Get any specific simulation result from GCS."""
    valid_types = {"transcript", "questions", "diagnosis", "education",
                   "analytics", "checklist", "report", "session_info"}
    if result_type not in valid_types:
        raise HTTPException(400, f"Invalid result type. Valid: {', '.join(sorted(valid_types))}")

    storage = get_storage()
    path = f"{CONSULTATION_PREFIX}/{patient_id}/simulation/{result_type}.json"

    if not storage.exists(path):
        raise HTTPException(404, f"No {result_type} found for {patient_id}")

    return storage.read_json(path)
