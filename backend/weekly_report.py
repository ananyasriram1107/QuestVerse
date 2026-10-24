"""
Weekly progress reports, built from what is already recorded in the database.

Nothing new is measured here: a report is a summary of a user's `attempts`,
`level_completions`, `xp_awards` and `user_achievements` rows for one calendar week
(Monday 00:00 UTC to the next Monday), across all of the user's heroes. Accuracy means
FIRST-TRY accuracy -- the share of questions answered right on the first attempt -- which is
the same figure the quest reports use.

Finished weeks are stored once in `weekly_reports` (so they never change afterwards, even if
the code that builds them does); the current week is rebuilt on every request. A background
loop (start_scheduler) stores last week's report for everyone and, if SMTP is configured
through environment variables and the user gave an email address, emails it once.
"""

import json
import logging
import os
import smtplib
import threading
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Optional

import accounts
import attempt_store
from guess_analysis import analyze_attempts
from quest_session import attempt_view

log = logging.getLogger(__name__)

SCHEDULER_INTERVAL_S = 3600
SMTP_VARS = ("QUESTVERSE_SMTP_HOST", "QUESTVERSE_SMTP_FROM")


def week_start_of(moment: datetime) -> datetime:
    moment = moment.astimezone(timezone.utc)
    return (moment - timedelta(days=moment.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds")


def _pct(num: int, den: int) -> Optional[float]:
    return round(100 * num / den, 1) if den else None


def _week_attempts(conn, user_id: int, start: datetime, end: datetime) -> list:
    return [dict(r) for r in conn.execute(
        "SELECT * FROM attempts WHERE student_id LIKE ? AND submitted_at >= ? AND submitted_at < ? ORDER BY id",
        (accounts.student_pattern(user_id), _iso(start), _iso(end)),
    ).fetchall()]


def _first_attempts(rows: list) -> dict:
    """{(session, question): that question's first attempt row} -- one entry per question played."""
    return {(r["session_id"], r["question_id"]): r for r in rows if r["attempt_no"] == 1}


def build_report(user_id: int, start: datetime) -> dict:
    start = week_start_of(start)
    end = start + timedelta(days=7)
    prev_start = start - timedelta(days=7)
    conn = attempt_store._connect()
    try:
        rows = _week_attempts(conn, user_id, start, end)
        prev_rows = _week_attempts(conn, user_id, prev_start, start)
        pattern = accounts.student_pattern(user_id)
        completions = conn.execute(
            "SELECT level_id, student_id, completed_at, first_try_pct FROM level_completions "
            "WHERE student_id LIKE ? AND completed_at >= ? AND completed_at < ? ORDER BY completed_at",
            (pattern, _iso(start), _iso(end)),
        ).fetchall()
        xp = conn.execute(
            "SELECT COALESCE(SUM(xp), 0) FROM xp_awards WHERE student_id LIKE ? AND awarded_at >= ? AND awarded_at < ?",
            (pattern, _iso(start), _iso(end)),
        ).fetchone()[0]
        unlocked = conn.execute(
            "SELECT achievement_id, unlocked_at FROM user_achievements WHERE user_id = ? AND unlocked_at >= ? AND unlocked_at < ? "
            "ORDER BY unlocked_at", (user_id, _iso(start), _iso(end)),
        ).fetchall()
        total_unlocked = conn.execute("SELECT COUNT(*) FROM user_achievements WHERE user_id = ?", (user_id,)).fetchone()[0]
    finally:
        conn.close()

    first = _first_attempts(rows)
    questions = len(first)
    right = sum(1 for r in first.values() if r["is_correct"])
    prev_first = _first_attempts(prev_rows)
    prev_accuracy = _pct(sum(1 for r in prev_first.values() if r["is_correct"]), len(prev_first))
    accuracy = _pct(right, questions)

    heroes: dict = {}
    topics: dict = {}
    for row in first.values():
        ok = bool(row["is_correct"])
        hero = row["student_id"].split(".", 1)[1] if "." in row["student_id"] else row["student_id"]
        for bucket, key in ((heroes, hero), (topics, row["topic"])):
            entry = bucket.setdefault(key, {"questions": 0, "first_try_right": 0})
            entry["questions"] += 1
            entry["first_try_right"] += int(ok)
    for bucket in (heroes, topics):
        for entry in bucket.values():
            entry["first_try_accuracy_pct"] = _pct(entry["first_try_right"], entry["questions"])

    guess = analyze_attempts([attempt_view(r) for r in rows])
    days_active = len({r["submitted_at"][:10] for r in rows})

    report = {
        "week_start": _iso(start),
        "week_end": _iso(end),
        "in_progress": datetime.now(timezone.utc) < end,
        "questions_answered": questions,
        "attempts": len(rows),
        "first_try_accuracy_pct": accuracy,
        "previous_week_accuracy_pct": prev_accuracy,
        "accuracy_change_pts": round(accuracy - prev_accuracy, 1) if accuracy is not None and prev_accuracy is not None else None,
        "days_active": days_active,
        "xp_earned": xp,
        "levels_completed": [
            {"level_id": c["level_id"], "hero": c["student_id"].split(".", 1)[-1],
             "completed_at": c["completed_at"], "first_try_pct": c["first_try_pct"]} for c in completions
        ],
        "achievements_unlocked": [{"id": u["achievement_id"], "unlocked_at": u["unlocked_at"]} for u in unlocked],
        "achievements_total": total_unlocked,
        "heroes": heroes,
        "topics": topics,
        "guessing_pattern": {"status": guess["status"], "headline": guess["summary"]["headline"],
                             "next_step": guess["summary"]["next_step"]},
    }
    report["highlights"] = _highlights(report)
    return report


def _highlights(r: dict) -> list:
    if r["questions_answered"] == 0:
        return ["No quests this week - a short one is a great way to start the next."]
    lines = [f"You answered {r['questions_answered']} question{'s' * (r['questions_answered'] != 1)} on "
             f"{r['days_active']} day{'s' * (r['days_active'] != 1)}, getting {r['first_try_accuracy_pct']:.0f}% right on the first try."]
    change = r["accuracy_change_pts"]
    if change is not None and abs(change) >= 1:
        lines.append(f"That's {'up' if change > 0 else 'down'} {abs(change):.0f} point{'s' * (abs(change) >= 1.5)} from last week.")
    if r["levels_completed"]:
        n = len(r["levels_completed"])
        lines.append(f"You cleared {n} level{'s' * (n != 1)} and earned {r['xp_earned']} XP.")
    if r["achievements_unlocked"]:
        lines.append(f"{len(r['achievements_unlocked'])} new achievement{'s' * (len(r['achievements_unlocked']) != 1)} unlocked.")
    practice = [t for t, e in r["topics"].items() if e["questions"] >= 4 and e["first_try_accuracy_pct"] < 60]
    if practice:
        lines.append(f"Worth another look next week: {', '.join(t.upper() for t in sorted(practice))}.")
    return lines


# ------------------------------------------------------------------ storage

def get_report(user_id: int, start: Optional[datetime] = None) -> dict:
    """The week's report. Finished weeks are stored on first request and returned as stored."""
    start = week_start_of(start or datetime.now(timezone.utc))
    in_progress = datetime.now(timezone.utc) < start + timedelta(days=7)
    conn = attempt_store._connect()
    try:
        if not in_progress:
            row = conn.execute(
                "SELECT report_json FROM weekly_reports WHERE user_id = ? AND week_start = ?", (user_id, _iso(start))
            ).fetchone()
            if row:
                return json.loads(row["report_json"])
    finally:
        conn.close()
    report = build_report(user_id, start)
    if not in_progress:
        conn = attempt_store._connect()
        try:
            with conn:
                conn.execute(
                    "INSERT OR IGNORE INTO weekly_reports (user_id, week_start, report_json, generated_at) VALUES (?,?,?,?)",
                    (user_id, _iso(start), json.dumps(report), _iso(datetime.now(timezone.utc))),
                )
        finally:
            conn.close()
    return report


def list_weeks(user_id: int, limit: int = 12) -> list:
    """Week starts (newest first) the user has any recorded play in, plus the current week."""
    conn = attempt_store._connect()
    try:
        rows = conn.execute(
            "SELECT submitted_at FROM attempts WHERE student_id LIKE ?", (accounts.student_pattern(user_id),)
        ).fetchall()
    finally:
        conn.close()
    weeks = {week_start_of(datetime.now(timezone.utc))}
    for r in rows:
        weeks.add(week_start_of(datetime.fromisoformat(r["submitted_at"])))
    return [_iso(w) for w in sorted(weeks, reverse=True)[:limit]]


# ------------------------------------------------------------------ email + scheduler

def smtp_configured() -> bool:
    return all(os.environ.get(v) for v in SMTP_VARS)


def render_text(username: str, report: dict) -> str:
    lines = [f"Hi {username},", "", "Your QuestVerse week:", ""]
    lines += [f"- {h}" for h in report["highlights"]]
    if report["topics"]:
        lines += ["", "By topic (first-try accuracy):"]
        lines += [f"- {t.upper()}: {e['first_try_accuracy_pct']:.0f}% over {e['questions']} questions"
                  for t, e in sorted(report["topics"].items())]
    lines += ["", f"Guessing pattern: {report['guessing_pattern']['headline']} {report['guessing_pattern']['next_step']}",
              "", "Keep questing!"]
    return "\n".join(lines)


def send_email(user: dict, report: dict) -> bool:
    """Sends the report if SMTP is configured; False (and nothing sent) otherwise."""
    if not user.get("email") or not smtp_configured():
        return False
    message = EmailMessage()
    message["Subject"] = "Your QuestVerse weekly progress"
    message["From"] = os.environ["QUESTVERSE_SMTP_FROM"]
    message["To"] = user["email"]
    message.set_content(render_text(user["username"], report))
    try:
        with smtplib.SMTP(os.environ["QUESTVERSE_SMTP_HOST"], int(os.environ.get("QUESTVERSE_SMTP_PORT", "587")), timeout=20) as smtp:
            if os.environ.get("QUESTVERSE_SMTP_USER"):
                smtp.starttls()
                smtp.login(os.environ["QUESTVERSE_SMTP_USER"], os.environ.get("QUESTVERSE_SMTP_PASSWORD", ""))
            smtp.send_message(message)
        return True
    except (OSError, smtplib.SMTPException):
        log.exception("could not email the weekly report to user %s", user["id"])
        return False


def run_weekly_job(now: Optional[datetime] = None) -> int:
    """Stores last week's report for every user and emails it once. Returns how many were emailed."""
    now = now or datetime.now(timezone.utc)
    last_week = week_start_of(now) - timedelta(days=7)
    sent = 0
    for user in accounts.all_users():
        report = get_report(user["id"], last_week)
        conn = attempt_store._connect()
        try:
            already = conn.execute(
                "SELECT emailed_at FROM weekly_reports WHERE user_id = ? AND week_start = ?", (user["id"], _iso(last_week))
            ).fetchone()
        finally:
            conn.close()
        if already and already["emailed_at"] is None and report["questions_answered"] > 0 and send_email(user, report):
            conn = attempt_store._connect()
            try:
                with conn:
                    conn.execute("UPDATE weekly_reports SET emailed_at = ? WHERE user_id = ? AND week_start = ?",
                                 (_iso(datetime.now(timezone.utc)), user["id"], _iso(last_week)))
            finally:
                conn.close()
            sent += 1
    return sent


def start_scheduler() -> None:
    def loop():
        while True:
            try:
                run_weekly_job()
            except Exception:  # keep the loop alive whatever one run hits
                log.exception("weekly report job failed")
            time.sleep(SCHEDULER_INTERVAL_S)

    threading.Thread(target=loop, daemon=True, name="weekly-reports").start()
