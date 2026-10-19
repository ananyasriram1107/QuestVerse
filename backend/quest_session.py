"""
Server-side quest sessions.

The original /answer endpoint trusted the client for tier, streaks and total
XP and always served a "next" question, so progression lived entirely in
React state. A QuestSession moves that authority to the backend: it records
which question is currently unlocked, which are solved, every attempt, and
the XP actually awarded, so a student cannot skip ahead, replay a solved
question for more XP, or inflate XP by editing the request payload.

Sessions are cached in memory for speed but every change is written to SQLite
(see attempt_store.py) in the same transaction as the attempt it came from.
A reopened tab -- or a restarted backend -- reloads the session from the
database, rebuilding the attempt history from the persisted attempt rows.
"""

import logging
import secrets
import sqlite3
import threading
import time
from typing import Callable, Optional

import attempt_store
from engine import QUEST_LENGTH, level_from_xp, next_state
from levels_config import MIN_LEVEL_QUESTIONS

log = logging.getLogger(__name__)

SESSION_TTL_SECONDS = 6 * 60 * 60   # idle in-memory sessions are dropped (they reload from the DB on demand)
MAX_SESSIONS = 5000
MAX_START_XP = 1_000_000

# One lock for every session mutation: sync FastAPI endpoints run in a thread
# pool, and two concurrent submissions of the same correct answer must not
# both be awarded.
LOCK = threading.RLock()
SESSIONS: dict = {}

# main.py registers how to look a question up by id (used to rebuild attempt
# metadata -- format, option count, tier -- from persisted rows).
_question_lookup: Callable[[str], Optional[dict]] = lambda qid: None


def set_question_lookup(fn: Callable[[str], Optional[dict]]) -> None:
    global _question_lookup
    _question_lookup = fn


class SessionError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def attempt_view(row: dict) -> dict:
    """A persisted attempt row in the shape the analytics and UI consume."""
    q = _question_lookup(row["question_id"])
    return {
        "question_id": row["question_id"],
        "correct": bool(row["is_correct"]),
        "tier": q["tier"] if q else 1,
        "attempt_no": row["attempt_no"],
        "time_taken_ms": row["response_time_ms"],
        "mode": q["mode"] if q else None,
        # Options that were still selectable at that attempt (a 50/50 lowers
        # this), falling back to the full option count for older rows.
        "n_options": (row.get("options_shown") or len(q["options"])) if q and q["mode"] == "mcq" else None,
        # Evidence for guesswork detection: which quest/topic, whether an AI hint had
        # been received, and whether the recorded time can be trusted.
        "session_id": row.get("session_id"),
        "topic": row.get("topic"),
        "hint_used": bool(row.get("hint_used", 0)),
        "timing_valid": bool(row.get("timing_valid", 1)),
    }


