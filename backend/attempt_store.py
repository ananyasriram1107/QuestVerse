"""
Persistent attempt log and session state (SQLite, stdlib only).

The project had no database before this: questions are in-memory and player
progress lives in the browser. This adds the minimum needed to keep an
append-only record of every answer submission (`attempts`) plus the state of
each quest (`sessions`) so a backend restart or a reopened tab resumes where
the student left off instead of silently resetting their attempts.

Everything stored is decided server-side: correctness comes from grading, the
timestamp from the server clock, and response time from the server's own
measurement (ms from the moment the question -- or the retry after a miss --
was presented to the moment the submission was received). Nothing about
correctness or XP is ever read from the client.

student_id is whatever the client claims (the app has no login yet; the
frontend sends the chosen character's id), so treat it as a label, not proof
of identity.

Schema versioning: `PRAGMA user_version` records which migration last ran.
init_db() applies any missing ones in order, inside a transaction each, and is
safe to call on every start (and on a database created by an earlier version
of this file, whose user_version is still 0).
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Optional

DB_PATH = os.environ.get(
    "QUESTVERSE_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "questverse.db")
)
MAX_ANSWER_CHARS = 2000
_STUDENT_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")

# Ordered migrations: index + 1 == the user_version it brings the DB to.
# Statements are idempotent (IF NOT EXISTS) so adopting a v0 database that
# already has the attempts table is harmless.
MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS attempts (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id       TEXT    NOT NULL,
        session_id       TEXT    NOT NULL,
        question_id      TEXT    NOT NULL,
        topic            TEXT    NOT NULL,
        selected_answer  TEXT,
        is_correct       INTEGER NOT NULL CHECK (is_correct IN (0, 1)),
        attempt_no       INTEGER NOT NULL CHECK (attempt_no >= 1),
        response_time_ms INTEGER NOT NULL CHECK (response_time_ms >= 0),
        submitted_at     TEXT    NOT NULL,
        -- one row per (session, question, attempt number): a replayed or
        -- racing request cannot insert the same attempt twice
        UNIQUE (session_id, question_id, attempt_no)
    );
    CREATE INDEX IF NOT EXISTS idx_attempts_student ON attempts (student_id, submitted_at);
    CREATE INDEX IF NOT EXISTS idx_attempts_session ON attempts (session_id);
    """,
    """
    CREATE TABLE IF NOT EXISTS sessions (
        id                  TEXT PRIMARY KEY,
        student_id          TEXT    NOT NULL,
        topic               TEXT    NOT NULL,
        mode                TEXT    NOT NULL,
        quest_length        INTEGER NOT NULL,
        start_xp            INTEGER NOT NULL,
        xp_earned           INTEGER NOT NULL,
        tier                INTEGER NOT NULL,
        correct_streak      INTEGER NOT NULL,
        wrong_streak        INTEGER NOT NULL,
        current_question_id TEXT,
        solved_json         TEXT    NOT NULL,
        attempts_on_current INTEGER NOT NULL,
        eliminated_json     TEXT    NOT NULL,
        hint                TEXT,
        created_at          TEXT    NOT NULL,
        updated_at          TEXT    NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sessions_student ON sessions (student_id);
    """,
    # v3: explicit 50/50 hint. `fifty_fifty_used` limits it to once per
    # question; `options_shown` records how many answer options were still
    # selectable when an attempt was made, so the chance baseline in
    # guess_analysis.py stays honest when a 50/50 was in play.
    """
    ALTER TABLE sessions ADD COLUMN fifty_fifty_used INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE attempts ADD COLUMN options_shown INTEGER;
    """,
    # v4: levels. A level session carries its level id and its fixed question
    # list. `xp_awards` is the XP ledger: one row per (student, level, question)
    # -- the primary key is what stops a question's XP being granted twice.
    # `level_completions` holds one row per finished level session (primary key
    # = session id, so recording a completion twice is a no-op).
    """
    ALTER TABLE sessions ADD COLUMN level_id TEXT;
    ALTER TABLE sessions ADD COLUMN question_ids_json TEXT;
    CREATE INDEX IF NOT EXISTS idx_sessions_level ON sessions (student_id, level_id);
    CREATE TABLE IF NOT EXISTS xp_awards (
        student_id  TEXT    NOT NULL,
        level_id    TEXT    NOT NULL,
        question_id TEXT    NOT NULL,
        xp          INTEGER NOT NULL CHECK (xp >= 0),
        session_id  TEXT    NOT NULL,
        awarded_at  TEXT    NOT NULL,
        PRIMARY KEY (student_id, level_id, question_id)
    );
    CREATE TABLE IF NOT EXISTS level_completions (
        session_id   TEXT PRIMARY KEY,
        student_id   TEXT    NOT NULL,
        level_id     TEXT    NOT NULL,
        completed_at TEXT    NOT NULL,
        questions    INTEGER NOT NULL,
        attempts     INTEGER NOT NULL,
        first_try_pct REAL   NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_completions_student ON level_completions (student_id, level_id);
    """,
]


