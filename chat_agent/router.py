"""Chat Agent API routes.

Provides REST and WebSocket endpoints for the board chat agent.
Answers clinical questions from patient context in GCS and returns
board navigation instructions.
"""
import json
import logging
import traceback
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from storage import get_storage

router = APIRouter(prefix="/api/v1/chat", tags=["chat-agent"])
logger = logging.getLogger("chat-agent")

GCS_PREFIX = "chat_history"
_memory_history: dict[str, list] = {}  # in-memory chat history per patient


class ChatRequest(BaseModel):
    patient_id: str
    message: str


class ChatHistoryMessage(BaseModel):
    patient_id: str
    role: str  # "doctor" or "agent"
    content: str


# ── REST endpoint ────────────────────────────────────────────────────


@router.post("/preload/{patient_id}")
async def preload_context(patient_id: str):
    """Preload patient context into cache for fast responses."""
    from chat_agent.agent import _load_patient_context
    import time
    t0 = time.time()
    _load_patient_context(patient_id, force_refresh=True)
    return {"status": "loaded", "patient_id": patient_id, "load_time_ms": int((time.time() - t0) * 1000)}


@router.post("/send")
async def send_chat(req: ChatRequest):
    """Send a message to the board chat agent.

    Returns the agent's answer and which board item to navigate to.
    """
    from chat_agent.agent import chat

    try:
        import time as _t
        _t0 = _t.time()

        # In-memory history (no GCS round-trips)
        if req.patient_id not in _memory_history:
            _memory_history[req.patient_id] = []
        history = _memory_history[req.patient_id]

        result = await chat(
            patient_id=req.patient_id,
            query=req.message,
            conversation_history=history,
        )

        # Keep in memory only
        history.append({"role": "doctor", "content": req.message})
        history.append({"role": "agent", "content": result["answer"]})
        # Trim to last 10 messages
        if len(history) > 10:
            _memory_history[req.patient_id] = history[-10:]

        logger.info(f"Total: {_t.time()-_t0:.2f}s")

        return {
            "answer": result["answer"],
            "focus_item": result.get("focus_item"),
            "focus_label": result.get("focus_label"),
            "patient_id": req.patient_id,
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, str(e))


# ── Chat history ─────────────────────────────────────────────────────


@router.get("/history/{patient_id}")
async def get_chat_history(patient_id: str):
    """Get chat history for a patient."""
    history = _load_history(patient_id)
    return {"patient_id": patient_id, "messages": history}


@router.post("/refresh/{patient_id}")
async def refresh_context(patient_id: str):
    """Refresh the cached patient context from GCS."""
    from chat_agent.agent import invalidate_cache
    invalidate_cache(patient_id)
    return {"status": "cache_cleared", "patient_id": patient_id}


@router.delete("/history/{patient_id}")
async def clear_chat_history(patient_id: str):
    """Clear chat history for a patient."""
    storage = get_storage()
    path = f"{GCS_PREFIX}/{patient_id}/messages.json"
    if storage.exists(path):
        storage.delete(path)
    return {"status": "cleared", "patient_id": patient_id}


# ── WebSocket endpoint ───────────────────────────────────────────────


@router.websocket("/ws/{patient_id}")
async def websocket_chat(websocket: WebSocket, patient_id: str):
    """WebSocket for real-time board chat.

    Client sends: { "type": "message", "content": "..." }
    Server responds: { "type": "answer", "content": "...", "focus_item": "...", "focus_label": "..." }
    """
    await websocket.accept()
    logger.info(f"Chat WebSocket connected for {patient_id}")

    try:
        while True:
            data = await websocket.receive_json()

            if data.get("type") == "message":
                content = data.get("content", "").strip()
                if not content:
                    continue

                from chat_agent.agent import chat

                history = _load_history(patient_id)

                result = await chat(
                    patient_id=patient_id,
                    query=content,
                    conversation_history=history,
                )

                # Save to GCS
                now = datetime.now(timezone.utc).isoformat()
                _append_message(patient_id, {"role": "doctor", "content": content, "timestamp": now})
                _append_message(patient_id, {
                    "role": "agent", "content": result["answer"], "timestamp": now,
                    "focus_item": result.get("focus_item"),
                    "focus_label": result.get("focus_label"),
                })

                await websocket.send_json({
                    "type": "answer",
                    "content": result["answer"],
                    "focus_item": result.get("focus_item"),
                    "focus_label": result.get("focus_label"),
                })

    except WebSocketDisconnect:
        logger.info(f"Chat WebSocket disconnected for {patient_id}")
    except Exception as e:
        logger.error(f"Chat WebSocket error: {e}")
        traceback.print_exc()


# ── GCS helpers ──────────────────────────────────────────────────────


def _load_history(patient_id: str) -> list[dict]:
    storage = get_storage()
    path = f"{GCS_PREFIX}/{patient_id}/messages.json"
    if not storage.exists(path):
        return []
    return storage.read_json(path)


def _append_message(patient_id: str, message: dict):
    storage = get_storage()
    path = f"{GCS_PREFIX}/{patient_id}/messages.json"
    history = storage.read_json(path) if storage.exists(path) else []
    history.append(message)
    storage.write_json(path, history)
