from __future__ import annotations
import json
from pathlib import Path
from google import genai

from debate_engine.config import GOOGLE_API_KEY, GEMINI_MODEL, MAX_OUTPUT_TOKENS_AGENT, THINKING_BUDGET_AGENT
from debate_engine.utils import parse_llm_json

client = genai.Client(api_key=GOOGLE_API_KEY)


class BaseAgent:
    """Base class for debate agents. Each agent has a persona and a prompt file."""

    def __init__(self, agent_id: str, agent_persona: str, prompt_path: Path):
        self.agent_id = agent_id
        self.agent_persona = agent_persona
        self.system_prompt = prompt_path.read_text(encoding="utf-8")

    def analyze(self, patient_data: dict, module_context: str) -> dict:
        """Send patient data to Gemini with the agent's persona prompt.

        Args:
            patient_data: The full patient payload (enriched with risk_factors).
            module_context: Either 'red_flag' or 'pattern'.

        Returns:
            Parsed JSON dict with verdict/classification, confidence, reasoning, key_factors_cited.
        """
        user_message = (
            f"## Patient Data\n\n```json\n{json.dumps(patient_data, indent=2)}\n```"
        )

        config = {
            "temperature": 0,
            "max_output_tokens": MAX_OUTPUT_TOKENS_AGENT,
            "response_mime_type": "application/json",
        }
        if THINKING_BUDGET_AGENT > 0:
            config["thinking_config"] = {"thinking_budget": THINKING_BUDGET_AGENT}

        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                {"role": "user", "parts": [{"text": self.system_prompt + "\n\n" + user_message}]}
            ],
            config=config,
        )

        parsed = parse_llm_json(response.text)

        # Attach agent metadata
        parsed["agent_id"] = self.agent_id
        parsed["agent_persona"] = self.agent_persona

        # Extract token usage
        usage = getattr(response, "usage_metadata", None)
        parsed["_token_usage"] = {
            "input": getattr(usage, "prompt_token_count", 0) or 0,
            "output": getattr(usage, "candidates_token_count", 0) or 0,
        }

        return parsed
