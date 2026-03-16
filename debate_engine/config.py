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
MAX_OUTPUT_TOKENS_AGENT = 4000
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


# ── Module configurations ─────────────────────────────────────────────
# Each entry defines the agents, prompts, and output shape for a debate module.
# To add a new module, add an entry here and create the prompt files.
# No orchestrator or agent code changes needed.

MODULES = {
    "red_flag": {
        "agents": [
            {"id": "agent_safety_net", "persona": "The Cautious Safety-Net", "prompt": "red_flag_safety_net.md"},
            {"id": "agent_guideline", "persona": "The Guideline Adherent", "prompt": "red_flag_guideline.md"},
            {"id": "agent_statistician", "persona": "The Statistical Analyst", "prompt": "red_flag_statistician.md"},
        ],
        "synthesizer_prompt": "red_flag_synthesizer.md",
        "decision_field": "verdict",
        "output_decision_key": "final_decision",
        "output_args_for_key": "key_arguments_for_red_flag",
        "output_args_against_key": "key_arguments_against_red_flag",
        "consensus_actions": {
            "RED_FLAG_PRESENT": "Urgent specialist review required",
            "_default": "Proceed to pattern analysis",
        },
    },
    "pattern": {
        "agents": [
            {"id": "agent_safety_net", "persona": "The Cautious Safety-Net", "prompt": "pattern_safety_net.md"},
            {"id": "agent_guideline", "persona": "The Guideline Adherent", "prompt": "pattern_guideline.md"},
            {"id": "agent_statistician", "persona": "The Statistical Analyst", "prompt": "pattern_statistician.md"},
        ],
        "synthesizer_prompt": "pattern_synthesizer.md",
        "decision_field": "classification",
        "output_decision_key": "final_classification",
        "output_args_for_key": "key_arguments_for_primary",
        "output_args_against_key": "key_arguments_against_primary",
        "consensus_actions": {
            "_default": "Follow {decision} pathway guidelines",
        },
    },
}
