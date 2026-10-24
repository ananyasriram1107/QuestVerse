"""
Tops a level up when its slice of the question bank is too small.

With the shipped banks every level already reaches MIN_LEVEL_QUESTIONS, so this only
runs for a level whose bank is short (a smaller course, an edited levels_config, or a
removed question). It reuses the PDF pipeline's building blocks -- the same local Ollama
model, the same prompts and the same JSON parser (custom_upload) -- but takes its source
material from the course's own existing questions, so the new questions stay on the
course's subject.

What is produced is validated and de-duplicated against every existing question, then
saved to generated_questions.json next to the database. Saving matters: a level's question set is
fixed, so once a question was generated for it, it must come back the same after a
restart. Failures raise LevelFillError with a message that is safe to show the player;
the level simply does not start until the minimum is met.
"""

import hashlib
import json
import os
import re
import tempfile
import threading
from typing import Callable, Optional

import attempt_store
from ai import ollama_client
from levels_config import MIN_LEVEL_QUESTIONS
import custom_upload

# Saved next to the database, so on a deployment it lands on the same persistent disk.
GENERATED_PATH = os.environ.get(
    "QUESTVERSE_GENERATED",
    os.path.join(os.path.dirname(os.path.abspath(attempt_store.DB_PATH)), "generated_questions.json"),
)
MAX_SOURCE_CHARS = 3500
FILL_LOCK = threading.Lock()   # one top-up at a time; the second caller re-checks after the first finishes


class LevelFillError(Exception):
    """A level could not be topped up to the minimum. `message` is safe to show the player."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", str(text).lower())).strip()


def load_generated() -> list:
    """Previously generated questions (empty if none or the file is unreadable)."""
    try:
        with open(GENERATED_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return [q for q in data if isinstance(q, dict) and q.get("id") and q.get("prompt")]
    except (OSError, ValueError):
        return []


def _save_generated(questions: list) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(GENERATED_PATH)), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(GENERATED_PATH)), suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)
    os.replace(tmp, GENERATED_PATH)   # atomic: a crash never leaves a half-written file


def _valid(question: dict) -> bool:
    if not str(question.get("prompt", "")).strip():
        return False
    if question["mode"] == "mcq":
        options = question.get("options", [])
        return (len(options) == 4 and len(set(map(_norm, options))) == 4
                and question.get("correct_answer") in options)
    return len(question.get("keyword_clusters", [])) >= 2


def _source_text(course_id: str, all_questions: list) -> str:
    parts = []
    for q in all_questions:
        if q["courseId"] != course_id:
            continue
        answer = q.get("explanation") or q.get("model_answer") or ""
        parts.append(f"{q['prompt']} {answer}".strip())
    return "\n".join(parts)[:MAX_SOURCE_CHARS]


def _shortfall(level: dict, all_questions: list) -> Optional[dict]:
    """The first pool of the level's selector that has fewer questions than it asks for."""
    for pool in level["selector"]["pools"]:
        have = sum(1 for q in all_questions if q["courseId"] == level["course_id"]
                   and q["mode"] == pool["mode"] and q["tier"] == pool["tier"])
        if have < pool["count"]:
            return {**pool, "missing": pool["count"] - have}
    return None


def generate_questions(level: dict, all_questions: list, need: int, generate: Optional[Callable] = None) -> list:
    """Up to `need` new validated, unique questions for the level's course. Raises
    LevelFillError when the model is unreachable or yields nothing usable."""
    generate = generate or ollama_client.generate     # looked up at call time so it can be swapped
    pool = _shortfall(level, all_questions) or level["selector"]["pools"][-1]
    mode, tier, course_id = pool["mode"], pool["tier"], level["course_id"]
    count = need + 2    # a few spares: some outputs are rejected as duplicates or malformed
    template = custom_upload._MCQ_SYSTEM_PROMPT if mode == "mcq" else custom_upload._SHORT_ANSWER_SYSTEM_PROMPT
    prompt = f"Source material:\n{_source_text(course_id, all_questions)}\n\nWrite {count} NEW questions on this subject."
    known = {_norm(q["prompt"]) for q in all_questions}
    fresh: list = []
    unreachable = False
    for _ in range(2):
        try:
            raw = generate(prompt, system=template % {"count": count}, timeout=custom_upload.GENERATION_TIMEOUT_S)
            unreachable = False
            parsed = custom_upload._parse_generated(raw, mode, count)
        except ollama_client.OllamaUnavailable:
            unreachable = True
            continue
        except (ValueError, KeyError, TypeError):
            continue
        for q in parsed:
            key = _norm(q["prompt"])
            if key in known or not _valid({**q, "mode": mode}):
                continue
            known.add(key)
            q["id"] = f"gen-{course_id}-{mode}-{hashlib.sha1(key.encode()).hexdigest()[:8]}"
            q["courseId"], q["tier"], q["generated"] = course_id, tier, True
            fresh.append(q)
        if len(fresh) >= need:
            break
    if not fresh:
        raise LevelFillError(
            "Your companion couldn't prepare this level's questions right now. Make sure Ollama is running and try again."
            if unreachable else "This level doesn't have enough questions yet. Please try again later."
        )
    return fresh[:need + 2]


def top_up(level: dict, all_questions: list, generate: Optional[Callable] = None) -> list:
    """Generates and saves enough questions for `level` to reach MIN_LEVEL_QUESTIONS; returns
    the new questions (the caller registers them and rebuilds the catalog)."""
    need = MIN_LEVEL_QUESTIONS - level["question_count"]
    new = generate_questions(level, all_questions, need, generate)
    _save_generated(load_generated() + new)
    return new
