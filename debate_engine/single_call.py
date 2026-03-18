"""Utility for single Gemini API calls (non-debate).

Used by handlers that don't need the 3-agent debate pattern —
investigation recommendations, diagnosis suggestions, education content, etc.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from google import genai

from debate_engine.config import (
    GOOGLE_API_KEY, GEMINI_MODEL, PROMPTS_DIR,
    MAX_OUTPUT_TOKENS_AGENT, THINKING_BUDGET_SYNTHESIZER,
)
from debate_engine.utils import parse_llm_json

client = genai.Client(api_key=GOOGLE_API_KEY)


def call_gemini(
    prompt_file: str,
    patient_data: dict,
    extra_context: dict | None = None,
    thinking_budget: int = THINKING_BUDGET_SYNTHESIZER,
    max_output_tokens: int = MAX_OUTPUT_TOKENS_AGENT,
) -> dict:
    """Single Gemini call with a prompt file and patient data.

    Args:
        prompt_file: Name of the prompt markdown file in PROMPTS_DIR.
        patient_data: Patient payload or context dict.
        extra_context: Additional context to include (e.g., prior results).
        thinking_budget: Token budget for thinking (0 to disable).
        max_output_tokens: Max output tokens.

    Returns:
        Parsed JSON dict with _token_usage and _processing_time_ms keys.
    """
    start = time.time()

    prompt = (PROMPTS_DIR / prompt_file).read_text(encoding="utf-8")

    user_message = f"{prompt}\n\n## Patient Data\n\n```json\n{json.dumps(patient_data, indent=2)}\n```"

    if extra_context:
        user_message += f"\n\n## Additional Context\n\n```json\n{json.dumps(extra_context, indent=2)}\n```"

    config = {
        "max_output_tokens": max_output_tokens,
        "response_mime_type": "application/json",
    }
    if thinking_budget > 0:
        config["thinking_config"] = {"thinking_budget": thinking_budget}

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[{"role": "user", "parts": [{"text": user_message}]}],
        config=config,
    )

    parsed = parse_llm_json(response.text)

    usage = getattr(response, "usage_metadata", None)
    parsed["_token_usage"] = {
        "input": getattr(usage, "prompt_token_count", 0) or 0,
        "output": getattr(usage, "candidates_token_count", 0) or 0,
    }
    parsed["_processing_time_ms"] = int((time.time() - start) * 1000)

    return parsed
