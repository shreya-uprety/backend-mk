"""Scenario-based audio simulation manager.

Plays pre-recorded transcript with audio streaming and sends clinical
updates from local dump files. At the end, saves all consultation
results to GCS for persistence across machines.
"""
import asyncio
import json
import os
import base64
import logging
import datetime
import wave
from pathlib import Path
from fastapi import WebSocket

from storage import get_storage

logger = logging.getLogger("consultation")

SCENARIO_DIR = Path(__file__).resolve().parent / "scenario_dumps"
GCS_PREFIX = "consultation_data"


class TranscriptManager:
    def __init__(self):
        self.history = []

    def log(self, speaker, text):
        self.history.append({
            "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
            "speaker": speaker,
            "text": text.strip(),
        })


class SimulationAudioManager:
    """Plays a pre-recorded scenario with audio and saves results to GCS."""

    def __init__(self, websocket: WebSocket, patient_id: str, script_file: str = None):
        self.websocket = websocket
        self.patient_id = patient_id
        self.tm = TranscriptManager()
        self.running = False
        self.script_file = script_file or str(SCENARIO_DIR / "transcript.json")
        self.script_data = self._load_script()

        # Track latest state for GCS save
        self.latest_questions = []
        self.latest_diagnosis = []
        self.latest_education = []
        self.latest_analytics = {}
        self.latest_checklist = []
        self.latest_report = {}

    def _load_script(self):
        path = self.script_file
        if not os.path.exists(path):
            logger.error(f"Script file {path} not found.")
            return []
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return sorted(data, key=lambda x: x.get("index", 0))

    def _get_audio_duration(self, file_path):
        if not os.path.exists(file_path):
            return 2.0
        try:
            with wave.open(file_path, 'rb') as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            try:
                return os.path.getsize(file_path) / 32000
            except Exception:
                return 2.0

    async def _stream_audio_file(self, speaker, audio_path):
        """Stream audio chunks only — text sent separately after audio finishes."""
        if not audio_path or not os.path.exists(audio_path):
            return

        chunk_size = 4096 * 4
        try:
            with open(audio_path, "rb") as f:
                while self.running:
                    data = f.read(chunk_size)
                    if not data:
                        break
                    encoded = base64.b64encode(data).decode("utf-8")
                    await self.websocket.send_json({
                        "type": "audio", "speaker": speaker,
                        "data": encoded, "text": "",
                    })
                    await asyncio.sleep(0.02)
        except Exception as e:
            logger.error(f"Error streaming audio: {e}")

        # Signal audio chunks are done (no text yet — text comes after sleep)
        await self.websocket.send_json({
            "type": "audio", "speaker": speaker,
            "data": None, "text": "", "isFinal": True,
        })

    async def _send_delayed_updates(self, transcript_pool, index, audio_wait=0):
        """Send transcript and clinical updates with delays — runs as background task."""
        try:
            # Wait for audio to finish on client, then 3 more seconds
            await asyncio.sleep(audio_wait + 3.0)
            if not self.running:
                return
            await self.websocket.send_json({"type": "chat", "data": transcript_pool})

            # Clinical updates 2 seconds after transcript
            if index % 2 == 0:
                await asyncio.sleep(2.0)
                if not self.running:
                    return
                update_index = max(0, int(index // 2))
                for folder, prefix, msg_type, key in [
                    ("questions", "q", "questions", "questions"),
                    ("education", "ed", "education", "data"),
                    ("diagnosis", "diag", "diagnosis", "diagnosis"),
                    ("analytics", "a", "analytics", "data"),
                ]:
                    await self._send_scenario_update(folder, prefix, update_index, msg_type, key)

            await self.websocket.send_json({"type": "turn", "data": "finish cycle"})
        except Exception as e:
            logger.error(f"Delayed update error: {e}")

    async def _send_scenario_update(self, folder, file_prefix, index, msg_type, data_key):
        file_path = SCENARIO_DIR / folder / f"{file_prefix}{index}.json"
        if file_path.exists():
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                await self.websocket.send_json({"type": msg_type, data_key: data})

                # Track latest state
                if msg_type == "questions":
                    self.latest_questions = data
                elif msg_type == "diagnosis":
                    self.latest_diagnosis = data
                elif msg_type == "education":
                    self.latest_education = data
                elif msg_type == "analytics":
                    self.latest_analytics = data
            except Exception as e:
                logger.error(f"Failed to load update from {file_path}: {e}")

    def _save_to_gcs(self):
        """Save all consultation results to GCS."""
        try:
            storage = get_storage()
            prefix = f"{GCS_PREFIX}/{self.patient_id}/simulation"
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()

            storage.write_json(f"{prefix}/transcript.json", self.tm.history)
            storage.write_json(f"{prefix}/questions.json", self.latest_questions)
            storage.write_json(f"{prefix}/diagnosis.json", self.latest_diagnosis)
            storage.write_json(f"{prefix}/education.json", self.latest_education)
            storage.write_json(f"{prefix}/analytics.json", self.latest_analytics)
            storage.write_json(f"{prefix}/checklist.json", self.latest_checklist)
            storage.write_json(f"{prefix}/report.json", self.latest_report)
            storage.write_json(f"{prefix}/session_info.json", {
                "patient_id": self.patient_id,
                "completed_at": now,
                "turns": len(self.tm.history),
                "status": "completed",
            })

            logger.info(f"Saved consultation results to GCS: {prefix}/")
        except Exception as e:
            logger.error(f"GCS save error: {e}")

    async def run(self):
        self.running = True
        logger.info("Starting Audio Simulation")

        await self.websocket.send_json({"type": "system", "message": "Initializing Audio Script..."})
        await asyncio.sleep(1)
        await self.websocket.send_json({"type": "system", "message": "Ready."})

        transcript_pool = []

        # Send initial state
        for folder, prefix, msg_type, key in [
            ("questions", "q", "questions", "questions"),
            ("diagnosis", "diag", "diagnosis", "diagnosis"),
        ]:
            await self._send_scenario_update(folder, prefix, 0, msg_type, key)

        for item in self.script_data:
            if not self.running:
                break

            index = item.get("index")
            transcript = item.get("message", "")
            audio_path = item.get("audio_path", "")
            speaker = item.get("role", "SYSTEM")

            # Resolve audio path
            if audio_path and not os.path.isabs(audio_path):
                resolved = SCENARIO_DIR / "audio_files" / f"{index}.WAV"
                if resolved.exists():
                    audio_path = str(resolved)
                else:
                    audio_path = ""

            transcript_pool.append({
                "role": speaker,
                "message": transcript,
                "highlights": item.get("highlights"),
            })
            self.tm.log(speaker, transcript)
            logger.info(f"[{index}] {speaker}: {transcript[:60]}...")

            # Stream audio chunks
            audio_duration = self._get_audio_duration(audio_path)
            start_time = asyncio.get_event_loop().time()
            await self._stream_audio_file(speaker, audio_path)

            # Wait for audio to finish on client
            # Streaming is faster than playback, so real playback time =
            # audio_duration + browser buffering overhead (~1s base + 15% of duration)
            elapsed = asyncio.get_event_loop().time() - start_time
            playback_estimate = audio_duration + 1.0 + (audio_duration * 0.15)
            remaining = playback_estimate - elapsed
            await asyncio.sleep(max(remaining, 0))

            # Transcript appears 0.5s after audio finishes
            await asyncio.sleep(0.5)
            await self.websocket.send_json({"type": "chat", "data": transcript_pool})

            # Send clinical updates 2 seconds after transcript
            if index % 2 == 0:
                await asyncio.sleep(2.0)
                update_index = max(0, int(index // 2))
                for folder, prefix, msg_type, key in [
                    ("questions", "q", "questions", "questions"),
                    ("education", "ed", "education", "data"),
                    ("diagnosis", "diag", "diagnosis", "diagnosis"),
                    ("analytics", "a", "analytics", "data"),
                ]:
                    await self._send_scenario_update(folder, prefix, update_index, msg_type, key)

            await self.websocket.send_json({"type": "turn", "data": "finish cycle"})

        # Final outputs
        await asyncio.sleep(3)
        try:
            for filename, msg_type, data_key, attr in [
                ("checklist.json", "checklist", "data", "latest_checklist"),
                ("report.json", "report", "data", "latest_report"),
            ]:
                path = SCENARIO_DIR / filename
                if path.exists():
                    with open(path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    setattr(self, attr, data)
                    await self.websocket.send_json({"type": msg_type, data_key: data})
        except Exception:
            pass

        # Save everything to GCS
        self._save_to_gcs()

        if self.running:
            await self.websocket.send_json({"type": "system", "message": "Session Complete."})
            await self.websocket.send_json({"type": "turn", "data": "end"})
            self.running = False
            logger.info("Audio Simulation Ended.")

    def stop(self):
        self.running = False
