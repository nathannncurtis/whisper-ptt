"""Text post-processing pipeline.

Deliberately structured as an ordered list of str -> str steps so a future
LLM cleanup pass can be appended (or inserted) without touching callers:

    STEPS.append(llm_cleanup)   # e.g. punctuation/formatting model
"""

from __future__ import annotations

import re
from typing import Callable

Processor = Callable[[str], str]


def _strip(text: str) -> str:
    return text.strip()


def _collapse_whitespace(text: str) -> str:
    """Newlines/tabs -> single spaces. Critical: the AHK side types the text
    with SendText, where a newline is an Enter keypress — which submits chat
    inputs. Speech transcripts never legitimately contain newlines."""
    return re.sub(r"\s+", " ", text)


def _capitalize_first(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


_FILLER_RE = re.compile(r"\b(?:um+|uh+|erm+)\b[,.]?\s*", re.IGNORECASE)


def _strip_fillers(text: str) -> str:
    """Cheap filler removal so short utterances that skip the LLM pass still
    lose their um/uh. Harmless before the LLM (less for it to do)."""
    return _FILLER_RE.sub("", text)


STEPS: list[Processor] = [
    _strip_fillers,
    _collapse_whitespace,
    _strip,
    _capitalize_first,
]


def apply(text: str) -> str:
    for step in STEPS:
        text = step(text)
    return text
