from __future__ import annotations

import re
from dataclasses import dataclass

from dude.config import NormalizationConfig

_NUMBER_WORDS = {
    "zero": "0",
    "one": "1",
    "two": "2",
    "three": "3",
    "four": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8",
    "nine": "9",
}

_HOMOPHONE_NUMBERS = {
    "for": "4",
    "to": "2",
    "too": "2",
}

_PHRASE_REPLACEMENTS: list[tuple[str, str, str]] = [
    ("dash dash", "__DOUBLE_DASH__", "flags"),
    ("back slash", "__BACKSLASH__", "path"),
    ("open parenthesis", "(", "math"),
    ("close parenthesis", ")", "math"),
    ("open paren", "(", "math"),
    ("close paren", ")", "math"),
    ("equal sign", "=", "math"),
    ("divided by", "/", "math"),
    ("multiplied by", "*", "math"),
    ("underscore", "__UNDERSCORE__", "filename"),
    ("slash", "__SLASH__", "path"),
    ("dot", "__DOT__", "filename"),
    ("dash", "__DASH__", "flags"),
    ("plus", "+", "math"),
    ("minus", "-", "math"),
    ("times", "*", "math"),
    ("equals", "=", "math"),
]

_SYMBOL_JOIN = {
    "__DOT__": ".",
    "__UNDERSCORE__": "_",
    "__SLASH__": "/",
    "__BACKSLASH__": "\\",
    "__DASH__": "-",
    "__DOUBLE_DASH__": "--",
}

_MATH_OPERATORS = {"+", "-", "*", "/", "=", "(", ")"}
_NUMBER_CONTEXT_MARKERS = set(_SYMBOL_JOIN) | _MATH_OPERATORS


@dataclass(slots=True)
class TranscriptNormalization:
    text: str
    changed: bool
    categories: list[str]


class TranscriptNormalizer:
    def __init__(self, config: NormalizationConfig):
        self.config = config

    def normalize(self, text: str) -> TranscriptNormalization:
        original = " ".join(text.strip().split())
        if not self.config.enabled or not original:
            return TranscriptNormalization(text=original, changed=False, categories=[])

        working = original.lower()
        categories: list[str] = []

        if self.config.format_symbols:
            for phrase, replacement, category in _PHRASE_REPLACEMENTS:
                pattern = rf"\b{re.escape(phrase)}\b"
                updated = re.sub(pattern, f" {replacement} ", working)
                if updated != working:
                    categories.append(category)
                    working = updated

        tokens = working.split()
        if self.config.format_numbers and tokens:
            tokens = self._normalize_numbers(tokens, categories)

        if not categories:
            return TranscriptNormalization(text=original, changed=False, categories=[])

        normalized = self._join_tokens(tokens)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        changed = normalized != original
        return TranscriptNormalization(
            text=normalized if changed else original,
            changed=changed,
            categories=sorted(set(categories)),
        )

    def _normalize_numbers(self, tokens: list[str], categories: list[str]) -> list[str]:
        has_number_context = any(token in _NUMBER_CONTEXT_MARKERS for token in tokens)
        if not has_number_context:
            return tokens

        changed = False
        normalized: list[str] = []
        for index, token in enumerate(tokens):
            mapped = self._map_number_token(tokens, index)
            if mapped != token:
                changed = True
            normalized.append(mapped)

        if changed:
            categories.append("numbers")
        return normalized

    def _map_number_token(self, tokens: list[str], index: int) -> str:
        token = tokens[index]
        previous_token = tokens[index - 1] if index > 0 else ""
        next_token = tokens[index + 1] if index + 1 < len(tokens) else ""
        in_numeric_span = (
            previous_token in _NUMBER_CONTEXT_MARKERS
            or next_token in _NUMBER_CONTEXT_MARKERS
            or previous_token.isdigit()
            or next_token.isdigit()
        )
        if token in _NUMBER_WORDS:
            return _NUMBER_WORDS[token] if in_numeric_span else token
        if token in _HOMOPHONE_NUMBERS and in_numeric_span:
            return _HOMOPHONE_NUMBERS[token]
        return token

    def _join_tokens(self, tokens: list[str]) -> str:
        output = ""
        for token in tokens:
            if token in _SYMBOL_JOIN:
                output = output.rstrip() + _SYMBOL_JOIN[token]
                continue
            if token == ")":
                output = output.rstrip() + ")"
                continue
            if token == "(":
                if output and not output.endswith(" "):
                    output += " "
                output += "("
                continue
            if token in {"+", "-", "*", "/", "="}:
                output = output.rstrip() + f" {token} "
                continue
            if output and not output.endswith((" ", "(", "/", "\\", ".", "_", "-", "--")):
                output += " "
            output += token
        return output
