import os
import random
import sys
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ai/ lives one directory up (a sibling of backend/), so `import ai...` only
# resolves if the project root is on sys.path -- this makes it work no
# matter whether uvicorn was launched from backend/ or the project root.
#
# This block MUST run before the `from ai...` imports further down (the
# Programming Languages question bank and short-answer grader both live in
# ai/), otherwise it blows up with "ModuleNotFoundError: No module named 'ai'".
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from engine import level_from_xp, next_state
from keyword_grader import grade_keyword_answer
from course_content import (
    DBMS_QUESTIONS,
    DBMS_SHORT_ANSWER,
    DSA_QUESTIONS,
    DSA_SHORT_ANSWER,
    OS_QUESTIONS,
    OS_SHORT_ANSWER,
)

from ai.question_bank import MCQ_QUESTIONS as LANG_MCQ_QUESTIONS
from ai.question_bank import SHORT_ANSWER_QUESTIONS as LANG_SHORT_ANSWER_QUESTIONS
from ai.short_ans import grade_short_answer
from custom_upload import GenerationFailedError, PdfHasNoTextError, generate_questions_from_pdf

app = FastAPI()

# Wide open for hackathon speed — tighten later if it ever matters
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class AnswerRequest(BaseModel):
    question_id: str
    answer: Optional[str] = None  # null on a timeout (see PlayScreen's onAnswer(null, true))
    tier: int
    correct_streak: int
    wrong_streak: int
    total_xp: int
    mode: Optional[str] = None  # informational only -- grading always uses the stored question's real mode


# ---- Question bank: every course's content, combined and indexed ----
ALL_QUESTIONS: list[dict] = []
QUESTIONS_BY_ID: dict[str, dict] = {}

# (courseId, mode) -> [questions]   and   (courseId, mode) -> {tier: [questions]}
QUESTIONS_BY_COURSE_MODE: dict[tuple[str, str], list[dict]] = {}
QUESTIONS_BY_COURSE_MODE_TIER: dict[tuple[str, str], dict[int, list[dict]]] = {}

def register_questions(questions: list[dict]) -> None:
    """Folds a batch of questions into every in-memory index. Called once at
    startup for the built-in banks -- so a freshly generated PDF course is
    playable immediately, with no restart required."""
    for q in questions:
        ALL_QUESTIONS.append(q)
        QUESTIONS_BY_ID[str(q["id"])] = q
        key = (q["courseId"], q["mode"])
        QUESTIONS_BY_COURSE_MODE.setdefault(key, []).append(q)
        QUESTIONS_BY_COURSE_MODE_TIER.setdefault(key, {}).setdefault(q["tier"], []).append(q)


register_questions(
    OS_QUESTIONS
    + OS_SHORT_ANSWER
    + DBMS_QUESTIONS
    + DBMS_SHORT_ANSWER
    + DSA_QUESTIONS
    + DSA_SHORT_ANSWER
    + LANG_MCQ_QUESTIONS
    + LANG_SHORT_ANSWER_QUESTIONS
)

DEFAULT_COURSE = "os"
DEFAULT_MODE = "mcq"


def public_question(q: dict) -> dict:
    """Strip answer-revealing fields (correct_answer / keyword_clusters / dataset field) before sending to the client."""
    base = {
        "id": q["id"],
        "prompt": q["prompt"],
        "tier": q["tier"],
        "mode": q["mode"],
        "courseId": q.get("courseId"),
    }
    if q["mode"] == "mcq":
        base["options"] = q["options"]
    return base


def random_question_for(course_id: str, mode: str, tier: int, exclude_id: Optional[str] = None) -> dict:
    key = (course_id, mode)
    if key not in QUESTIONS_BY_COURSE_MODE:
        key = (DEFAULT_COURSE, DEFAULT_MODE)  # unknown course/mode combo -- don't 500, just degrade gracefully

    by_tier = QUESTIONS_BY_COURSE_MODE_TIER.get(key, {})
    pool = by_tier.get(tier) or []
    if not pool:
        for fallback_tier in (2, 1, 3):
            if by_tier.get(fallback_tier):
                pool = by_tier[fallback_tier]
                break
    if not pool:
        pool = QUESTIONS_BY_COURSE_MODE.get(key, [])

    candidates = [q for q in pool if q["id"] != exclude_id] or pool
    return random.choice(candidates)