class QuestSession:
    def __init__(self, course_id: str, mode: str, start_xp: int, student_id: str = "anonymous",
                 quest_length: int = QUEST_LENGTH, level_id: Optional[str] = None,
                 question_ids: Optional[list] = None, tier: int = 1):
        # Level sessions: a fixed, ordered question set whose size IS the length.
        self.level_id = level_id
        self.question_ids = list(question_ids) if question_ids else None
        if self.question_ids:
            quest_length = len(self.question_ids)
        self.quest_length = max(1, min(QUEST_LENGTH, int(quest_length))) if not self.question_ids else quest_length
        self.student_id = student_id
        self.id = secrets.token_urlsafe(24)
        self.course_id = course_id
        self.mode = mode
        self.start_xp = max(0, min(MAX_START_XP, int(start_xp)))
        self.xp_earned = 0
        self.tier = max(1, min(3, int(tier)))
        self.correct_streak = 0
        self.wrong_streak = 0
        self.current_question_id: Optional[str] = None
        self.solved: list = []
        self.attempts: list = []
        self.attempts_on_current = 0
        self.eliminated: list = []   # MCQ options crossed out for the current question
        self.hint: Optional[str] = None
        self.fifty_fifty_used = False   # explicit 50/50 hint, once per question
        self.served_at = time.time()
        self.timing_valid = True   # False after a reload mid-question: the timer restarted, so the time is unreliable
        self.touched_at = time.time()

    @property
    def total_xp(self) -> int:
        return self.start_xp + self.xp_earned

    @property
    def complete(self) -> bool:
        return len(self.solved) >= self.quest_length

    def serve(self, question_id: Optional[str]) -> None:
        """Unlocks a question: resets the per-question attempt state."""
        self.current_question_id = question_id
        self.attempts_on_current = 0
        self.eliminated = []
        self.hint = None
        self.fifty_fifty_used = False
        self.served_at = time.time()
        self.timing_valid = True

    def to_state(self) -> dict:
        return {
            "id": self.id, "student_id": self.student_id, "quest_length": self.quest_length, "topic": self.course_id, "mode": self.mode,
            "start_xp": self.start_xp, "xp_earned": self.xp_earned, "tier": self.tier,
            "correct_streak": self.correct_streak, "wrong_streak": self.wrong_streak,
            "current_question_id": self.current_question_id, "solved": list(self.solved),
            "attempts_on_current": self.attempts_on_current, "eliminated": list(self.eliminated),
            "hint": self.hint, "fifty_fifty_used": bool(self.fifty_fifty_used),
            "level_id": self.level_id, "question_ids": list(self.question_ids) if self.question_ids else None,
        }

    def restore(self, state: dict, served_at: float) -> None:
        """Puts the mutable progression fields back (used to undo a change
        whose database write failed)."""
        self.xp_earned = state["xp_earned"]
        self.tier = state["tier"]
        self.correct_streak = state["correct_streak"]
        self.wrong_streak = state["wrong_streak"]
        self.current_question_id = state["current_question_id"]
        self.solved = list(state["solved"])
        self.attempts_on_current = state["attempts_on_current"]
        self.eliminated = list(state["eliminated"])
        self.hint = state["hint"]
        self.fifty_fifty_used = bool(state.get("fifty_fifty_used", False))
        self.served_at = served_at

    @classmethod
    def from_state(cls, state: dict) -> "QuestSession":
        s = cls(state["topic"], state["mode"], state["start_xp"], state["student_id"], state["quest_length"],
                level_id=state.get("level_id"), question_ids=state.get("question_ids"))
        s.id = state["id"]
        s.restore(state, time.time())  # response time restarts from the reload...
        s.timing_valid = False         # ...so the next answer's time is not trusted by the analysis
        s.attempts = [attempt_view(r) for r in attempt_store.fetch_session_attempts(s.id)]
        return s


def _purge_expired() -> None:
    now = time.time()
    for sid in [s for s, sess in SESSIONS.items() if now - sess.touched_at > SESSION_TTL_SECONDS]:
        del SESSIONS[sid]
    if len(SESSIONS) > MAX_SESSIONS:
        oldest = sorted(SESSIONS.values(), key=lambda s: s.touched_at)[: len(SESSIONS) - MAX_SESSIONS]
        for sess in oldest:
            SESSIONS.pop(sess.id, None)


def create_session(course_id: str, mode: str, start_xp: int, student_id: str = "anonymous", quest_length: int = QUEST_LENGTH,
                   level_id: Optional[str] = None, question_ids: Optional[list] = None, tier: int = 1) -> QuestSession:
    if level_id is not None:
        # Server-side guarantee, independent of the client: a level quiz never starts short or with repeats.
        ids = [str(i) for i in (question_ids or [])]
        if len(set(ids)) != len(ids) or len(ids) < MIN_LEVEL_QUESTIONS:
            raise SessionError(503, f"This level needs at least {MIN_LEVEL_QUESTIONS} different questions and is not ready yet.")
    with LOCK:
        _purge_expired()
        return QuestSession(course_id, mode, start_xp, student_id, quest_length, level_id, question_ids, tier)


def register_session(session: QuestSession) -> None:
    """Caches and persists a freshly created session (after its first
    question has been served). Raises SessionError(503) if it can't be saved."""
    with LOCK:
        try:
            attempt_store.save_session(session.to_state())
        except sqlite3.Error as e:
            log.exception("failed to persist new session")
            raise SessionError(503, "Could not start the quest. Please try again.") from e
        SESSIONS[session.id] = session


def get_session(session_id: str, student_id: str) -> QuestSession:
    """Looks a session up (memory first, then the database) and verifies it
    belongs to `student_id`. 404 if unknown, 403 if it is someone else's."""
    with LOCK:
        session = SESSIONS.get(session_id)
        if session is None:
            try:
                state = attempt_store.load_session(session_id)
            except sqlite3.Error as e:
                log.exception("failed to load session")
                raise SessionError(503, "Could not load the quest. Please try again.") from e
            if state is None:
                raise SessionError(404, "Unknown or expired session")
            session = QuestSession.from_state(state)
            SESSIONS[session.id] = session
        if session.student_id != student_id:
            raise SessionError(403, "This session belongs to a different student")
        session.touched_at = time.time()
        return session


