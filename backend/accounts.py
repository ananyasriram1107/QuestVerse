"""
User accounts: registration, login, bearer-token sessions, per-user achievements.

Design notes
  * Passwords are never stored: only a scrypt hash with a random per-user salt, compared in
    constant time. Login errors are deliberately generic so they don't reveal which
    usernames exist, and repeated failures are throttled per username.
  * A login returns a random bearer token. Only its SHA-256 is stored, so a leaked database
    can't be replayed. Tokens expire after TOKEN_TTL_DAYS and are deleted on logout.
  * A user owns "students": one per hero (character) they play, with the server-side id
    `u<user id>.<character>`. Every existing table already keys on student_id, so levels, XP,
    attempts and quests are per user and per hero without any other schema change. The
    server -- not the client -- decides which student ids a request may touch (see
    attempt_store.ACTIVE_USER_ID, set by the login middleware in main.py).
  * Achievements are recorded per user. The browser still computes the stats (it also counts
    offline free play), so the server only accepts values that stay inside sane bounds and
    never lets a stat go down.
"""

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import attempt_store

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}$")
MIN_PASSWORD_LEN = 8
MAX_PASSWORD_LEN = 128
TOKEN_TTL_DAYS = 30
_SCRYPT = {"n": 2 ** 14, "r": 8, "p": 1, "dklen": 32}

MAX_FAILURES = 5            # failed logins per username...
FAILURE_WINDOW_S = 300      # ...within this window lock further attempts out
_FAILURES: dict = {}
_FAILURES_LOCK = threading.Lock()

STAT_KEYS = ("totalAnswered", "totalMcqAnswered", "totalShortAnswered", "totalCorrect", "longestStreakEver")
MAX_STAT = 1_000_000
ACHIEVEMENT_ID_RE = re.compile(r"^[a-z0-9_]{1,40}$")
MAX_ACHIEVEMENTS = 100


class AccountError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def _hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)


def _public(row) -> dict:
    return {"id": row["id"], "username": row["username"], "email": row["email"], "created_at": row["created_at"]}


def student_id_for(user_id: int, character_id: str) -> str:
    return f"u{user_id}.{character_id}"


def student_pattern(user_id: int) -> str:
    return f"u{int(user_id)}.%"


# ------------------------------------------------------------------ register / login

def register(username: str, password: str, email: Optional[str] = None) -> dict:
    username = (username or "").strip()
    email = (email or "").strip() or None
    if not USERNAME_RE.match(username):
        raise AccountError(400, "Usernames are 3-32 characters: letters, numbers, dot, dash or underscore.")
    if not (MIN_PASSWORD_LEN <= len(password or "") <= MAX_PASSWORD_LEN):
        raise AccountError(400, f"Passwords need {MIN_PASSWORD_LEN}-{MAX_PASSWORD_LEN} characters.")
    if email is not None and not EMAIL_RE.match(email):
        raise AccountError(400, "That email address doesn't look right.")
    salt = secrets.token_bytes(16)
    digest = _hash(password, salt)
    conn = attempt_store._connect()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (username, email, password_hash, salt, created_at) VALUES (?,?,?,?,?)",
                (username, email, digest.hex(), salt.hex(), _iso(_now())),
            )
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    except sqlite3.IntegrityError as e:
        raise AccountError(409, "That username is taken.") from e
    finally:
        conn.close()
    return _public(row)


def _throttled(key: str) -> bool:
    now = time.time()
    with _FAILURES_LOCK:
        recent = [t for t in _FAILURES.get(key, []) if now - t < FAILURE_WINDOW_S]
        _FAILURES[key] = recent
        return len(recent) >= MAX_FAILURES


def _note_failure(key: str) -> None:
    with _FAILURES_LOCK:
        _FAILURES.setdefault(key, []).append(time.time())


