import logging
import os
import random
import sqlite3
import sys
import time
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
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

from engine import level_from_xp
import accounts
import ai_hint
import cors_config
import level_fill
import weekly_report
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
import attempt_store
from guess_analysis import incomplete_result, analyze_attempts
from quest_session import (
    LOCK, QuestSession, SessionError, apply_answer, attempt_view, create_session,
    apply_fifty_fifty, fifty_fifty_available, get_session, register_session, set_question_lookup,
)
from levels_config import COURSE_TITLES as LEVEL_COURSE_TITLES
from progression import build_catalog, compute_progress, level_states, next_level_id, public_level, stars_for
from topic_insights import recommend, topic_performance
from custom_upload import GenerationFailedError, PdfHasNoTextError, generate_questions_from_pdf

log = logging.getLogger(__name__)
app = FastAPI()

# Everything except these needs a logged-in user. Registered BEFORE the CORS middleware below, so
# CORS wraps it and even a 401 carries the CORS headers the browser needs to read it.
PUBLIC_PATHS = {"/health", "/auth/register", "/auth/login", "/docs", "/redoc", "/openapi.json"}


def bearer_token(request: Request) -> Optional[str]:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else None


@app.middleware("http")
async def require_login(request: Request, call_next):
    if request.method == "OPTIONS" or request.url.path in PUBLIC_PATHS:
        return await call_next(request)
    user = await run_in_threadpool(accounts.user_for_token, bearer_token(request))
    if user is None:
        return JSONResponse(status_code=401, content={"detail": "Please log in to continue."})
    request.state.user = user
    reset = attempt_store.ACTIVE_USER_ID.set(user["id"])
    try:
        return await call_next(request)
    finally:
        attempt_store.ACTIVE_USER_ID.reset(reset)

attempt_store.init_db()