def incorrect_options(question: dict) -> list:
    """The question's wrong options, decided from its real correct_answer
    (never from option position)."""
    right = str(question["correct_answer"]).strip().lower()
    return [o for o in question["options"] if str(o).strip().lower() != right]


def fifty_fifty_available(session: QuestSession, question: dict) -> bool:
    """50/50 removes exactly two wrong options and must leave the correct
    answer plus at least one wrong one, so it needs three or more wrong
    options still standing. One use per question."""
    if question["mode"] != "mcq" or session.fifty_fifty_used:
        return False
    return len([o for o in incorrect_options(question) if o not in session.eliminated]) >= 3


def apply_fifty_fifty(session: QuestSession, question: dict) -> list:
    """Explicit, student-requested hint: eliminates exactly two incorrect
    options (never the correct one) and persists the new session state.
    Caller holds LOCK and has verified ownership and the current question."""
    if question["mode"] != "mcq":
        raise SessionError(409, "50/50 is only available on multiple-choice questions")
    if session.fifty_fifty_used:
        raise SessionError(409, "You already used 50/50 on this question")
    if not fifty_fifty_available(session, question):
        raise SessionError(409, "50/50 isn't available now: too few wrong options are left to remove two safely")

    before = session.to_state()
    candidates = [o for o in incorrect_options(question) if o not in session.eliminated]
    removed = secrets.SystemRandom().sample(candidates, 2)
    session.eliminated.extend(removed)
    session.fifty_fifty_used = True
    session.hint = "50/50 used: two wrong options were removed. The correct answer is one of the options still showing."
    try:
        attempt_store.save_session(session.to_state())
    except sqlite3.Error as e:
        session.restore(before, session.served_at)
        log.exception("failed to persist 50/50 hint")
        raise SessionError(503, "Could not apply the hint. Please try again.") from e
    return removed


def build_hint(question: dict, attempt_no: int, answer: Optional[str], evaluation: dict, struck: Optional[str]) -> str:
    """Feedback for a miss. Never states the correct answer (or the model
    answer) and only describes what actually happened: at most the student's
    own wrong pick is greyed out.

    MCQ: the question's own conceptual hint if it has one. Short answer:
    credits the ideas already covered and names the next uncovered
    concept(s) to think about.
    """
    if question["mode"] == "mcq":
        pieces = []
        if answer is None:
            pieces.append("Time ran out.")
        if question.get("hint"):
            pieces.append(str(question["hint"]))
        else:
            pieces.append("Reason from the core definition behind the question rather than what merely sounds familiar.")
        if struck is not None:
            pieces.append("The option you chose is greyed out because it isn't correct.")
        return " ".join(pieces)

    matched = evaluation.get("matched_concepts") or []
    missing = evaluation.get("missing_concepts") or []
    if not (answer or "").strip():
        return "You didn't write anything yet -- try describing the main idea in your own words."
    if missing:
        nudge = ", ".join(missing[: max(1, attempt_no)])
        prefix = f"You've covered {', '.join(matched)}. " if matched else ""
        return f"{prefix}Not quite there yet -- think about: {nudge}."
    return "Not quite -- re-read the question and be more specific about the exact term or value it asks for."


