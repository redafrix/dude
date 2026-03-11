from __future__ import annotations

from dude.config import PersonaConfig
from dude.persona import PersonaController


def test_persona_greeting_changes_with_mode() -> None:
    neutral = PersonaController(PersonaConfig(mode="neutral", operator_name="Reda"))
    witty = PersonaController(PersonaConfig(mode="witty", operator_name="Reda"))

    assert neutral.greeting("Hi, what can I help you with?") == "Hi, what can I help you with?"
    assert witty.greeting("Hi, what can I help you with?") == "Hi. What can I help you with?"


def test_persona_approval_prompt_uses_operator_name() -> None:
    persona = PersonaController(PersonaConfig(mode="narcissistic", operator_name="Reda"))

    result = persona.approval_required("network")

    assert "Reda" in result
    assert "network" in result