def login(username: str, password: str) -> tuple:
    """(bearer token, public user). Raises AccountError with a generic message on any bad login."""
    key = (username or "").strip().lower()
    if _throttled(key):
        raise AccountError(429, "Too many tries. Please wait a few minutes and try again.")
    conn = attempt_store._connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ? COLLATE NOCASE", (key,)).fetchone()
        salt = bytes.fromhex(row["salt"]) if row else b"\0" * 16          # same work whether or not the user exists
        digest = _hash(password or "", salt)
        if row is None or not hmac.compare_digest(digest.hex(), row["password_hash"]):
            _note_failure(key)
            raise AccountError(401, "Incorrect username or password.")
        with _FAILURES_LOCK:
            _FAILURES.pop(key, None)
        token = secrets.token_urlsafe(32)
        now = _now()
        with conn:
            conn.execute(
                "INSERT INTO auth_tokens (token_hash, user_id, created_at, expires_at) VALUES (?,?,?,?)",
                (hashlib.sha256(token.encode()).hexdigest(), row["id"], _iso(now), _iso(now + timedelta(days=TOKEN_TTL_DAYS))),
            )
            conn.execute("DELETE FROM auth_tokens WHERE expires_at < ?", (_iso(now),))
        return token, _public(row)
    finally:
        conn.close()


def user_for_token(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    conn = attempt_store._connect()
    try:
        row = conn.execute(
            "SELECT u.* FROM auth_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash = ? AND t.expires_at > ?",
            (hashlib.sha256(token.encode()).hexdigest(), _iso(_now())),
        ).fetchone()
    finally:
        conn.close()
    return _public(row) if row else None


def logout(token: Optional[str]) -> None:
    if not token:
        return
    conn = attempt_store._connect()
    try:
        with conn:
            conn.execute("DELETE FROM auth_tokens WHERE token_hash = ?", (hashlib.sha256(token.encode()).hexdigest(),))
    finally:
        conn.close()


def set_email(user_id: int, email: Optional[str]) -> Optional[str]:
    email = (email or "").strip() or None
    if email is not None and not EMAIL_RE.match(email):
        raise AccountError(400, "That email address doesn't look right.")
    conn = attempt_store._connect()
    try:
        with conn:
            conn.execute("UPDATE users SET email = ? WHERE id = ?", (email, user_id))
    finally:
        conn.close()
    return email


def all_users() -> list:
    conn = attempt_store._connect()
    try:
        return [_public(r) for r in conn.execute("SELECT * FROM users ORDER BY id").fetchall()]
    finally:
        conn.close()


# ------------------------------------------------------------------ achievements

def get_achievements(user_id: int) -> dict:
    conn = attempt_store._connect()
    try:
        stats_row = conn.execute("SELECT stats_json FROM user_stats WHERE user_id = ?", (user_id,)).fetchone()
        unlocked = conn.execute(
            "SELECT achievement_id, unlocked_at FROM user_achievements WHERE user_id = ? ORDER BY unlocked_at, achievement_id",
            (user_id,),
        ).fetchall()
    finally:
        conn.close()
    stats = {k: 0 for k in STAT_KEYS}
    if stats_row:
        stats.update({k: v for k, v in json.loads(stats_row["stats_json"]).items() if k in STAT_KEYS})
    return {"stats": stats, "unlocked": [{"id": r["achievement_id"], "unlocked_at": r["unlocked_at"]} for r in unlocked]}


def save_achievements(user_id: int, stats: dict, unlocked_ids: list) -> dict:
    """Merges what the browser reports into the stored record: stats only ever go up, unlocks
    are only ever added (the first unlock time is kept). Out-of-range values are rejected."""
    clean_stats = {}
    for key in STAT_KEYS:
        value = (stats or {}).get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= MAX_STAT:
            raise AccountError(400, f"Invalid value for {key}.")
        clean_stats[key] = value
    ids = list(dict.fromkeys(unlocked_ids or []))
    if len(ids) > MAX_ACHIEVEMENTS or not all(isinstance(i, str) and ACHIEVEMENT_ID_RE.match(i) for i in ids):
        raise AccountError(400, "Invalid achievements.")
    current = get_achievements(user_id)["stats"]
    merged = {k: max(current[k], clean_stats[k]) for k in STAT_KEYS}
    now = _iso(_now())
    conn = attempt_store._connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO user_stats (user_id, stats_json, updated_at) VALUES (?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET stats_json = excluded.stats_json, updated_at = excluded.updated_at",
                (user_id, json.dumps(merged), now),
            )
            for achievement_id in ids:
                conn.execute(
                    "INSERT OR IGNORE INTO user_achievements (user_id, achievement_id, unlocked_at) VALUES (?,?,?)",
                    (user_id, achievement_id, now),
                )
    finally:
        conn.close()
    return get_achievements(user_id)
