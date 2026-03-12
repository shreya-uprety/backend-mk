import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    raise ValueError("GOOGLE_API_KEY not found in .env file")

GEMINI_MODEL = "gemini-2.5-flash"

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

# Upper Limits of Normal (ULN) for lab values
ULN = {
    "ALT": 40,
    "AST": 40,
    "ALP": 130,
    "Bilirubin": 20,
    "Albumin_low": 35,  # lower bound of normal
    "GGT": 50,
}

# Agent output token caps
MAX_OUTPUT_TOKENS_AGENT = 2000
MAX_OUTPUT_TOKENS_SYNTHESIZER = 4000
MAX_OUTPUT_TOKENS_EXTRACTOR = 4000

# Thinking budgets — 0 disables internal reasoning (faster, cheaper)
# Agents don't need thinking: their prompts are specific enough
# Synthesizer gets a small budget for resolving disagreements
THINKING_BUDGET_AGENT = 0
THINKING_BUDGET_SYNTHESIZER = 1024
THINKING_BUDGET_EXTRACTOR = 0

# Short-circuit: skip synthesizer if all agents agree unanimously
UNANIMOUS_CONFIDENCE_THRESHOLD = 0.85
