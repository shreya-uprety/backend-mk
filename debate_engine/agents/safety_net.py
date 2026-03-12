from debate_engine.config import PROMPTS_DIR
from debate_engine.agents.base import BaseAgent


class SafetyNetRedFlag(BaseAgent):
    agent_id = "agent_safety_net"
    agent_persona = "The Cautious Safety-Net"

    def __init__(self):
        super().__init__(PROMPTS_DIR / "red_flag_safety_net.md")


class SafetyNetPattern(BaseAgent):
    agent_id = "agent_safety_net"
    agent_persona = "The Cautious Safety-Net"

    def __init__(self):
        super().__init__(PROMPTS_DIR / "pattern_safety_net.md")
