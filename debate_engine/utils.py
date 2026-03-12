"""Shared utilities for the debate engine."""
from __future__ import annotations
import json
import re


def parse_llm_json(raw_text: str) -> dict:
    """Robustly parse JSON from LLM output, handling markdown fences and minor issues."""
    text = raw_text.strip()

    # Remove markdown code fences
    text = re.sub(r"^```(?:json)?\s*\n?", "", text)
    text = re.sub(r"\n?```\s*$", "", text)
    text = text.strip()

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object within the text
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Try fixing common issues: trailing commas
    fixed = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Try fixing: single quotes to double quotes
    fixed2 = text.replace("'", '"')
    try:
        return json.loads(fixed2)
    except json.JSONDecodeError:
        pass

    raise ValueError(f"Could not parse JSON from LLM output: {text[:200]}...")
