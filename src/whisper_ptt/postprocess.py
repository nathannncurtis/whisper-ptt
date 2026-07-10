"""Text post-processing pipeline.

Deliberately structured as an ordered list of str -> str steps so a future
LLM cleanup pass can be appended (or inserted) without touching callers:

    STEPS.append(llm_cleanup)   # e.g. punctuation/formatting model
"""

from __future__ import annotations

from typing import Callable

Processor = Callable[[str], str]


def _strip(text: str) -> str:
    return text.strip()


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


STEPS: list[Processor] = [
    _strip,
    _capitalize_first,
]


def apply(text: str) -> str:
    for step in STEPS:
        text = step(text)
    return text
