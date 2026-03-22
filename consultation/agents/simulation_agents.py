"""Simulation AI agents for the consultation module.

Adapted from the consultation project's agents. Uses Gemini for:
- Diagnosis generation (hepatology-specific and general)
- Question generation and ranking
- Patient education
- Clinical analytics
- Consultation report generation
"""
import json
import logging
import os
from pathlib import Path
from google import genai
from google.genai import types

logger = logging.getLogger("consultation")

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "system_prompts"
GEMINI_MODEL = "gemini-2.5-flash"
API_KEY = os.getenv("GOOGLE_API_KEY", "")


class BaseLogicAgent:
    """Base agent with lazy Gemini client initialization."""
    _client = None

    @classmethod
    def get_client(cls):
        if cls._client is None:
            cls._client = genai.Client(api_key=API_KEY)
        return cls._client

    def _load_prompt(self, filename):
        path = PROMPTS_DIR / filename
        if path.exists():
            return path.read_text(encoding="utf-8")
        return ""

    async def _call_gemini(self, system_prompt, user_prompt, model=None, json_output=True):
        client = self.get_client()
        config = {
            "temperature": 0,
            "max_output_tokens": 8000,
        }
        if json_output:
            config["response_mime_type"] = "application/json"

        response = client.models.generate_content(
            model=model or GEMINI_MODEL,
            contents=[
                {"role": "user", "parts": [{"text": f"{system_prompt}\n\n{user_prompt}"}]}
            ],
            config=config,
        )

        if json_output:
            try:
                text = response.text.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0]
                return json.loads(text)
            except (json.JSONDecodeError, IndexError):
                return {}
        return response.text


class DiagnosisAgent(BaseLogicAgent):
    """Generates differential diagnoses from consultation transcript."""

    async def generate_diagnoses(self, transcript, patient_info, existing_questions=None):
        system = self._load_prompt("consolidated_agent.md") or (
            "You are a hepatology diagnostic AI. Analyze the consultation transcript and generate "
            "differential diagnoses. Return JSON array of diagnoses."
        )
        user = (
            f"## Patient Information\n{patient_info}\n\n"
            f"## Consultation Transcript\n{json.dumps(transcript, indent=2)}\n\n"
            f"## Existing Questions\n{json.dumps(existing_questions or [], indent=2)}\n\n"
            "Generate differential diagnoses with reasoning. Return JSON:\n"
            '[\n  {\n    "did": "D001",\n    "diagnosis": "...",\n    "indicators_point": ["..."],\n'
            '    "reasoning": "...",\n    "followup_question": "...",\n'
            '    "probability": "Low|Medium|High",\n    "rank": 1,\n'
            '    "severity": "High|Moderate|Low"\n  }\n]'
        )
        return await self._call_gemini(system, user)


class QuestionAgent(BaseLogicAgent):
    """Generates and ranks clinical questions."""

    async def generate_questions(self, transcript, diagnoses, existing_questions):
        system = self._load_prompt("question_merger.md") or (
            "Generate focused clinical questions based on the consultation so far. "
            "Return questions that would help narrow the differential diagnosis."
        )
        user = (
            f"## Transcript\n{json.dumps(transcript, indent=2)}\n\n"
            f"## Current Diagnoses\n{json.dumps(diagnoses, indent=2)}\n\n"
            f"## Already Asked\n{json.dumps(existing_questions, indent=2)}\n\n"
            "Generate new questions. Return JSON array:\n"
            '[{"qid": "Q001", "content": "...", "rank": 1, "domain": "...", '
            '"clinical_intent": "...", "tags": ["..."]}]'
        )
        return await self._call_gemini(system, user)

    async def rank_questions(self, transcript, questions):
        system = self._load_prompt("question_ranker.md") or (
            "Rank these clinical questions by priority for the current consultation."
        )
        user = (
            f"## Transcript\n{transcript}\n\n"
            f"## Questions\n{json.dumps(questions, indent=2)}\n\n"
            "Re-rank by clinical priority. Return: {\"ranked\": [...]}"
        )
        return await self._call_gemini(system, user)


class EducationAgent(BaseLogicAgent):
    """Generates patient education content."""

    async def generate_education(self, transcript, existing_education):
        system = self._load_prompt("patient_education_agent.md") or (
            "Generate patient education points based on the consultation. "
            "Focus on conditions discussed and lifestyle recommendations."
        )
        user = (
            f"## Consultation\n{json.dumps(transcript, indent=2)}\n\n"
            f"## Already Covered\n{json.dumps(existing_education, indent=2)}\n\n"
            "Generate new education points. Return JSON array:\n"
            '[{"id": "E001", "content": "...", "category": "...", "priority": "high|medium|low"}]'
        )
        return await self._call_gemini(system, user)


class AnalyticsAgent(BaseLogicAgent):
    """Scores nurse consultation performance."""

    async def analyze_consultation(self, transcript):
        system = self._load_prompt("chat_model_system.md") or (
            "Analyze the nurse's consultation performance. Score empathy, clarity, "
            "thoroughness, and clinical accuracy."
        )
        user = (
            f"## Consultation Transcript\n{json.dumps(transcript, indent=2)}\n\n"
            "Analyze consultation quality. Return JSON:\n"
            '{"empathy_score": 0-100, "clarity_score": 0-100, "thoroughness_score": 0-100, '
            '"clinical_accuracy": 0-100, "overall_score": 0-100, '
            '"strengths": ["..."], "improvements": ["..."]}'
        )
        return await self._call_gemini(system, user)


class ChecklistAgent(BaseLogicAgent):
    """Generates clinical assessment checklist."""

    async def generate_checklist(self, transcript, diagnoses, questions, education):
        system = self._load_prompt("clinical_checklist_agent.md") or (
            "Generate a clinical assessment checklist for this consultation."
        )
        user = (
            f"## Transcript\n{json.dumps(transcript, indent=2)}\n\n"
            f"## Diagnoses\n{json.dumps(diagnoses, indent=2)}\n\n"
            f"## Questions\n{json.dumps(questions, indent=2)}\n\n"
            f"## Education\n{json.dumps(education, indent=2)}\n\n"
            "Generate compliance checklist. Return JSON array:\n"
            '[{"item": "...", "status": "completed|pending|missing", "notes": "..."}]'
        )
        return await self._call_gemini(system, user)


class ReportAgent(BaseLogicAgent):
    """Generates comprehensive consultation report."""

    async def generate_report(self, transcript, diagnoses, questions, education, analytics):
        system = self._load_prompt("clinical_agent.md") or (
            "Generate a comprehensive clinical consultation report."
        )
        user = (
            f"## Transcript\n{json.dumps(transcript, indent=2)}\n\n"
            f"## Diagnoses\n{json.dumps(diagnoses, indent=2)}\n\n"
            f"## Questions\n{json.dumps(questions, indent=2)}\n\n"
            f"## Education\n{json.dumps(education, indent=2)}\n\n"
            f"## Analytics\n{json.dumps(analytics, indent=2)}\n\n"
            "Generate comprehensive clinical report. Return JSON:\n"
            '{"summary": "...", "presenting_complaint": "...", '
            '"history_of_presenting_illness": "...", '
            '"differential_diagnosis": [...], "plan": [...], '
            '"recommendations": [...], "follow_up": "..."}'
        )
        return await self._call_gemini(system, user)
