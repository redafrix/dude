from __future__ import annotations

from dude.config import PersonaConfig


class PersonaController:
    def __init__(self, config: PersonaConfig) -> None:
        self.config = config

    def greeting(self, default_text: str) -> str:
        if self.config.mode == "witty":
            return "Hi. What can I help you with?"
        if self.config.mode == "narcissistic":
            return "Dude is online. What masterpiece are we handling?"
        return default_text

    def approval_required(self, approval_phrase: str) -> str:
        name = self.config.operator_name.strip() or "operator"
        if self.config.mode == "witty":
            return (
                f"{name}, I need approval for a {approval_phrase} task. "
                "Say approve latest task, or run dude approve --latest."
            )
        if self.config.mode == "narcissistic":
            return (
                f"{name}, I require approval for this {approval_phrase} task. "
                "Authorize it with approve latest task or dude approve --latest."
            )
        return (
            f"{name}, I need approval for a {approval_phrase} task. "
            "Say approve latest task, or run dude approve --latest."
        )

    def failure(self, detail: str | None = None) -> str:
        if self.config.mode == "witty":
            base = "That one went sideways."
        elif self.config.mode == "narcissistic":
            base = "That task failed, despite my otherwise excellent standards."
        else:
            base = "That task failed."
        if detail:
            return f"{base} {detail}"
        return base

    def stop_response(self) -> str:
        if self.config.mode == "narcissistic":
            return "Standing down. Summon me again with Alt plus A."
        return "Stopping. Say Alt plus A when you want me again."

    def status_response(self, state_value: str) -> str:
        spoken_state = state_value.replace("_", " ")
        if self.config.mode == "witty":
            return f"I am {spoken_state} and ready."
        if self.config.mode == "narcissistic":
            return f"I am {spoken_state}, as expected."
        return f"I am {spoken_state} and listening."

    def builtin_fallback(self) -> str:
        if self.config.mode == "witty":
            return "I heard you. The deeper agent skills are still loading in stages."
        if self.config.mode == "narcissistic":
            return "I heard you. The more advanced capabilities are still beneath construction."
        return "I heard you. Milestone one only supports greeting and control commands so far."
