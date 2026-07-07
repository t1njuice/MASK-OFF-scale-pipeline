"""PROMPT EDITOR agent: fold reviewer feedback into generator prompt lessons."""

import json
import os
from pathlib import Path

from . import config
from .llm import call_json
from .schemas import SeedLearningUpdate

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
    return _clean_lessons(lessons, allow_empty=False)


def _clean_lessons(lessons: list[str], *, allow_empty: bool) -> list[str]:
    if not lessons:
        if allow_empty:
            return []
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


def _ensure_lesson_markers(prompt_text: str) -> str:
    has_start = START in prompt_text
    has_end = END in prompt_text
    if has_start != has_end:
        raise ValueError("partial prompt-editor markers in generator prompt")
    if has_start:
        return prompt_text

    block = f"## Learned adjustments\n\n{START}\n{END}\n\n"
    marker = "## Revision mode"
    if marker in prompt_text:
        before, after = prompt_text.split(marker, 1)
        return f"{before.rstrip()}\n\n{block}{marker}{after}"
    return f"{prompt_text.rstrip()}\n\n{block}"


def extract_lessons(prompt_text: str) -> list[str]:
    if START not in prompt_text and END not in prompt_text:
        return []
    if START not in prompt_text or END not in prompt_text:
        raise ValueError("partial prompt-editor markers in generator prompt")
    section = prompt_text.split(START, 1)[1].split(END, 1)[0]
    return [
        line.strip()[2:].strip()
        for line in section.splitlines()
        if line.strip().startswith("- ")
    ]


def replace_lessons(prompt_text: str, lessons: list[str]) -> str:
    clean = validate_lessons(lessons)
    prompt_text = _ensure_lesson_markers(prompt_text)

    before, rest = prompt_text.split(START, 1)
    _old, after = rest.split(END, 1)
    body = "\n".join(f"- {lesson}" for lesson in clean)
    return f"{before}{START}\n{body}\n{END}{after}"


def _user_message(
    trigger: str,
    old_lessons: list[str],
    signals: list[str],
    error: str | None,
) -> str:
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


def _load_pool(path: Path) -> dict:
    if not path.exists():
        return {"lessons": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_pool(path: Path, pool: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, json.dumps(pool, ensure_ascii=False, indent=2) + "\n")


def _seed_pool(pool: dict, old_lessons: list[str]) -> None:
    by_text = {item.get("text"): item for item in pool.get("lessons", [])}
    for lesson in old_lessons:
        if lesson in by_text:
            by_text[lesson]["promoted"] = True
            continue
        pool.setdefault("lessons", []).append(
            {
                "text": lesson,
                "support": config.LESSON_PROMOTION_THRESHOLD,
                "promoted": True,
                "last_seed_summary": "",
            }
        )


def _trim_pool(pool: dict) -> None:
    promoted = [item for item in pool.get("lessons", []) if item.get("promoted")]
    candidates = [item for item in pool.get("lessons", []) if not item.get("promoted")]
    room = max(config.LESSON_POOL_MAX_ITEMS - len(promoted), 0)
    candidates = sorted(
        candidates,
        key=lambda item: item.get("support", 0),
        reverse=True,
    )
    pool["lessons"] = promoted + candidates[:room]


def _promoted_lessons(pool: dict) -> list[str]:
    return [
        item["text"]
        for item in pool.get("lessons", [])
        if item.get("promoted")
    ][:MAX_LESSONS]


def _update_lesson_pool(
    update: SeedLearningUpdate,
    old_lessons: list[str],
    pool_path: Path,
) -> list[str]:
    pool = _load_pool(pool_path)
    pool.setdefault("lessons", [])
    _seed_pool(pool, old_lessons)

    retire = set(_clean_lessons(update.retire_lessons, allow_empty=True))
    if retire:
        pool["lessons"] = [
            item for item in pool["lessons"] if item.get("text") not in retire
        ]

    proposed = _clean_lessons(update.proposed_lessons, allow_empty=True)
    if update.evidence != "skip":
        by_text = {item.get("text"): item for item in pool["lessons"]}
        for lesson in proposed:
            item = by_text.get(lesson)
            if item is None:
                item = {
                    "text": lesson,
                    "support": 0,
                    "promoted": False,
                    "last_seed_summary": "",
                }
                pool["lessons"].append(item)
                by_text[lesson] = item
            item["support"] = int(item.get("support", 0)) + 1
            item["last_seed_summary"] = update.seed_summary
            if (
                update.evidence == "strong"
                or item["support"] >= config.LESSON_PROMOTION_THRESHOLD
            ):
                item["promoted"] = True

    _trim_pool(pool)
    _save_pool(pool_path, pool)
    return _promoted_lessons(pool)


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
    pool_path: Path | None = None,
) -> dict:
    path = prompt_path or (config.PROMPTS_DIR / "generator_system.md")
    lessons_path = pool_path or config.LESSON_POOL_PATH
    old_text = path.read_text(encoding="utf-8")
    old_lessons = extract_lessons(old_text)
    last_error = None

    for _attempt in range(2):
        try:
            result = call_json(
                config.PROMPT_EDITOR_MODEL,
                config.PROMPT_EDITOR_EFFORT,
                _system(),
                _user_message(trigger, old_lessons, signals, last_error),
                SeedLearningUpdate,
                config.PROMPT_EDITOR_MAX_TOKENS,
                retries=0,
            )
            update, actual_model = result[:2]
            usage = result[2] if len(result) > 2 else {}
            promoted_lessons = _update_lesson_pool(update, old_lessons, lessons_path)
            applied = bool(promoted_lessons and promoted_lessons != old_lessons)
            if applied:
                _write_atomic(path, replace_lessons(old_text, promoted_lessons))
            return {
                "applied": applied,
                "trigger": trigger,
                "editor_model": actual_model,
                "seed_summary": update.seed_summary,
                "evidence": update.evidence,
                "proposed_lessons": update.proposed_lessons,
                "retire_lessons": update.retire_lessons,
                "old_lessons": old_lessons,
                "new_lessons": promoted_lessons if applied else old_lessons,
                "usage": usage,
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
        "usage": {},
        "error": last_error,
    }