def clean_student_id(raw: Optional[str]) -> str:
    return raw if raw and _STUDENT_ID_RE.match(raw) else "anonymous"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> int:
    """Applies pending migrations; returns the resulting schema version."""
    conn = _connect()
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for target, script in enumerate(MIGRATIONS, start=1):
            if target <= version:
                continue
            with conn:  # one transaction per migration; rolls back on error
                conn.executescript("BEGIN;" + script + f"PRAGMA user_version = {target};COMMIT;")
        return conn.execute("PRAGMA user_version").fetchone()[0]
    finally:
        conn.close()


def _save_session(conn: sqlite3.Connection, state: dict) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO sessions (id, student_id, topic, mode, quest_length, start_xp, xp_earned, tier, correct_streak, "
        "wrong_streak, current_question_id, solved_json, attempts_on_current, eliminated_json, hint, "
        "fifty_fifty_used, level_id, question_ids_json, created_at, updated_at) VALUES (:id,:student_id,:topic,:mode,"
        ":quest_length,:start_xp,:xp_earned,:tier,"
        ":correct_streak,:wrong_streak,:current_question_id,:solved_json,:attempts_on_current,"
        ":eliminated_json,:hint,:fifty_fifty_used,:level_id,:question_ids_json,:now,:now) "
        "ON CONFLICT(id) DO UPDATE SET xp_earned=excluded.xp_earned, tier=excluded.tier, "
        "correct_streak=excluded.correct_streak, wrong_streak=excluded.wrong_streak, "
        "current_question_id=excluded.current_question_id, solved_json=excluded.solved_json, "
        "attempts_on_current=excluded.attempts_on_current, eliminated_json=excluded.eliminated_json, "
        "hint=excluded.hint, fifty_fifty_used=excluded.fifty_fifty_used, updated_at=excluded.updated_at",
        {**state, "solved_json": json.dumps(state["solved"]),
         "eliminated_json": json.dumps(state["eliminated"]),
         "level_id": state.get("level_id"),
         "question_ids_json": json.dumps(state["question_ids"]) if state.get("question_ids") else None,
         "now": now},
    )


def save_session(state: dict) -> None:
    conn = _connect()
    try:
        with conn:
            _save_session(conn, state)
    finally:
        conn.close()


def load_session(session_id: str) -> Optional[dict]:
    conn = _connect()
    try:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    state = dict(row)
    state["solved"] = json.loads(state.pop("solved_json"))
    state["eliminated"] = json.loads(state.pop("eliminated_json"))
    ids = state.pop("question_ids_json", None)
    state["question_ids"] = json.loads(ids) if ids else None
    return state


