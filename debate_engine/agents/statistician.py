from debate_engine.config import PROMPTS_DIR
from debate_engine.agents.base import BaseAgent


class StatisticianRedFlag(BaseAgent):
    agent_id = "agent_statistician"
    agent_persona = "The Statistical Analyst"

    def __init__(self):
        super().__init__(PROMPTS_DIR / "red_flag_statistician.md")


class StatisticianPattern(BaseAgent):
    agent_id = "agent_statistician"
    agent_persona = "The Statistical Analyst"

    def __init__(self):
        super().__init__(PROMPTS_DIR / "pattern_statistician.md")
