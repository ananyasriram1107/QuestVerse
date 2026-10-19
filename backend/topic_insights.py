"""
Per-topic performance and practice recommendations.

"Topic" here means the course (os, dbms, dsa, lang, custom) -- the only
subject grouping the question banks actually have. Everything is computed
from the stored attempt log, and every recommendation names a course/mode
pair that exists in the loaded question banks; nothing is invented.
"""

from statistics import median
from typing import Callable, Optional

CONFIG = {
    "min_topic_questions": 5,        # fewer attempted questions -> "not enough data" for that topic
    "revise_first_attempt_below": 60.0,   # percent
    "revise_retry_rate_at_least": 50.0,   # percent
}


def _pct(num: int, den: int) -> Optional[float]:
    return round(100 * num / den, 1) if den else None


def topic_performance(rows: list, mode_of: Callable[[str], Optional[str]], config: dict = CONFIG) -> list:
    """`rows`: attempt rows (dicts) with session_id, question_id, topic,
    is_correct, attempt_no, response_time_ms. `mode_of(question_id)` returns
    "mcq"/"short_answer" or None if the question no longer exists."""
    grouped: dict = {}
    for r in rows:
        grouped.setdefault(r["topic"], {}).setdefault((r["session_id"], r["question_id"]), []).append(r)

    out = []
    for topic, questions in grouped.items():
        n = len(questions)
        firsts = [sorted(qa, key=lambda r: r["attempt_no"])[0] for qa in questions.values()]
        first_correct = sum(1 for f in firsts if f["is_correct"])
        retried = n - first_correct
        submissions = sum(len(qa) for qa in questions.values())
        solved = sum(1 for qa in questions.values() if any(r["is_correct"] for r in qa))

        t_right = [f["response_time_ms"] for f in firsts if f["is_correct"]]
        t_wrong = [f["response_time_ms"] for f in firsts if not f["is_correct"]]

        by_mode: dict = {}
        for f in firsts:
            m = mode_of(f["question_id"])
            if m:
                d = by_mode.setdefault(m, {"questions": 0, "first_correct": 0})
                d["questions"] += 1
                d["first_correct"] += 1 if f["is_correct"] else 0

        enough = n >= config["min_topic_questions"]
        fa = _pct(first_correct, n)
        rr = _pct(retried, n)
        needs_revision = bool(
            enough and (fa < config["revise_first_attempt_below"] or rr >= config["revise_retry_rate_at_least"])
        )
        out.append({
            "topic": topic,
            "questions_attempted": n,
            "questions_solved": solved,
            "first_attempt_accuracy_pct": fa,
            "questions_needing_retries": retried,
            "retry_rate_pct": rr,
            "avg_attempts_per_question": round(submissions / n, 2),
            "response_time": {
                "median_first_attempt_ms": int(median([f["response_time_ms"] for f in firsts])),
                "median_when_first_correct_ms": int(median(t_right)) if t_right else None,
                "median_when_first_wrong_ms": int(median(t_wrong)) if t_wrong else None,
            },
            "by_mode": {m: {**d, "first_attempt_accuracy_pct": _pct(d["first_correct"], d["questions"])}
                        for m, d in by_mode.items()},
            "enough_data": enough,
            "needs_revision": needs_revision,
        })
    out.sort(key=lambda t: (not t["needs_revision"], t["first_attempt_accuracy_pct"] or 0))
    return out


def recommend(topics: list, available: Callable[[str, str], bool], titles: dict, all_courses: list,
              current_topic: str, config: dict = CONFIG) -> list:
    """Practice suggestions drawn only from real course/mode combinations."""
    recs = []
    for t in topics:
        if not t["needs_revision"]:
            continue
        title = titles.get(t["topic"], t["topic"])
        # Prefer the mode this student struggled with most in this topic.
        modes = [(m, d) for m, d in t["by_mode"].items() if available(t["topic"], m) and d["questions"] >= 2]
        mode = min(modes, key=lambda x: x[1]["first_attempt_accuracy_pct"])[0] if modes else None
        if mode is None:
            mode = next((m for m in ("mcq", "short_answer") if available(t["topic"], m)), None)
        if mode is None:
            continue
        reason = (f"{t['first_attempt_accuracy_pct']:.0f}% right on the first try across "
                  f"{t['questions_attempted']} {title} questions, with {t['retry_rate_pct']:.0f}% needing a retry.")
        recs.append({
            "type": "revise",
            "courseId": t["topic"],
            "title": title,
            "mode": mode,
            "reason": reason,
        })

    if not recs:
        # No weak area found: suggest a course the student has not tried yet.
        tried = {t["topic"] for t in topics}
        for cid in all_courses:
            if cid not in tried and cid != current_topic:
                mode = next((m for m in ("mcq", "short_answer") if available(cid, m)), None)
                if mode:
                    recs.append({
                        "type": "explore", "courseId": cid, "title": titles.get(cid, cid), "mode": mode,
                        "reason": "No weak areas found so far -- try a topic you haven't played yet.",
                    })
                    break
        if not recs and current_topic:
            mode = next((m for m in ("short_answer", "mcq") if available(current_topic, m)), None)
            if mode:
                recs.append({
                    "type": "stretch", "courseId": current_topic,
                    "title": titles.get(current_topic, current_topic), "mode": mode,
                    "reason": "Solid first-try results here -- try it again in the other format to check the knowledge holds up.",
                })
    return recs