ALLOWED_ORIGINS = cors_config.allowed_origins(os.environ.get("FRONTEND_URL"), os.environ.get("QUESTVERSE_ENV", "development"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,        # the configured frontend(s) (+ localhost unless production) -- never "*"
    allow_methods=["GET", "POST", "PUT", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    allow_credentials=False,              # logins use a bearer token, not cookies
)


class StartLevelRequest(BaseModel):
    student_id: Optional[str] = None
    resume_only: bool = False  # True when re-entering from a URL/refresh: resume, never start a new run


class CompleteLevelRequest(BaseModel):
    student_id: Optional[str] = None
    session_id: str


class HintRequest(BaseModel):
    session_id: str
    student_id: Optional[str] = None  # must match the student the session was started for
    question_id: str


class AnswerRequest(BaseModel):
    session_id: str
    student_id: Optional[str] = None  # must match the student the session was started for
    question_id: str
    answer: Optional[str] = None  # null on a timeout (see PlayScreen's onAnswer(null, true))
    # Legacy fields the client still sends. Tier, streaks and XP are now owned
    # by the server-side session, so these are accepted but ignored.
    tier: Optional[int] = None
    correct_streak: Optional[int] = None
    wrong_streak: Optional[int] = None
    total_xp: Optional[int] = None
    mode: Optional[str] = None


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

set_question_lookup(lambda qid: QUESTIONS_BY_ID.get(str(qid)))

# Mirrors frontend/src/courses.js -- the only topic grouping the banks have.
COURSE_TITLES = {
    "os": "Operating Systems",
    "dbms": "Database Systems",
    "dsa": "Data Structures & Algorithms",
    "lang": "Programming Languages",
    "custom": "Upload Your Own",
}

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
    return {"status": "ok", "service": "questverse"}


@app.get("/questions/all")
def get_all_questions(tier: Optional[int] = None):
    """Debug-only: full question data including answers, for validating content."""
    if tier is not None:
        return [q for q in ALL_QUESTIONS if q["tier"] == tier]
    return ALL_QUESTIONS


def session_view(session: QuestSession) -> dict:
    """Everything the client needs to render (or resume) the session. The
    current question is sent in its public form -- never its answer."""
    current = QUESTIONS_BY_ID.get(session.current_question_id) if session.current_question_id else None
    question = None
    if current is not None:
        question = public_question(current)
        if session.eliminated:
            question["eliminated_options"] = list(session.eliminated)
        question["fifty_fifty_available"] = fifty_fifty_available(session, current)
    return {
        "session_id": session.id,
        "courseId": session.course_id,
        "mode": session.mode,
        "quest_length": session.quest_length,
        "level_id": session.level_id,
        "solved_count": len(session.solved),
        "game_complete": session.complete,
        "tier": session.tier,
        "correct_streak": session.correct_streak,
        "wrong_streak": session.wrong_streak,
        "total_xp": session.total_xp,
        "level": level_from_xp(session.total_xp),
        "hint": session.hint,
        "attempts": session.attempts,
        "question": question,
    }


def pick_next_question(session: QuestSession):
    def pick(tier: int, solved_ids: set):
        if session.question_ids:  # level session: the next unsolved question of its fixed set
            return next((QUESTIONS_BY_ID[i] for i in session.question_ids if i not in solved_ids), None)
        # Never re-serve a solved question: prefer the target tier, then any
        # unsolved question of this course/mode. quest_length is capped at the
        # pool size when the session starts, so one always exists.
        key = (session.course_id, session.mode)
        pool = [q for q in QUESTIONS_BY_COURSE_MODE_TIER.get(key, {}).get(tier, []) if str(q["id"]) not in solved_ids]
        if not pool:
            pool = [q for q in QUESTIONS_BY_COURSE_MODE.get(key, []) if str(q["id"]) not in solved_ids]
        return random.choice(pool) if pool else None
    return pick


@app.get("/question/first")
def get_first_question(courseId: str = DEFAULT_COURSE, mode: str = DEFAULT_MODE, start_xp: int = 0, student_id: str = "anonymous"):
    """Starts a new quest session and unlocks its first question. The
    response is the public question plus session fields, so existing
    clients reading question fields keep working."""
    q = random_question_for(courseId, mode, tier=1)
    try:
        with LOCK:
            pool_size = len(QUESTIONS_BY_COURSE_MODE.get((q["courseId"], q["mode"]), []))
            session = create_session(q["courseId"], q["mode"], start_xp, attempt_store.clean_student_id(student_id), pool_size)
            session.serve(str(q["id"]))
            register_session(session)
            view = session_view(session)
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e
    return {**view["question"], **{k: v for k, v in view.items() if k not in ("question", "courseId", "mode")}}


def http_error(e: SessionError) -> HTTPException:
    return HTTPException(status_code=e.status_code, detail=e.detail)


@app.get("/session/{session_id}")
def get_session_state(session_id: str, student_id: str = "anonymous"):
    """Lets a refreshed page (or a restarted backend) resume exactly where
    the server says the student is -- current question, hint, attempt history."""
    try:
        with LOCK:
            return session_view(get_session(session_id, attempt_store.clean_student_id(student_id)))
    except SessionError as e:
        raise http_error(e) from e


@app.get("/dashboard/{session_id}")
def get_dashboard(session_id: str, student_id: str = "anonymous"):
    """Analysis for a quest, computed from the PERSISTED attempt log (not
    from anything the client reports). Only valid, graded submissions are in
    that log -- rejected requests never reach it."""
    sid = attempt_store.clean_student_id(student_id)
    try:
        with LOCK:
            session = get_session(session_id, sid)
            state = session.to_state()
    except SessionError as e:
        raise http_error(e) from e

    try:
        rows = attempt_store.fetch_session_attempts(session_id)
        history = attempt_store.fetch_student_attempts(sid) if sid != "anonymous" else rows
    except sqlite3.Error as e:
        raise HTTPException(status_code=503, detail="Could not read your attempt history. Please try again.") from e

    attempts = [attempt_view(r) for r in rows]
    mode_of = lambda qid: (QUESTIONS_BY_ID.get(str(qid)) or {}).get("mode")
    topics = topic_performance(history, mode_of)
    available = lambda cid, m: (cid, m) in QUESTIONS_BY_COURSE_MODE
    recs = recommend(topics, available, COURSE_TITLES, ["os", "dbms", "dsa", "lang"], session.course_id)

    by_q: dict = {}
    for a in attempts:
        by_q.setdefault(a["question_id"], []).append(a)
    most_retried = []
    for qid, qa in by_q.items():
        retries = len(qa) - 1 if any(x["correct"] for x in qa) else len(qa)
        q = QUESTIONS_BY_ID.get(qid)
        if retries > 0 and q:
            most_retried.append({"question_id": qid, "prompt": q["prompt"], "retries": retries, "mode": q["mode"]})
    most_retried.sort(key=lambda x: -x["retries"])

    return {
        "session_id": session_id,
        "topic": session.course_id,
        "topic_title": COURSE_TITLES.get(session.course_id, session.course_id),
        "completion": {
            "complete": session.complete,
            "solved": len(state["solved"]),
            "quest_length": session.quest_length,
            "total_xp": session.total_xp,
            "xp_earned": session.xp_earned,
        },
        "analysis": analyze_attempts(attempts) if session.complete else incomplete_result(),
        # Same analysis over every saved quest of this hero (quests stay separate inside it),
        # used when a single quest is too short to say anything.
        "analysis_overall": analyze_attempts([attempt_view(r) for r in history]) if sid != "anonymous" else None,
        "most_retried": most_retried[:3],
        "topics": topics,
        "recommendations": recs,
    }


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

    try:
        with LOCK:
            session = get_session(payload.session_id, attempt_store.clean_student_id(payload.student_id))
            if session.complete:
                raise SessionError(409, "This quest is already complete")
            # Progression gate: only the currently unlocked question can be
            # answered. Later questions (or already-solved ones) are rejected.
            if str(payload.question_id) != session.current_question_id:
                raise SessionError(409, "That question is not currently unlocked")

            # An option that has been removed can't be submitted (a timeout,
            # answer=None, is still fine). Rejected before grading, so it is
            # not recorded as an attempt.
            if payload.answer is not None and payload.answer in session.eliminated:
                raise SessionError(409, "That option has been eliminated and can't be selected")

            is_correct, evaluation = grade(question, payload.answer)
            outcome = apply_answer(
                session, question, payload.answer, is_correct, evaluation, pick_next_question(session)
            )

            if is_correct:
                shown_evaluation = evaluation
            else:
                # Never reveal the answer on a miss: only the hint and the
                # player's own answer go back.
                shown_evaluation = {
                    "your_answer": payload.answer,
                    "feedback": outcome["hint"],
                    "accuracy": evaluation.get("accuracy"),
                    "matched_concepts": evaluation.get("matched_concepts"),
                }

            view = session_view(session)
    except SessionError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail) from e

    return {
        "correct": is_correct,
        "evaluation": shown_evaluation,
        "question_solved": outcome["question_solved"],
        "xp_earned": outcome["xp_earned"],
        "total_xp": view["total_xp"],
        "tier": view["tier"],
        "correct_streak": view["correct_streak"],
        "wrong_streak": view["wrong_streak"],
        "level": view["level"],
        "level_up": outcome["level_up"],
        "hint": outcome["hint"],
        "solved_count": view["solved_count"],
        "quest_length": view["quest_length"],
        "level_id": view["level_id"],
        "game_complete": view["game_complete"],
        "attempts": view["attempts"],
        # On a miss this is the SAME question (with any crossed-out options);
        # on a solve it's the newly unlocked one; null when the quest is done.
        "next_question": view["question"],
    }


_HINTS_IN_FLIGHT: set = set()


@app.on_event("startup")
def warm_hint_model():
    """Load the hint model in the background so the first hint isn't a cold start, and start
    the loop that stores (and, when SMTP is configured, emails) each finished week's report."""
    import threading
    # Only when an Ollama server actually answers: without one (the normal case on a plain
    # deployment) startup does nothing and the game, health check and everything else carry on.
    if not os.environ.get("QUESTVERSE_NO_WARMUP") and ai_hint.ollama_client.is_running():
        threading.Thread(target=ai_hint.ollama_client.warm_up, daemon=True).start()
    if not os.environ.get("QUESTVERSE_NO_SCHEDULER"):
        weekly_report.start_scheduler()


@app.post("/hint/ai")
def ai_hint_for_question(payload: HintRequest):
    """Verbal hint from the local Ollama model for the session's current question.
    Read-only: never touches XP, attempts, options or progression. The question
    is looked up server-side so the correct answer can be screened out of the hint."""
    question = QUESTIONS_BY_ID.get(str(payload.question_id))
    if question is None:
        raise HTTPException(status_code=404, detail="Unknown question_id")
    try:
        with LOCK:
            session = get_session(payload.session_id, attempt_store.clean_student_id(payload.student_id))
            if session.complete or str(payload.question_id) != session.current_question_id:
                raise SessionError(409, "That question is not currently unlocked")
    except SessionError as e:
        raise http_error(e) from e
    key = (payload.session_id, str(payload.question_id))
    with LOCK:
        busy = key in _HINTS_IN_FLIGHT
        _HINTS_IN_FLIGHT.add(key)
    if busy:
        raise HTTPException(status_code=429, detail="Your companion is already thinking. Hold on a moment.")
    started = time.monotonic()
    hint = None
    try:
        hint = ai_hint.generate_hint(question)
    except ai_hint.HintError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e
    finally:
        with LOCK:
            _HINTS_IN_FLIGHT.discard(key)
        # Evidence for the guesswork analysis: the client timer is paused for this whole
        # wait, so the server logs its own measurement of it (hint received or not).
        try:
            attempt_store.record_hint_event(
                session_id=payload.session_id, student_id=session.student_id, question_id=str(payload.question_id),
                duration_ms=int((time.monotonic() - started) * 1000), ok=hint is not None,
            )
        except sqlite3.Error:
            log.exception("could not log hint event")
    return {"hint": hint, "question_id": str(payload.question_id)}


@app.post("/hint/fifty-fifty")
def use_fifty_fifty(payload: HintRequest):
    """Explicit 50/50 hint: removes exactly two wrong options from the current
    multiple-choice question, once per question. Never touches the correct
    answer, XP, attempts or progression."""
    question = QUESTIONS_BY_ID.get(str(payload.question_id))
    if question is None:
        raise HTTPException(status_code=404, detail="Unknown question_id")
    try:
        with LOCK:
            session = get_session(payload.session_id, attempt_store.clean_student_id(payload.student_id))
            if session.complete or str(payload.question_id) != session.current_question_id:
                raise SessionError(409, "That question is not currently unlocked")
            removed = apply_fifty_fifty(session, question)
            view = session_view(session)
    except SessionError as e:
        raise http_error(e) from e
    return {
        "removed_count": len(removed),
        "hint": view["hint"],
        "next_question": view["question"],
    }


# ===================================================================== accounts
class RegisterRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None


class LoginRequest(BaseModel):
    username: str
    password: str


class EmailRequest(BaseModel):
    email: Optional[str] = None


class AchievementsRequest(BaseModel):
    stats: dict
    unlocked: list = []


def _account_call(fn, *args):
    try:
        return fn(*args)
    except accounts.AccountError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from e
    except sqlite3.Error as e:
        log.exception("account database error")
        raise HTTPException(status_code=503, detail="Could not reach your account. Please try again.") from e


@app.post("/auth/register")
def auth_register(payload: RegisterRequest):
    user = _account_call(accounts.register, payload.username, payload.password, payload.email)
    token, _ = _account_call(accounts.login, payload.username, payload.password)
    return {"token": token, "user": user}


@app.post("/auth/login")
def auth_login(payload: LoginRequest):
    token, user = _account_call(accounts.login, payload.username, payload.password)
    return {"token": token, "user": user}


@app.post("/auth/logout")
def auth_logout(request: Request):
    _account_call(accounts.logout, bearer_token(request))
    return {"ok": True}


@app.get("/auth/me")
def auth_me(request: Request):
    return {"user": request.state.user}


@app.put("/me/email")
def update_email(payload: EmailRequest, request: Request):
    email = _account_call(accounts.set_email, request.state.user["id"], payload.email)
    return {"email": email, "email_delivery": weekly_report.smtp_configured()}


@app.get("/me/achievements")
def get_my_achievements(request: Request):
    return _account_call(accounts.get_achievements, request.state.user["id"])


@app.put("/me/achievements")
def put_my_achievements(payload: AchievementsRequest, request: Request):
    return _account_call(accounts.save_achievements, request.state.user["id"], payload.stats, payload.unlocked)


@app.get("/me/weekly-report")
def my_weekly_report(request: Request, week: Optional[str] = None):
    """The weekly progress report: the current week by default, or the week starting at `week`
    (an ISO date from /me/weekly-report/weeks)."""
    from datetime import datetime, timezone
    user = request.state.user
    try:
        start = datetime.fromisoformat(week) if week else None
        if start is not None and start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Unknown week") from e
    try:
        report = weekly_report.get_report(user["id"], start)
        weeks = weekly_report.list_weeks(user["id"])
    except sqlite3.Error as e:
        log.exception("weekly report failed")
        raise HTTPException(status_code=503, detail="Could not build your report. Please try again.") from e
    return {"report": report, "weeks": weeks, "email": user["email"], "email_delivery": weekly_report.smtp_configured()}


# ===================================================================== levels
# World -> Stage -> Level -> Quiz. The backend owns which levels exist, which are
# open for a student, and who gets XP; the client only displays what it is told.

# Levels are built from the built-in banks (uploaded "custom" quizzes stay free-play).
CATALOG: dict = {}


def rebuild_catalog() -> None:
    """(Re)builds the stage/level catalog from the question banks, in place so every
    reference to CATALOG sees the change (used again after a level is topped up)."""
    CATALOG.clear()
    CATALOG.update(build_catalog([q for q in ALL_QUESTIONS if q["courseId"] != "custom"]))


# Questions generated earlier to top a level up are part of the bank from the start.
register_questions([q for q in level_fill.load_generated() if str(q["id"]) not in QUESTIONS_BY_ID])
rebuild_catalog()


def ensure_level_ready(level_id: str) -> dict:
    """The level, guaranteed to have MIN_LEVEL_QUESTIONS unique questions -- generating the
    missing ones with the local model if needed. Raises 503 (and starts nothing) otherwise."""
    level = CATALOG["levels"][level_id]
    if level["meets_minimum"]:
        return level
    with level_fill.FILL_LOCK:
        level = CATALOG["levels"][level_id]          # another request may have filled it while we waited
        if not level["meets_minimum"]:
            try:
                fresh = level_fill.top_up(level, ALL_QUESTIONS)
            except level_fill.LevelFillError as e:
                raise HTTPException(status_code=503, detail=e.message) from e
            with LOCK:
                register_questions(fresh)
                rebuild_catalog()
            level = CATALOG["levels"][level_id]
    if not level["meets_minimum"]:
        raise HTTPException(status_code=503, detail="This level doesn't have enough questions yet. Please try again later.")
    return level


def require_student(raw: Optional[str]) -> str:
    student_id = attempt_store.clean_student_id(raw)
    if student_id == "anonymous":
        raise HTTPException(status_code=400, detail="A valid student_id is required")
    return student_id


def student_progress_state(student_id: str):
    """(completion rows, open level ids, level states) read from the database."""
    try:
        completions = attempt_store.fetch_completions(student_id)
        open_ids = attempt_store.open_level_ids(student_id)
    except sqlite3.Error as e:
        raise HTTPException(status_code=503, detail="Could not read your progress. Please try again.") from e
    states = level_states(CATALOG, {c["level_id"] for c in completions}, open_ids)
    return completions, open_ids, states


def stage_name(stage_id: str) -> str:
    return next((st["name"] for st in CATALOG["stages"] if st["id"] == stage_id), stage_id)


@app.get("/stages")
def get_stages():
    """The world's structure -- stages and levels -- with no per-student state."""
    return {
        "world": CATALOG["world"],
        "stages": [
            {"id": st["id"], "name": st["name"], "description": st["description"], "theme": st["theme"],
             "levels": [{k: v for k, v in public_level(lv, "", {}).items() if k not in ("state", "completions",
                                                                                      "best_first_try_pct", "stars")}
                        for lv in st["levels"]]}
            for st in CATALOG["stages"]
        ],
    }


@app.get("/progress/me")
def get_progress(student_id: str = ""):
    """The student's progression: every stage and level with its unlock state,
    their XP, and where to continue. This is the single source of truth the
    map renders."""
    sid = require_student(student_id)
    completions, open_ids, _ = student_progress_state(sid)
    progress = compute_progress(CATALOG, completions, open_ids)
    try:
        total_xp = attempt_store.student_xp_total(sid)
    except sqlite3.Error as e:
        raise HTTPException(status_code=503, detail="Could not read your progress. Please try again.") from e
    progress.update({"student_id": sid, "total_xp": total_xp, "level": level_from_xp(total_xp)})
    return progress


@app.post("/levels/{level_id}/start")
def start_level(level_id: str, payload: StartLevelRequest):
    """Opens a level's quiz. Refused (403) while the level is locked. If the
    student already has an unfinished run of this level it is RESUMED, so
    re-entering never resets their attempts."""
    level = CATALOG["levels"].get(level_id)
    if level is None:
        raise HTTPException(status_code=404, detail="Unknown level")
    sid = require_student(payload.student_id)
    _, _, early_states = student_progress_state(sid)
    if early_states[level_id] == "locked":
        raise HTTPException(status_code=403, detail="This level is locked. Complete the previous level first.")
    if not payload.resume_only:
        # Slow (may call the local model), so it runs before taking the global lock. A level
        # that cannot reach the minimum refuses to start rather than starting short.
        level = ensure_level_ready(level_id)
    try:
        with LOCK:
            _, _, states = student_progress_state(sid)
            if states[level_id] == "locked":
                raise HTTPException(status_code=403, detail="This level is locked. Complete the previous level first.")

            try:
                existing = attempt_store.find_open_level_session(sid, level_id)
            except sqlite3.Error as e:
                raise HTTPException(status_code=503, detail="Could not read your progress. Please try again.") from e

            if existing is not None:
                session = get_session(existing["id"], sid)
            elif payload.resume_only:
                raise HTTPException(status_code=409, detail="No unfinished run of this level to resume")
            else:
                formats = level["formats"]
                session = create_session(
                    level["course_id"], formats[0] if len(formats) == 1 else "mixed",
                    attempt_store.student_xp_total(sid), sid, level["question_count"],
                    level_id=level_id, question_ids=level["question_ids"], tier=level["start_tier"],
                )
                session.serve(level["question_ids"][0])
                register_session(session)
            view = session_view(session)
    except SessionError as e:
        raise http_error(e) from e
    return {
        **view["question"], **{k: v for k, v in view.items() if k not in ("question", "courseId", "mode")},
        "question": view["question"],
        "level_info": public_level(level, states[level_id], {}),
        "resumed": existing is not None,
    }


def build_level_results(sid: str, level_id: str, session_id: Optional[str]) -> dict:
    level = CATALOG["levels"].get(level_id)
    if level is None:
        raise HTTPException(status_code=404, detail="Unknown level")
    completions, open_ids, states_after = student_progress_state(sid)
    mine = [c for c in completions if c["level_id"] == level_id]
    if session_id:
        row = next((c for c in mine if c["session_id"] == session_id), None)
    else:
        row = mine[-1] if mine else None
    if row is None:
        raise HTTPException(status_code=404, detail="No completed run of this level yet")

    is_first = mine[0]["session_id"] == row["session_id"]
    completed_after = {c["level_id"] for c in completions}
    states_before = level_states(CATALOG, completed_after - ({level_id} if is_first else set()), open_ids)

    newly_unlocked = []
    if is_first:
        for lv in CATALOG["ordered_levels"]:
            if states_before[lv["id"]] == "locked" and states_after[lv["id"]] != "locked":
                newly_unlocked.append({"level_id": lv["id"], "level_name": lv["name"], "stage_id": lv["stage_id"],
                                       "stage_name": stage_name(lv["stage_id"]), "new_stage": lv["order"] == 0})

    next_id = next_level_id(CATALOG, states_after)
    next_level = None
    if next_id:
        nl = CATALOG["levels"][next_id]
        next_level = {"id": nl["id"], "name": nl["name"], "stage_id": nl["stage_id"],
                      "stage_name": stage_name(nl["stage_id"]), "state": states_after[next_id]}

    total_xp = attempt_store.student_xp_total(sid)
    earned = attempt_store.session_xp(row["session_id"])
    questions = row["questions"]
    return {
        "level": {"id": level["id"], "name": level["name"], "stage_id": level["stage_id"],
                  "stage_name": stage_name(level["stage_id"]), "question_count": level["question_count"]},
        "session_id": row["session_id"],
        "completed_at": row["completed_at"],
        "first_completion": is_first,
        "first_try_pct": row["first_try_pct"],
        "stars": stars_for(row["first_try_pct"]),
        "questions": questions,
        "attempts": row["attempts"],
        "retries": max(0, row["attempts"] - questions),
        "xp": {
            "earned_this_run": earned,
            "total": total_xp,
            "level": level_from_xp(total_xp),
            # Replays earn nothing for questions whose XP was already granted.
            "note": None if earned > 0 else "XP for this level was already earned on an earlier run, so this replay adds none.",
        },
        "newly_unlocked": newly_unlocked,
        "next_level": next_level,
        "all_completed": next_id is None,
    }


@app.post("/levels/{level_id}/complete")
def complete_level(level_id: str, payload: CompleteLevelRequest):
    """Confirms a finished run and returns its results. Completion is decided by
    the server from the recorded attempts, never by the client; calling this
    more than once is harmless (one completion per session, XP is a ledger)."""
    if level_id not in CATALOG["levels"]:
        raise HTTPException(status_code=404, detail="Unknown level")
    sid = require_student(payload.student_id)
    try:
        with LOCK:
            session = get_session(payload.session_id, sid)
            if session.level_id != level_id:
                raise SessionError(409, "That session belongs to a different level")
            if not session.complete:
                raise SessionError(409, f"Level not complete yet: {len(session.solved)} of {session.quest_length} questions solved")
            rows = [a for a in attempt_store.fetch_session_attempts(session.id)]
            firsts: dict = {}
            for r in rows:
                firsts.setdefault(r["question_id"], bool(r["is_correct"]))
            attempt_store.ensure_completion({
                "session_id": session.id, "student_id": sid, "level_id": level_id,
                "questions": session.quest_length, "attempts": len(rows),
                "first_try_pct": round(100 * sum(1 for ok in firsts.values() if ok) / session.quest_length, 1),
            })
            return build_level_results(sid, level_id, session.id)
    except SessionError as e:
        raise http_error(e) from e
    except sqlite3.Error as e:
        raise HTTPException(status_code=503, detail="Could not record the completion. Please try again.") from e


@app.get("/levels/{level_id}/results")
def get_level_results(level_id: str, student_id: str = "", session_id: Optional[str] = None):
    """Results of a completed run (the given session, or the latest)."""
    sid = require_student(student_id)
    try:
        return build_level_results(sid, level_id, session_id)
    except sqlite3.Error as e:
        raise HTTPException(status_code=503, detail="Could not read the results. Please try again.") from e


if __name__ == "__main__":
    # `python main.py` for hosts that just run a command. Render and Docker use the uvicorn command instead.
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8010")))