def register_custom_questions(questions: list[dict]) -> None:
    """Replaces any previously-uploaded custom question set with a new one.

    Unlike the static course banks, "custom" content is generated at
    runtime, so these lookup dicts need to support being updated in place
    rather than only being built once at import time.
    """
    for key in [k for k in QUESTIONS_BY_COURSE_MODE if k[0] == "custom"]:
        for q in QUESTIONS_BY_COURSE_MODE[key]:
            QUESTIONS_BY_ID.pop(str(q["id"]), None)
        del QUESTIONS_BY_COURSE_MODE[key]
        QUESTIONS_BY_COURSE_MODE_TIER.pop(key, None)

    for q in questions:
        QUESTIONS_BY_ID[str(q["id"])] = q
        key = (q["courseId"], q["mode"])
        QUESTIONS_BY_COURSE_MODE.setdefault(key, []).append(q)
        QUESTIONS_BY_COURSE_MODE_TIER.setdefault(key, {}).setdefault(q["tier"], []).append(q)


def grade(question: dict, answer: Optional[str]):
    """Returns (is_correct, evaluation). evaluation always carries enough for the UI to show a real review screen -- the right answer, the player's own answer, and an explanation/feedback sentence."""
    raw_answer = answer or ""  # timeouts submit null -- treat like an empty answer, not a crash
    if question["mode"] == "mcq":
        is_correct = str(raw_answer).strip().lower() == str(question["correct_answer"]).strip().lower()
        evaluation = {
            "correct_answer": question["correct_answer"],
            "your_answer": answer,
            "explanation": question.get("explanation", ""),
        }
        return is_correct, evaluation

    if question["courseId"] == "lang":
        result = grade_short_answer(question, raw_answer)
    else:
        result = grade_keyword_answer(question, raw_answer)
    result["your_answer"] = answer
    return result["correct"], result


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/questions/all")
def get_all_questions(tier: Optional[int] = None):
    """Debug-only: full question data including answers, for validating content."""
    if tier is not None:
        return [q for q in ALL_QUESTIONS if q["tier"] == tier]
    return ALL_QUESTIONS


@app.get("/question/first")
def get_first_question(courseId: str = DEFAULT_COURSE, mode: str = DEFAULT_MODE):
    q = random_question_for(courseId, mode, tier=1)
    return public_question(q)


@app.post("/custom/generate")
async def generate_custom_questions(
    file: UploadFile = File(...),
    mode: str = Form("mcq"),
    count: int = Form(5),
):
    """Generates a fresh 'custom' course from an uploaded PDF via the local
    Ollama model, then registers it so /question/first and /answer can serve
    and grade it exactly like any other course -- no other endpoint changes
    needed."""
    if mode not in ("mcq", "short_answer"):
        raise HTTPException(status_code=400, detail="mode must be 'mcq' or 'short_answer'")

    safe_count = max(1, min(10, count))

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        questions = generate_questions_from_pdf(file_bytes, mode, safe_count)
    except PdfHasNoTextError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except GenerationFailedError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    register_custom_questions(questions)

    return {"courseId": "custom", "mode": mode, "count": len(questions)}


@app.post("/answer")
def submit_answer(payload: AnswerRequest):
    question = QUESTIONS_BY_ID.get(str(payload.question_id))
    if question is None:
        raise HTTPException(status_code=404, detail="Unknown question_id")

    safe_tier = max(1, min(3, payload.tier))   # clamp against bad/stale input

    is_correct, evaluation = grade(question, payload.answer)

    result = next_state(
        tier=safe_tier,
        correct_streak=payload.correct_streak,
        wrong_streak=payload.wrong_streak,
        correct=is_correct,
    )

    new_total_xp = payload.total_xp + result["xp_earned"]
    old_level = level_from_xp(payload.total_xp)
    new_level = level_from_xp(new_total_xp)

    next_q = random_question_for(question["courseId"], question["mode"], result["tier"], exclude_id=question["id"])

    return {
        "correct": is_correct,
        "evaluation": evaluation,  # accuracy/feedback for short-answer; null for mcq
        "xp_earned": result["xp_earned"],
        "total_xp": new_total_xp,
        "tier": result["tier"],
        "correct_streak": result["correct_streak"],
        "wrong_streak": result["wrong_streak"],
        "level": new_level,
        "level_up": new_level > old_level,
        "next_question": public_question(next_q),
    }