def find_open_level_session(student_id: str, level_id: str) -> Optional[dict]:
    """The student's unfinished session for a level (most recent first), so
    starting a level again resumes it instead of resetting their attempts."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT id, quest_length, solved_json FROM sessions WHERE student_id = ? AND level_id = ? "
            "ORDER BY created_at DESC", (student_id, level_id),
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        if len(json.loads(row["solved_json"])) < row["quest_length"]:
            return load_session(row["id"])
    return None


def open_level_ids(student_id: str) -> set:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT level_id, quest_length, solved_json FROM sessions WHERE student_id = ? AND level_id IS NOT NULL",
            (student_id,),
        ).fetchall()
    finally:
        conn.close()
    return {r["level_id"] for r in rows if len(json.loads(r["solved_json"])) < r["quest_length"]}


# ------------------------------------------------------------ XP ledger / levels

def xp_already_awarded(student_id: str, level_id: str, question_id: str) -> bool:
    conn = _connect()
    try:
        return conn.execute(
            "SELECT 1 FROM xp_awards WHERE student_id = ? AND level_id = ? AND question_id = ?",
            (student_id, level_id, question_id),
        ).fetchone() is not None
    finally:
        conn.close()


def student_xp_total(student_id: str) -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COALESCE(SUM(xp), 0) FROM xp_awards WHERE student_id = ?", (student_id,)).fetchone()[0]
    finally:
        conn.close()


def session_xp(session_id: str) -> int:
    conn = _connect()
    try:
        return conn.execute("SELECT COALESCE(SUM(xp), 0) FROM xp_awards WHERE session_id = ?", (session_id,)).fetchone()[0]
    finally:
        conn.close()


def fetch_completions(student_id: str) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM level_completions WHERE student_id = ? ORDER BY completed_at, rowid", (student_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def ensure_completion(completion: dict) -> bool:
    """Records a level completion for a session; a repeat is a no-op.
    Returns True if a new row was written."""
    conn = _connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT OR IGNORE INTO level_completions (session_id, student_id, level_id, completed_at, "
                "questions, attempts, first_try_pct) VALUES (:session_id,:student_id,:level_id,:completed_at,"
                ":questions,:attempts,:first_try_pct)",
                {**completion, "completed_at": _now()},
            )
            return cur.rowcount == 1
    finally:
        conn.close()


def record_attempt(
    *,
    student_id: str,
    session_id: str,
    question_id: str,
    topic: str,
    selected_answer: Optional[str],
    is_correct: bool,
    attempt_no: int,
    response_time_ms: int,
    options_shown: Optional[int] = None,
    session_state: Optional[dict] = None,
    xp_award: Optional[dict] = None,
    completion: Optional[dict] = None,
) -> None:
    """Appends one attempt and (in the same transaction) the session state it
    produced -- plus, for level sessions, the XP ledger row and the level
    completion it caused -- so they can never disagree. Raises on any failure:
    the caller must treat the submission as not recorded. A duplicate
    (session, question, attempt_no) raises sqlite3.IntegrityError."""
    answer = None if selected_answer is None else str(selected_answer)[:MAX_ANSWER_CHARS]
    conn = _connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO attempts (student_id, session_id, question_id, topic, selected_answer, "
                "is_correct, attempt_no, response_time_ms, submitted_at, options_shown) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (student_id, session_id, question_id, topic, answer, int(is_correct),
                 attempt_no, max(0, int(response_time_ms)), _now(), options_shown),
            )
            if session_state is not None:
                _save_session(conn, session_state)
            if xp_award is not None:
                # Primary key (student, level, question): a second grant for the
                # same question is ignored, never doubled.
                conn.execute(
                    "INSERT OR IGNORE INTO xp_awards (student_id, level_id, question_id, xp, session_id, awarded_at) "
                    "VALUES (:student_id,:level_id,:question_id,:xp,:session_id,:now)",
                    {**xp_award, "now": _now()},
                )
            if completion is not None:
                conn.execute(
                    "INSERT OR IGNORE INTO level_completions (session_id, student_id, level_id, completed_at, "
                    "questions, attempts, first_try_pct) VALUES (:session_id,:student_id,:level_id,:completed_at,"
                    ":questions,:attempts,:first_try_pct)",
                    {**completion, "completed_at": _now()},
                )
    finally:
        conn.close()


def fetch_session_attempts(session_id: str) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE session_id = ? ORDER BY id", (session_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def fetch_student_attempts(student_id: str) -> list:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM attempts WHERE student_id = ? ORDER BY id", (student_id,)
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]