def apply_answer(session: QuestSession, question: dict, answer: Optional[str], is_correct: bool, evaluation: dict, pick_next) -> dict:
    """Applies one validated submission to the session, persists the attempt
    and the new session state atomically, and returns the progression part of
    the response. `pick_next(tier, solved_ids)` returns the next question dict.

    Caller holds LOCK and has already checked ownership, that the session is
    open, and that `question` is the session's current question. If the
    database write fails the in-memory change is undone and SessionError is
    raised, so nothing is awarded or unlocked without being recorded.
    """
    before = session.to_state()
    before_served_at = session.served_at
    # How many options were still selectable when this answer was given (a
    # 50/50 lowers it); the guessing analysis uses it for the chance baseline.
    options_shown = (len(question["options"]) - len(session.eliminated)) if question["mode"] == "mcq" else None

    # Response time = server-measured ms from when this question (or the
    # retry after a miss) was shown until this submission arrived.
    # AI hint generation pauses the player's timer, so that wait is excluded.
    try:
        hint_wait_ms, hint_used = attempt_store.pending_hint_info(session.id, str(question["id"]))
    except sqlite3.Error:
        log.exception("could not read hint events; recording the attempt without them")
        hint_wait_ms, hint_used = 0, False
    timing_valid = session.timing_valid
    time_taken_ms = max(0, int((time.time() - session.served_at) * 1000) - hint_wait_ms)
    session.served_at = time.time()
    session.timing_valid = True  # a retry starts a fresh, trustworthy clock
    session.attempts_on_current += 1
    attempt_no = session.attempts_on_current

    old_level = level_from_xp(session.total_xp)
    state = next_state(session.tier, session.correct_streak, session.wrong_streak, is_correct)
    session.tier = state["tier"]
    session.correct_streak = state["correct_streak"]
    session.wrong_streak = state["wrong_streak"]

    xp = 0
    if not is_correct:
        struck = None
        if question["mode"] == "mcq":
            # Exactly one option is greyed out: the wrong one the student just
            # picked (resubmitting it would be pointless). Nothing else is
            # removed automatically -- further elimination only comes from an
            # explicit 50/50 request.
            struck = next((o for o in incorrect_options(question)
                           if answer is not None and str(o) == str(answer) and o not in session.eliminated), None)
            if struck is not None:
                session.eliminated.append(struck)
        session.hint = build_hint(question, attempt_no, answer, evaluation, struck)
    else:
        # Award exactly once per question, then unlock the next.
        qid = str(question["id"])
        if qid not in session.solved:
            session.solved.append(qid)
            xp = state["xp_earned"]
            if session.level_id is not None and attempt_store.xp_already_awarded(session.student_id, session.level_id, qid):
                xp = 0  # already earned in an earlier run of this level: replays and restarts earn nothing more
            session.xp_earned += xp
        if session.complete:
            session.serve(None)
        else:
            nxt = pick_next(session.tier, set(session.solved))
            session.serve(str(nxt["id"]) if nxt else None)

    attempt_entry = {
        "question_id": str(question["id"]),
        "correct": is_correct,
        "tier": question["tier"],
        "attempt_no": attempt_no,
        "time_taken_ms": time_taken_ms,
        "mode": question["mode"],
        "n_options": options_shown,
        "session_id": session.id,
        "topic": session.course_id,
        "hint_used": hint_used,
        "timing_valid": timing_valid,
    }

    # Level bookkeeping rides in the same transaction as the attempt itself.
    xp_award = completion = None
    if session.level_id is not None and is_correct:
        if xp > 0:
            xp_award = {"student_id": session.student_id, "level_id": session.level_id,
                        "question_id": str(question["id"]), "xp": xp, "session_id": session.id}
        if session.complete:
            history = session.attempts + [attempt_entry]
            firsts = {}
            for a in history:
                firsts.setdefault(a["question_id"], a["correct"])
            completion = {
                "session_id": session.id, "student_id": session.student_id, "level_id": session.level_id,
                "questions": session.quest_length, "attempts": len(history),
                "first_try_pct": round(100 * sum(1 for ok in firsts.values() if ok) / session.quest_length, 1),
            }

    try:
        attempt_store.record_attempt(
            student_id=session.student_id,
            session_id=session.id,
            question_id=str(question["id"]),
            topic=session.course_id,
            selected_answer=answer,
            is_correct=is_correct,
            attempt_no=attempt_no,
            response_time_ms=time_taken_ms,
            options_shown=options_shown,
            hint_used=hint_used,
            hint_wait_ms=hint_wait_ms,
            timing_valid=timing_valid,
            session_state=session.to_state(),
            xp_award=xp_award,
            completion=completion,
        )
    except sqlite3.IntegrityError as e:
        session.restore(before, before_served_at)
        session.timing_valid = timing_valid
        log.warning("duplicate attempt rejected for session %s question %s", session.id, question["id"])
        raise SessionError(409, "That attempt was already recorded") from e
    except sqlite3.Error as e:
        session.restore(before, before_served_at)
        session.timing_valid = timing_valid
        log.exception("failed to persist attempt")
        raise SessionError(503, "Could not save your answer. Please try again.") from e

    session.attempts.append(attempt_entry)

    return {
        "question_solved": is_correct,
        "xp_earned": xp,
        "level_up": level_from_xp(session.total_xp) > old_level,
        "game_complete": session.complete,
        "hint": None if is_correct else session.hint,
    }
