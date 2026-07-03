"""PROMPT EDITOR agent: fold reviewer feedback into generator prompt lessons."""

import os
from pathlib import Path

from . import config
from .llm import call_json
from .schemas import PromptLessons

START = "<!-- prompt-editor:start -->"
END = "<!-- prompt-editor:end -->"
MAX_LESSONS = 8
MAX_LESSON_CHARS = 220
_SYSTEM = None

_FORMAT_TERMS = (
    "json",
    "schema",
    "output format",
    "six keys",
    "six-field",
    "return only",
    "markdown fence",
    "code fence",
)


def _system() -> str:
    global _SYSTEM
    if _SYSTEM is None:
        _SYSTEM = (config.PROMPTS_DIR / "prompt_editor_system.md").read_text(
            encoding="utf-8"
        )
    return _SYSTEM


def validate_lessons(lessons: list[str]) -> list[str]:
    if not lessons:
        raise ValueError("lessons must not be empty")
    if len(lessons) > MAX_LESSONS:
        raise ValueError("lessons must contain at most 8 items")

    cleaned = []
    for lesson in lessons:
        text = str(lesson).strip()
        if text.startswith("- "):
            text = text[2:].strip()
        text = " ".join(text.split())
        if not text:
            raise ValueError("lessons must not be empty")
        if len(text) > MAX_LESSON_CHARS:
            raise ValueError(f"lesson exceeds {MAX_LESSON_CHARS} characters")
        lower = text.lower()
        if any(term in lower for term in _FORMAT_TERMS):
            raise ValueError("lesson appears to change schema/output format")
        cleaned.append(text)
    return cleaned


def extract_lessons(prompt_text: str) -> list[str]:
    if START not in prompt_text or END not in prompt_text:
        return []
    section = prompt_text.split(START, 1)[1].split(END, 1)[0]
    return [
        line.strip()[2:].strip()
        for line in section.splitlines()
        if line.strip().startswith("- ")
    ]


def replace_lessons(prompt_text: str, lessons: list[str]) -> str:
    clean = validate_lessons(lessons)
    if START not in prompt_text or END not in prompt_text:
        raise ValueError("generator prompt is missing prompt-editor markers")

    before, rest = prompt_text.split(START, 1)
    _old, after = rest.split(END, 1)
    body = "\n".join(f"- {lesson}" for lesson in clean)
    return f"{before}{START}\n{body}\n{END}{after}"


def _user_message(trigger: str, old_lessons: list[str], signals: list[str], error: str | None) -> str:
    old = "\n".join(f"- {lesson}" for lesson in old_lessons) or "(none)"
    feedback = "\n\n---\n\n".join(signals) or "(none)"
    retry = f"\n\nPrevious invalid output: {error}\n" if error else ""
    return f"""Trigger: {trigger}

Current learned lessons:
{old}

Reviewer feedback + metrics:
{feedback}
{retry}
Return ONLY the JSON object."""


def _write_atomic(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def snapshot_generator_prompt() -> None:
    source = config.PROMPTS_DIR / "generator_system.md"
    target = config.PROMPT_SNAPSHOT_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(target, source.read_text(encoding="utf-8"))


def edit_generator_prompt(
    *,
    trigger: str,
    signals: list[str],
    prompt_path: Path | None = None,
) -> dict:
    path = prompt_path or (config.PROMPTS_DIR / "generator_system.md")
    old_text = path.read_text(encoding="utf-8")
    old_lessons = extract_lessons(old_text)
    last_error = None

    for _attempt in range(2):
        try:
            update, actual_model = call_json(
                config.PROMPT_EDITOR_MODEL,
                config.PROMPT_EDITOR_EFFORT,
                _system(),
                _user_message(trigger, old_lessons, signals, last_error),
                PromptLessons,
                config.PROMPT_EDITOR_MAX_TOKENS,
                retries=0,
            )
            new_lessons = validate_lessons(update.lessons)
            _write_atomic(path, replace_lessons(old_text, new_lessons))
            return {
                "applied": True,
                "trigger": trigger,
                "editor_model": actual_model,
                "old_lessons": old_lessons,
                "new_lessons": new_lessons,
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 - malformed editor output is discardable
            last_error = str(exc)

    return {
        "applied": False,
        "trigger": trigger,
        "editor_model": config.PROMPT_EDITOR_MODEL,
        "old_lessons": old_lessons,
        "new_lessons": old_lessons,
        "error": last_error,
    }
