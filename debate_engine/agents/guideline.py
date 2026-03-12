from debate_engine.config import PROMPTS_DIR
from debate_engine.agents.base import BaseAgent


class GuidelineRedFlag(BaseAgent):
    agent_id = "agent_guideline"
    agent_persona = "The Guideline Adherent"

    def __init__(self):
        super().__init__(PROMPTS_DIR / "red_flag_guideline.md")


class GuidelinePattern(BaseAgent):
    agent_id = "agent_guideline"
    agent_persona = "The Guideline Adherent"

    def __init__(self):
        super().__init__(PROMPTS_DIR / "pattern_guideline.md")
