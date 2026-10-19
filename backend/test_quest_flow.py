"""
Tests for server-side quest progression, persistence and analytics.

Same style as test_engine.py (plain asserts, run with `python test_quest_flow.py`).
Uses a throwaway SQLite file and calls the endpoint functions directly, so no
server needs to be running and the real questverse.db is never touched.
"""

import json
import os
import sqlite3
import tempfile
import threading
import time

from fastapi import HTTPException

import attempt_store

_tmpdir = tempfile.mkdtemp()
attempt_store.DB_PATH = os.path.join(_tmpdir, "test.db")
attempt_store.init_db()

import main  # noqa: E402  (must come after DB_PATH is redirected)
import progression  # noqa: E402
import quest_session  # noqa: E402
import level_fill  # noqa: E402
from guess_analysis import analyze_attempts  # noqa: E402
from topic_insights import recommend, topic_performance  # noqa: E402

ANS = main.AnswerRequest
_counter = {"n": 0}


def new_student() -> str:
    _counter["n"] += 1
    return f"student{_counter['n']}"


def start(student: str, course="os", mode="mcq") -> dict:
    return main.get_first_question(course, mode, 0, student)


def submit(session_id, student, question_id, answer):
    """Returns the response dict, or the HTTP status code on rejection."""
    try:
        return main.submit_answer(ANS(session_id=session_id, student_id=student, question_id=question_id, answer=answer))
    except HTTPException as e:
        return e.status_code


def right_of(qid):
    return main.QUESTIONS_BY_ID[str(qid)]["correct_answer"]


def wrongs_of(qid):
    q = main.QUESTIONS_BY_ID[str(qid)]
    return [o for o in q["options"] if o != q["correct_answer"]]


def attempt_rows(session_id):
    return attempt_store.fetch_session_attempts(session_id)


def play_quest(student, first_try_wrong=0):
    """Plays a full quest; the first `first_try_wrong` questions get one wrong
    answer before the right one. Returns (session_id, last_response)."""
    r = start(student)
    sid, qid, last = r["session_id"], r["id"], None
    for i in range(5):
        if i < first_try_wrong:
            assert submit(sid, student, qid, wrongs_of(qid)[0])["correct"] is False
        last = submit(sid, student, qid, right_of(qid))
        assert last["correct"] is True
        if last["next_question"]:
            qid = last["next_question"]["id"]
    return sid, last


# ---------------------------------------------------------------- progression

def test_correct_first_attempt_unlocks_next():
    s = new_student()
    r = start(s)
    res = submit(r["session_id"], s, r["id"], right_of(r["id"]))
    assert res["correct"] and res["question_solved"]
    assert res["next_question"]["id"] != r["id"], "next question should be unlocked"
    assert res["solved_count"] == 1


def test_incorrect_does_not_unlock_and_hides_answer():
    s = new_student()
    r = start(s)
    res = submit(r["session_id"], s, r["id"], wrongs_of(r["id"])[0])
    assert res["correct"] is False and res["question_solved"] is False
    assert res["next_question"]["id"] == r["id"], "student must stay on the same question"
    assert res["xp_earned"] == 0 and res["total_xp"] == 0
    assert res["solved_count"] == 0
    assert res["hint"], "a hint should be returned"
    leaked = json.dumps({"evaluation": res["evaluation"], "hint": res["hint"]})
    assert right_of(r["id"]) not in leaked, "correct answer must not be revealed after a miss"
    assert "correct_answer" not in res["evaluation"] and "explanation" not in res["evaluation"]


def test_multiple_incorrect_attempts_stay_on_same_question():
    s = new_student()
    r = start(s)
    qid = r["id"]
    for bad in wrongs_of(qid):  # all three wrong options
        res = submit(r["session_id"], s, qid, bad)
        assert res["next_question"]["id"] == qid
    rows = attempt_rows(r["session_id"])
    assert [(x["question_id"], x["attempt_no"], x["is_correct"]) for x in rows] == [(qid, 1, 0), (qid, 2, 0), (qid, 3, 0)]
    assert res["total_xp"] == 0


def test_correct_answer_eventually_unlocks_next():
    s = new_student()
    r = start(s)
    qid = r["id"]
    submit(r["session_id"], s, qid, wrongs_of(qid)[0])
    res = submit(r["session_id"], s, qid, right_of(qid))
    assert res["correct"] and res["next_question"]["id"] != qid
    assert res["solved_count"] == 1
    assert [x["attempt_no"] for x in attempt_rows(r["session_id"])] == [1, 2]


def test_cannot_skip_ahead_or_answer_other_questions():
    s = new_student()
    r = start(s)
    other = next(q["id"] for q in main.ALL_QUESTIONS if q["courseId"] == "os" and q["mode"] == "mcq" and q["id"] != r["id"])
    before = len(attempt_rows(r["session_id"]))
    assert submit(r["session_id"], s, other, right_of(other)) == 409, "later question must be locked"
    assert submit(r["session_id"], s, "no-such-question", "x") == 404
    assert len(attempt_rows(r["session_id"])) == before, "rejected submissions must not be recorded"
    # and a solved question can't be replayed
    res = submit(r["session_id"], s, r["id"], right_of(r["id"]))
    assert submit(r["session_id"], s, r["id"], right_of(r["id"])) == 409
    assert res["solved_count"] == 1


def test_other_students_session_is_rejected():
    owner, intruder = new_student(), new_student()
    r = start(owner)
    qid = r["id"]
    before = len(attempt_rows(r["session_id"]))
    assert submit(r["session_id"], intruder, qid, right_of(qid)) == 403
    assert submit(r["session_id"], None, qid, right_of(qid)) == 403, "missing student id is not the owner"
    for fn in (main.get_session_state, main.get_dashboard):
        try:
            fn(r["session_id"], intruder)
            raise AssertionError("expected 403")
        except HTTPException as e:
            assert e.status_code == 403
    assert len(attempt_rows(r["session_id"])) == before
    assert submit("not-a-session", owner, qid, "x") == 404


# ------------------------------------------------- elimination and 50/50 hint

def fifty(session_id, student, question_id):
    try:
        return main.use_fifty_fifty(main.HintRequest(session_id=session_id, student_id=student, question_id=question_id))
    except HTTPException as e:
        return e.status_code


def current_eliminated(session_id, student):
    return main.get_session_state(session_id, student)["question"].get("eliminated_options", [])


def test_a_miss_greys_out_only_the_option_picked():
    for _ in range(10):  # whichever option the random question puts in each slot
        s = new_student()
        r = start(s)
        qid = r["id"]
        pick = wrongs_of(qid)[-1]
        res = submit(r["session_id"], s, qid, pick)
        elim = res["next_question"]["eliminated_options"]
        assert elim == [pick], "exactly one option, the one the student picked"
        assert right_of(qid) not in elim
        assert "greyed out" in res["hint"] and "crossed out" not in res["hint"]
        assert res["next_question"]["fifty_fifty_available"] is False, "only two wrong options remain"


def test_timeout_eliminates_nothing():
    s = new_student()
    r = start(s)
    res = submit(r["session_id"], s, r["id"], None)
    assert res["correct"] is False and res["next_question"].get("eliminated_options", []) == []
    assert res["hint"].startswith("Time ran out.") and "greyed out" not in res["hint"]
    assert res["next_question"]["fifty_fifty_available"] is True


def test_fifty_fifty_removes_exactly_two_wrong_options_and_keeps_the_answer():
    for _ in range(15):
        s = new_student()
        r = start(s)
        qid = r["id"]
        assert r["fifty_fifty_available"] is True
        res = fifty(r["session_id"], s, qid)
        elim = res["next_question"]["eliminated_options"]
        assert res["removed_count"] == 2 and len(elim) == 2 and len(set(elim)) == 2
        assert right_of(qid) not in elim and all(o in wrongs_of(qid) for o in elim)
        remaining = [o for o in main.QUESTIONS_BY_ID[qid]["options"] if o not in elim]
        assert len(remaining) == 2 and right_of(qid) in remaining
        assert "two wrong options were removed" in res["hint"]
        assert res["next_question"]["fifty_fifty_available"] is False


def test_fifty_fifty_once_per_question_and_not_after_a_miss_leaves_too_few():
    s = new_student()
    r = start(s)
    qid = r["id"]
    assert isinstance(fifty(r["session_id"], s, qid), dict)
    assert fifty(r["session_id"], s, qid) == 409, "only once per question"
    s2 = new_student()
    r2 = start(s2)
    submit(r2["session_id"], s2, r2["id"], wrongs_of(r2["id"])[0])
    assert fifty(r2["session_id"], s2, r2["id"]) == 409, "would leave only the correct answer"
    assert len(current_eliminated(r2["session_id"], s2)) == 1, "a rejected request changes nothing"


def test_fifty_fifty_availability_resets_for_the_next_question():
    s = new_student()
    r = start(s)
    qid = r["id"]
    fifty(r["session_id"], s, qid)
    res = submit(r["session_id"], s, qid, right_of(qid))
    assert res["next_question"]["fifty_fifty_available"] is True
    assert res["next_question"].get("eliminated_options", []) == []


def test_fifty_fifty_validates_session_student_and_question():
    owner, intruder = new_student(), new_student()
    r = start(owner)
    qid = r["id"]
    other = next(q["id"] for q in main.ALL_QUESTIONS if q["courseId"] == "os" and q["mode"] == "mcq" and q["id"] != qid)
    assert fifty(r["session_id"], intruder, qid) == 403
    assert fifty(r["session_id"], owner, other) == 409, "can't hint a locked question"
    assert fifty("no-such-session", owner, qid) == 404
    assert current_eliminated(r["session_id"], owner) == []
    sa = start(owner, course="os", mode="short_answer")
    assert fifty(sa["session_id"], owner, sa["id"]) == 409, "multiple choice only"


def test_eliminated_options_cannot_be_submitted():
    s = new_student()
    r = start(s)
    qid = r["id"]
    removed = fifty(r["session_id"], s, qid)["next_question"]["eliminated_options"]
    before = len(attempt_rows(r["session_id"]))
    for option in removed:
        assert submit(r["session_id"], s, qid, option) == 409
    assert len(attempt_rows(r["session_id"])) == before, "rejected picks are not recorded as attempts"
    bad = wrongs_of(qid)
    bad = next(o for o in bad if o not in removed)
    submit(r["session_id"], s, qid, bad)
    assert submit(r["session_id"], s, qid, bad) == 409, "a struck-out wrong pick can't be resubmitted either"
    assert submit(r["session_id"], s, qid, right_of(qid))["correct"] is True


def test_fifty_fifty_survives_restart_and_leaves_xp_unchanged():
    s = new_student()
    r = start(s)
    qid = r["id"]
    removed = fifty(r["session_id"], s, qid)["next_question"]["eliminated_options"]
    quest_session.SESSIONS.clear()
    state = main.get_session_state(r["session_id"], s)
    assert state["question"]["eliminated_options"] == removed and state["total_xp"] == 0
    assert state["question"]["fifty_fifty_available"] is False, "the one use is remembered"
    assert fifty(r["session_id"], s, qid) == 409
    res = submit(r["session_id"], s, qid, right_of(qid))
    assert res["xp_earned"] == 10 and res["solved_count"] == 1, "XP and progression are unaffected"


def test_chance_baseline_uses_options_actually_shown():
    s = new_student()
    r = start(s)
    qid = r["id"]
    fifty(r["session_id"], s, qid)
    submit(r["session_id"], s, qid, right_of(qid))
    first = main.get_session_state(r["session_id"], s)["attempts"][0]
    assert first["n_options"] == 2, "a 50/50 first attempt is a 1-in-2 guess, not 1-in-4"
    assert attempt_rows(r["session_id"])[0]["options_shown"] == 2


# ------------------------------------------------------------- resume/persist

def test_resume_preserves_state_even_after_restart():
    s = new_student()
    r = start(s)
    qid = r["id"]
    res = submit(r["session_id"], s, qid, right_of(qid))          # solve Q1 (+10 xp)
    q2 = res["next_question"]["id"]
    submit(r["session_id"], s, q2, wrongs_of(q2)[0])               # miss Q2 once
    live = main.get_session_state(r["session_id"], s)

    quest_session.SESSIONS.clear()                                 # simulate a backend restart
    resumed = main.get_session_state(r["session_id"], s)
    assert resumed["question"]["id"] == q2 == live["question"]["id"]
    assert resumed["solved_count"] == 1 and resumed["total_xp"] == 10
    assert len(resumed["attempts"]) == 2, "attempt history must survive the restart"
    assert resumed["hint"] == live["hint"]
    assert resumed["question"]["eliminated_options"] == live["question"]["eliminated_options"]
    assert submit(r["session_id"], s, qid, right_of(qid)) == 409, "solved question stays locked after restart"
    nxt = submit(r["session_id"], s, q2, right_of(q2))
    assert nxt["solved_count"] == 2 and nxt["total_xp"] == 20


# ------------------------------------------------------------------------ XP

def test_xp_awarded_once_and_ignores_client_values():
    s = new_student()
    r = start(s)
    qid = r["id"]
    res = main.submit_answer(ANS(session_id=r["session_id"], student_id=s, question_id=qid,
                                 answer=right_of(qid), total_xp=999999, tier=3, correct_streak=9))
    assert res["xp_earned"] == 10 and res["total_xp"] == 10, "tier-1 question is worth 10 XP regardless of the payload"
    assert submit(r["session_id"], s, qid, right_of(qid)) == 409
    assert main.get_session_state(r["session_id"], s)["total_xp"] == 10


def test_concurrent_duplicate_submissions_award_once():
    s = new_student()
    r = start(s)
    qid, results = r["id"], []

    def worker():
        results.append(submit(r["session_id"], s, qid, right_of(qid)))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    ok = [x for x in results if isinstance(x, dict)]
    assert len(ok) == 1 and results.count(409) == 7, results
    assert main.get_session_state(r["session_id"], s)["total_xp"] == 10
    assert len(attempt_rows(r["session_id"])) == 1


def test_failed_database_write_is_not_swallowed_or_rewarded():
    s = new_student()
    r = start(s)
    qid = r["id"]
    original = attempt_store.record_attempt

    def boom(**kwargs):
        raise sqlite3.OperationalError("disk I/O error")

    attempt_store.record_attempt = boom
    try:
        assert submit(r["session_id"], s, qid, right_of(qid)) == 503
    finally:
        attempt_store.record_attempt = original
    state = main.get_session_state(r["session_id"], s)
    assert state["total_xp"] == 0 and state["solved_count"] == 0 and state["question"]["id"] == qid
    assert submit(r["session_id"], s, qid, right_of(qid))["solved_count"] == 1, "retry succeeds once the DB works"


# --------------------------------------------------------- completion/analysis

def test_dashboard_metrics_from_persisted_attempts():
    s = new_student()
    sid, last = play_quest(s, first_try_wrong=2)       # 2 of 5 questions missed first
    assert last["game_complete"] and last["next_question"] is None
    assert submit(sid, s, "anything", "x") in (404, 409)
    quest_session.SESSIONS.clear()                      # analysis must not depend on memory
    d = main.get_dashboard(sid, s)
    assert d["completion"]["complete"] and d["completion"]["solved"] == 5
    m = d["analysis"]["metrics"]
    assert m["first_attempt_accuracy_pct"] == 60.0
    assert m["retry_rate_pct"] == 40.0
    assert m["total_submissions"] == 7 and m["avg_attempts_per_question"] == 1.4
    assert m["correction_rate_pct"] == 100.0
    assert len(d["most_retried"]) == 2 and all(x["retries"] == 1 for x in d["most_retried"])
    assert d["topics"][0]["topic"] == "os"


def test_rejected_submissions_are_excluded_from_analysis():
    s, intruder = new_student(), new_student()
    r = start(s)
    sid, qid = r["session_id"], r["id"]
    submit(sid, intruder, qid, wrongs_of(qid)[0])       # 403
    submit(sid, s, "nope", "x")                         # 404
    other = next(q["id"] for q in main.ALL_QUESTIONS if q["courseId"] == "os" and q["mode"] == "mcq" and q["id"] != qid)
    submit(sid, s, other, wrongs_of(other)[0])          # 409
    assert attempt_rows(sid) == []
    for _ in range(4):
        res = submit(sid, s, qid, right_of(qid))
        qid = res["next_question"]["id"]
    res = submit(sid, s, qid, right_of(qid))
    d = main.get_dashboard(sid, s)
    assert d["analysis"]["metrics"]["total_submissions"] == 5
    assert d["analysis"]["metrics"]["first_attempt_accuracy_pct"] == 100.0


def _attempt(q, n, ok, ms, mode="mcq", k=4):
    return {"question_id": q, "attempt_no": n, "correct": ok, "time_taken_ms": ms,
            "mode": mode, "n_options": k if mode == "mcq" else None}


def test_correction_rate_not_applicable_when_nothing_missed():
    a = analyze_attempts([_attempt(f"q{i}", 1, True, 4000) for i in range(5)])
    assert a["metrics"]["correction_rate_pct"] is None
    assert "Not applicable" in a["metrics"]["correction_rate_note"]
    assert a["metrics"]["retry_rate_pct"] == 0.0 and a["risk"]["level"] == "low"


def test_insufficient_data_for_small_samples():
    a = analyze_attempts([_attempt(f"q{i}", 1, False, 100) for i in range(3)] +
                         [_attempt(f"q{i}", 2, True, 100) for i in range(3)])
    assert a["status"] == "insufficient_data" and "risk" not in a
    assert analyze_attempts([])["status"] == "insufficient_data"
    s = new_student()
    r = start(s)
    assert main.get_dashboard(r["session_id"], s)["analysis"]["status"] == "insufficient_data"


def test_fast_answers_alone_never_classified_as_guessing():
    fast_correct = analyze_attempts([_attempt(f"q{i}", 1, True, 150) for i in range(5)])
    assert fast_correct["risk"]["level"] == "low"
    # Fast wrong-then-right, but accuracy signals are NOT triggered => timing adds nothing.
    atts = []
    for i in range(5):
        atts.append(_attempt(f"q{i}", 1, True, 300, mode="short_answer"))
    atts += [_attempt("q0", 0, False, 100, mode="short_answer")]  # stray extra row before: ignored ordering is by list
    res = analyze_attempts(atts)
    timing = next(s for s in res["risk"]["signals"] if s["id"] == "repeated_rapid_incorrect")
    assert timing["points"] == 0 and res["risk"]["level"] == "low"
    # Slow, deliberate wrong answers still raise accuracy-based signals (time is not what drives risk).
    slow = []
    for i in range(5):
        slow += [_attempt(f"q{i}", 1, False, 9000), _attempt(f"q{i}", 2, True, 9000)]
    res = analyze_attempts(slow)
    assert res["risk"]["level"] != "low"
    timing = next(s for s in res["risk"]["signals"] if s["id"] == "repeated_rapid_incorrect")
    assert timing["points"] == 0


def test_rapid_wrong_streaks_add_risk_only_alongside_accuracy_signals():
    pattern = []
    for i in range(5):
        pattern += [_attempt(f"q{i}", 1, False, 500), _attempt(f"q{i}", 2, False, 400), _attempt(f"q{i}", 3, True, 400)]
    res = analyze_attempts(pattern)
    ids = {s["id"]: s for s in res["risk"]["signals"]}
    assert ids["low_first_attempt_accuracy"]["points"] == 2 and ids["high_retry_rate"]["points"] == 1
    assert ids["repeated_rapid_incorrect"]["points"] == 2
    assert res["risk"]["level"] == "high" and res["chance_baseline"]["applicable"]
    assert res["chance_baseline"]["expected_correct_by_guessing"] == 1.2
    assert res["risk"]["meaning"] and res["limitations"], "output must disclose that this is not proof"


def test_chance_baseline_not_applied_to_short_answer():
    atts = [_attempt(f"q{i}", 1, False, 8000, mode="short_answer") for i in range(5)]
    atts += [_attempt(f"q{i}", 2, True, 8000, mode="short_answer") for i in range(5)]
    res = analyze_attempts(atts)
    assert res["chance_baseline"]["applicable"] is False
    chance = next(s for s in res["risk"]["signals"] if s["id"] == "chance_consistent_mcq")
    assert chance["points"] == 0


# ---------------------------------------------------------- topics/recommend

def test_topic_performance_and_recommendations_use_real_content():
    rows = []
    for i in range(6):                       # dbms: always wrong first try
        rows += [dict(session_id="s1", question_id=f"dbms-{i}", topic="dbms", is_correct=0, attempt_no=1, response_time_ms=3000),
                 dict(session_id="s1", question_id=f"dbms-{i}", topic="dbms", is_correct=1, attempt_no=2, response_time_ms=2000)]
    for i in range(5):                       # os: always right
        rows.append(dict(session_id="s2", question_id=f"os-{i}", topic="os", is_correct=1, attempt_no=1, response_time_ms=4000))
    rows.append(dict(session_id="s3", question_id="dsa-1", topic="dsa", is_correct=0, attempt_no=1, response_time_ms=1000))

    topics = topic_performance(rows, lambda qid: "mcq")
    by = {t["topic"]: t for t in topics}
    assert by["dbms"]["first_attempt_accuracy_pct"] == 0.0 and by["dbms"]["retry_rate_pct"] == 100.0
    assert by["dbms"]["avg_attempts_per_question"] == 2.0 and by["dbms"]["needs_revision"]
    assert by["os"]["first_attempt_accuracy_pct"] == 100.0 and not by["os"]["needs_revision"]
    assert by["dsa"]["enough_data"] is False and not by["dsa"]["needs_revision"], "1 question is too little to judge"
    assert topics[0]["topic"] == "dbms", "topics needing revision sort first"

    available = lambda cid, m: (cid, m) in main.QUESTIONS_BY_COURSE_MODE
    recs = recommend(topics, available, main.COURSE_TITLES, ["os", "dbms", "dsa", "lang"], "os")
    assert recs and recs[0]["courseId"] == "dbms" and recs[0]["type"] == "revise"
    for rec in recs:
        assert (rec["courseId"], rec["mode"]) in main.QUESTIONS_BY_COURSE_MODE, "recommendations must exist in the app"


def test_solved_questions_are_never_served_again_and_short_banks_finish():
    for _ in range(10):  # random picks -- repeat to catch tier-pool repeats
        s = new_student()
        r = start(s)
        seen, qid = [], r["id"]
        for _ in range(5):
            seen.append(qid)
            res = submit(r["session_id"], s, qid, right_of(qid))
            qid = res["next_question"]["id"] if res["next_question"] else None
        assert len(set(seen)) == 5, seen
    # An uploaded PDF course can have fewer questions than a full quest.
    main.register_custom_questions([
        {"id": f"custom-mcq-{i}", "courseId": "custom", "mode": "mcq", "tier": 1, "prompt": f"Q{i}?",
         "options": ["a", "b", "c", "d"], "correct_answer": "a"} for i in range(3)
    ])
    s = new_student()
    r = start(s, course="custom")
    assert r["quest_length"] == 3
    qid, res = r["id"], None
    for _ in range(3):
        res = submit(r["session_id"], s, qid, "a")
        qid = res["next_question"]["id"] if res["next_question"] else None
    assert res["game_complete"] and res["solved_count"] == 3


# ----------------------------------------------------------- levels / stages

def right_answer(qid):
    """A correct answer for any question format, derived from the question data."""
    from ai.dataset import get_language

    q = main.QUESTIONS_BY_ID[str(qid)]
    if q["mode"] == "mcq":
        return q["correct_answer"]
    if q.get("keyword_clusters"):
        return " ".join(c["aliases"][0] for c in q["keyword_clusters"])
    value = get_language(q["language"])[q["field"]]
    if isinstance(value, list):
        candidates = [str(v) for v in value] + [", ".join(str(v) for v in value)]
    elif isinstance(value, str):
        candidates = [value]
    else:
        candidates = [str(value), str(int(value))]
    for candidate in candidates:
        if main.grade(q, candidate)[0]:
            return candidate
    raise AssertionError(f"no correct answer found for {qid}")


def wrong_answer(qid):
    q = main.QUESTIONS_BY_ID[str(qid)]
    return wrongs_of(qid)[0] if q["mode"] == "mcq" else "zzz"


def start_lvl(student, level_id, resume_only=False):
    try:
        return main.start_level(level_id, main.StartLevelRequest(student_id=student, resume_only=resume_only))
    except HTTPException as e:
        return e.status_code


def complete_lvl(student, level_id, session_id):
    try:
        return main.complete_level(level_id, main.CompleteLevelRequest(student_id=student, session_id=session_id))
    except HTTPException as e:
        return e.status_code


def solve_level(student, level_id, misses_first=0):
    """Plays a level to the end. Returns (session_id, last /answer response)."""
    r = start_lvl(student, level_id)
    assert isinstance(r, dict), r
    sid, qid, last = r["session_id"], r["id"], None
    for i in range(r["quest_length"]):
        if i < misses_first:
            miss = submit(sid, student, qid, wrong_answer(qid))
            assert miss["correct"] is False and miss["game_complete"] is False
        last = submit(sid, student, qid, right_answer(qid))
        assert last["correct"] is True, (qid, last)
        qid = last["next_question"]["id"] if last["next_question"] else None
    assert last["game_complete"] is True
    return sid, last


def level_state(student, level_id):
    p = main.get_progress(student)
    return next(l["state"] for st in p["stages"] for l in st["levels"] if l["id"] == level_id)


def test_new_student_sees_only_the_first_level_open():
    s = new_student()
    p = main.get_progress(s)
    states = {l["id"]: l["state"] for st in p["stages"] for l in st["levels"]}
    assert states["grove-os"] == "available" and p["current_level_id"] == "grove-os"
    assert sum(1 for v in states.values() if v != "locked") == 1
    assert [st["state"] for st in p["stages"]] == ["available", "locked", "locked", "locked"]
    assert p["total_xp"] == 0 and p["totals"]["levels_completed"] == 0
    assert all("question_ids" not in l and "correct_answer" not in str(l) for st in p["stages"] for l in st["levels"])
    assert main.get_stages()["stages"][0]["levels"][0]["id"] == "grove-os"


def test_locked_levels_cannot_be_started_directly():
    s = new_student()
    assert start_lvl(s, "grove-dbms") == 403, "next level in the stage is locked"
    assert start_lvl(s, "caverns-os") == 403, "next stage is locked"
    assert start_lvl(s, "no-such-level") == 404
    assert start_lvl(None, "grove-os") == 400 and start_lvl("bad id!", "grove-os") == 400
    assert main.get_progress(s)["totals"]["levels_completed"] == 0


def test_level_quiz_uses_the_levels_own_fixed_question_set():
    s = new_student()
    expected = main.CATALOG["levels"]["grove-os"]["question_ids"]
    r = start_lvl(s, "grove-os")
    assert r["level_id"] == "grove-os" and r["quest_length"] == len(expected) and r["id"] == expected[0]
    seen, qid = [], r["id"]
    while qid:
        seen.append(qid)
        res = submit(r["session_id"], s, qid, right_answer(qid))
        qid = res["next_question"]["id"] if res["next_question"] else None
    assert seen == expected and len(seen) >= 5 and all(main.QUESTIONS_BY_ID[q]["courseId"] == "os" for q in seen)


def test_wrong_answer_does_not_complete_a_level_and_complete_endpoint_refuses():
    s = new_student()
    r = start_lvl(s, "grove-os")
    sid, qid = r["session_id"], r["id"]
    submit(sid, s, qid, wrongs_of(qid)[0])
    assert complete_lvl(s, "grove-os", sid) == 409, "not finished yet"
    submit(sid, s, qid, right_of(qid))                       # first of five questions solved
    assert complete_lvl(s, "grove-os", sid) == 409
    assert level_state(s, "grove-os") == "in_progress" and level_state(s, "grove-dbms") == "locked"


def test_completing_a_level_unlocks_the_next_and_persists():
    s = new_student()
    sid, last = solve_level(s, "grove-os", misses_first=1)
    assert level_state(s, "grove-os") == "completed" and level_state(s, "grove-dbms") == "available"
    assert level_state(s, "grove-dsa") == "locked"
    quest_session.SESSIONS.clear()                           # restart: everything comes from the database
    p = main.get_progress(s)
    assert p["current_level_id"] == "grove-dbms" and p["totals"]["levels_completed"] == 1
    assert p["total_xp"] > 0, "XP was awarded for the solved questions"
    assert isinstance(start_lvl(s, "grove-dbms"), dict), "the unlocked level can now be started"


def test_stage_unlocks_only_after_every_level_of_the_previous_stage():
    s = new_student()
    for lv in ("grove-os", "grove-dbms", "grove-dsa"):
        solve_level(s, lv)
        assert level_state(s, "caverns-os") == "locked", "three of four levels done is not enough"
    assert start_lvl(s, "caverns-os") == 403
    solve_level(s, "grove-lang")
    assert level_state(s, "caverns-os") == "available"
    assert [st["state"] for st in main.get_progress(s)["stages"]][:2] == ["completed", "available"]


def test_results_report_xp_stars_unlocks_and_the_next_level():
    s = new_student()
    sid, _ = solve_level(s, "grove-os", misses_first=1)
    res = main.get_level_results("grove-os", s, sid)
    assert res["first_completion"] and res["xp"]["earned_this_run"] > 0
    assert res["xp"]["total"] == res["xp"]["earned_this_run"]
    assert res["questions"] == 5 and res["first_try_pct"] == 80.0 and res["stars"] == 3
    assert res["retries"] == 1 and res["attempts"] == 6
    assert [u["level_id"] for u in res["newly_unlocked"]] == ["grove-dbms"]
    assert res["next_level"]["id"] == "grove-dbms" and res["all_completed"] is False
    assert main.get_level_results("grove-os", s)["session_id"] == sid, "latest run when no session is given"
    try:
        main.get_level_results("grove-dbms", s)
        raise AssertionError("expected 404")
    except HTTPException as e:
        assert e.status_code == 404


def test_repeated_completion_and_replays_never_duplicate_xp():
    s = new_student()
    sid, _ = solve_level(s, "grove-os")
    first = complete_lvl(s, "grove-os", sid)
    again = complete_lvl(s, "grove-os", sid)
    assert first == again or (first["xp"], first["session_id"]) == (again["xp"], again["session_id"])
    assert len(attempt_store.fetch_completions(s)) == 1, "one completion row per run, however often it is confirmed"
    xp = main.get_progress(s)["total_xp"]
    assert xp > 0
    sid2, last2 = solve_level(s, "grove-os")                 # replay a completed level
    assert last2["total_xp"] == xp and last2["xp_earned"] == 0
    assert main.get_progress(s)["total_xp"] == xp, "replay earns nothing"
    res = main.get_level_results("grove-os", s, sid2)
    assert res["first_completion"] is False and res["xp"]["earned_this_run"] == 0 and res["newly_unlocked"] == []
    assert len(attempt_store.fetch_completions(s)) == 2
    assert main.get_progress(s)["totals"]["levels_completed"] == 1 and level_state(s, "grove-os") == "completed"


def test_abandoning_and_restarting_a_level_cannot_farm_xp():
    s = new_student()
    r = start_lvl(s, "grove-os")
    submit(r["session_id"], s, r["id"], right_of(r["id"]))   # earns the first question's XP, then quits
    first_xp = main.get_progress(s)["total_xp"]
    assert first_xp > 0
    again = start_lvl(s, "grove-os")
    assert again["resumed"] is True and again["session_id"] == r["session_id"] and again["solved_count"] == 1
    assert again["id"] != r["id"], "resumes at the next unsolved question, attempts intact"
    assert start_lvl(s, "grove-os", resume_only=True)["session_id"] == r["session_id"]
    res, qid = None, again["id"]
    while qid:
        res = submit(again["session_id"], s, qid, right_answer(qid))
        qid = res["next_question"]["id"] if res["next_question"] else None
    assert res["game_complete"] and main.get_progress(s)["total_xp"] > first_xp
    assert start_lvl(s, "grove-os", resume_only=True) == 409, "nothing left to resume once complete"


def test_completing_with_someone_elses_session_is_rejected():
    owner, other = new_student(), new_student()
    sid, _ = solve_level(owner, "grove-os")
    assert complete_lvl(other, "grove-os", sid) == 403
    assert complete_lvl(owner, "grove-dbms", sid) in (403, 409, 404), "wrong level for that session"
    assert complete_lvl(owner, "grove-os", "no-such-session") == 404
    assert main.get_progress(other)["totals"]["levels_completed"] == 0


def test_finishing_the_last_level_leaves_nothing_to_redirect_to():
    s = new_student()
    last_res = None
    for stage in main.CATALOG["stages"]:
        for lv in stage["levels"]:
            sid, _ = solve_level(s, lv["id"])
            last_res = main.get_level_results(lv["id"], s, sid)
    p = main.get_progress(s)
    assert p["all_completed"] is True and p["current_level_id"] is None
    assert p["totals"]["levels_completed"] == p["totals"]["levels_total"] == 16
    assert last_res["all_completed"] is True and last_res["next_level"] is None
    assert [st["state"] for st in p["stages"]] == ["completed"] * 4
    assert isinstance(start_lvl(s, "grove-os"), dict), "completed levels stay open for replay"
    assert main.get_progress(s)["total_xp"] > 0


# ---------------------------------------------------------------- migrations

def test_migrations_create_and_upgrade_schema():
    path = os.path.join(_tmpdir, "fresh.db")
    original = attempt_store.DB_PATH
    attempt_store.DB_PATH = path
    try:
        assert attempt_store.init_db() == len(attempt_store.MIGRATIONS)
        assert attempt_store.init_db() == len(attempt_store.MIGRATIONS), "re-running is a no-op"

        # A database from the earlier version: attempts table exists, user_version is 0.
        legacy = os.path.join(_tmpdir, "legacy.db")
        conn = sqlite3.connect(legacy)
        conn.executescript(attempt_store.MIGRATIONS[0])
        conn.execute("INSERT INTO attempts (student_id, session_id, question_id, topic, selected_answer, is_correct, "
                     "attempt_no, response_time_ms, submitted_at) VALUES ('a','s','q','os','x',1,1,10,'t')")
        conn.commit()
        conn.close()
        attempt_store.DB_PATH = legacy
        assert attempt_store.init_db() == len(attempt_store.MIGRATIONS)
        assert len(attempt_store.fetch_student_attempts("a")) == 1, "existing rows survive the upgrade"
        assert attempt_store.fetch_student_attempts("a")[0]["options_shown"] is None, "v3 column added, old rows are NULL"
        assert attempt_store.load_session("missing") is None
        assert attempt_store.xp_already_awarded("a", "grove-os", "q") is False, "v4 tables exist"
    finally:
        attempt_store.DB_PATH = original


# ------------------------------------------------- guesswork detection (evidence + rules)

def _a(q, n, ok, ms, hint=False, session="s1", mode="mcq", k=4, topic=None, valid=True):
    return {"question_id": q, "attempt_no": n, "correct": ok, "time_taken_ms": ms, "mode": mode,
            "n_options": k if mode == "mcq" else None, "session_id": session, "topic": topic,
            "hint_used": hint, "timing_valid": valid}


def _signal(res, sid):
    return next(s for s in res["risk"]["signals"] if s["id"] == sid)


def test_consistently_accurate_answers_are_low_risk():
    res = analyze_attempts([_a(f"q{i}", 1, True, 5000) for i in range(6)])
    assert res["status"] == "ok" and res["risk"]["level"] == "low"
    assert res["summary"]["level"] == "low" and "thoughtful" in res["summary"]["observation"]


def test_fast_repeated_incorrect_first_attempts_raise_risk_with_matching_explanation():
    atts = []
    for i in range(5):
        atts += [_a(f"q{i}", 1, False, 600), _a(f"q{i}", 2, False, 500), _a(f"q{i}", 3, True, 500)]
    res = analyze_attempts(atts)
    assert res["risk"]["level"] == "high"
    assert _signal(res, "repeated_rapid_incorrect")["points"] == 2
    assert _signal(res, "consistently_rapid_first_answers")["points"] == 1
    assert "very quickly" in res["summary"]["observation"] and "read the question" in res["summary"]["next_step"]


def test_slow_incorrect_answers_do_not_trigger_timing_signals():
    atts = []
    for i in range(6):
        atts += [_a(f"q{i}", 1, False, 12000), _a(f"q{i}", 2, True, 9000)]
    res = analyze_attempts(atts)
    assert res["risk"]["level"] != "low"
    assert _signal(res, "repeated_rapid_incorrect")["points"] == 0
    assert _signal(res, "consistently_rapid_first_answers")["points"] == 0
    assert "quickly" not in res["summary"]["observation"], "explanation must not mention signals that did not fire"


def test_corrected_answers_versus_unresolved_questions():
    corrected = [_a(f"q{i}", 1, False, 8000) for i in range(5)] + [_a(f"q{i}", 2, True, 8000) for i in range(5)]
    res = analyze_attempts(corrected)
    assert res["metrics"]["correction_rate_pct"] == 100.0 and res["metrics"]["unresolved_questions"] == 0
    assert _signal(res, "unresolved_after_repeated_misses")["points"] == 0

    abandoned = [_a(f"q{i}", 1, False, 8000) for i in range(5)] + [_a("q0", 2, True, 8000)]
    abandoned += [_a("q1", n, False, 8000) for n in (2, 3)]          # q1: three wrong tries, never solved
    res = analyze_attempts(abandoned)
    assert res["metrics"]["unresolved_questions"] == 4
    assert res["metrics"]["correction_rate_pct"] == 20.0
    assert _signal(res, "unresolved_after_repeated_misses")["points"] == 1
    assert "unsolved" in res["summary"]["observation"]


def test_hint_usage_is_never_penalised():
    good = [_a(f"q{i}", 1, True, 6000) for i in range(5)]
    hinted_misses = [_a(f"h{i}", 1, False, 3000, hint=True) for i in range(5)]   # asked for a hint first, then missed
    res = analyze_attempts(good + hinted_misses)
    assert res["risk"]["level"] == "low" and res["metrics"]["hinted_questions"] == 5
    assert res["metrics"]["first_attempt_accuracy_pct"] == 100.0, "hinted questions leave the accuracy signals alone"
    # Only hinted evidence is not enough to judge anything -- and certainly not a high risk.
    only_hinted = analyze_attempts(hinted_misses + [_a(f"h{i}", 2, True, 500, hint=True) for i in range(5)])
    assert only_hinted["status"] == "insufficient_data" and only_hinted["hinted_questions"] == 5
    # A miss made BEFORE the hint still counts, but the hinted retry is not "rapid".
    before = []
    for i in range(5):
        before += [_a(f"q{i}", 1, False, 9000), _a(f"q{i}", 2, False, 200, hint=True), _a(f"q{i}", 3, True, 200, hint=True)]
    res = analyze_attempts(before)
    assert res["metrics"]["first_attempt_accuracy_pct"] == 0.0
    assert _signal(res, "repeated_rapid_incorrect")["points"] == 0


def test_hint_wait_is_excluded_from_response_time_and_consumed_once():
    s = new_student()
    r = start(s)
    sid, qid = r["session_id"], r["id"]
    session = quest_session.SESSIONS[sid]
    attempt_store.record_hint_event(session_id=sid, student_id=s, question_id=qid, duration_ms=4000, ok=True)
    session.served_at = time.time() - 6                       # 6 s since the question appeared, 4 s of it in the hint
    assert submit(sid, s, qid, wrongs_of(qid)[0])["correct"] is False
    first = attempt_rows(sid)[0]
    assert first["hint_used"] == 1 and first["hint_wait_ms"] == 4000
    assert 1500 <= first["response_time_ms"] <= 3500, first["response_time_ms"]
    assert submit(sid, s, qid, right_of(qid))["correct"] is True      # quick retry: nothing left to subtract
    second = attempt_rows(sid)[1]
    assert second["hint_used"] == 1 and second["hint_wait_ms"] == 0 and second["response_time_ms"] < 1500
    view = quest_session.attempt_view(first)
    assert view["hint_used"] is True and view["session_id"] == sid and view["topic"] == "os"


def test_failed_hint_request_time_is_excluded_but_not_counted_as_a_hint():
    s = new_student()
    r = start(s)
    sid, qid = r["session_id"], r["id"]
    attempt_store.record_hint_event(session_id=sid, student_id=s, question_id=qid, duration_ms=3000, ok=False)
    quest_session.SESSIONS[sid].served_at = time.time() - 4
    submit(sid, s, qid, right_of(qid))
    row = attempt_rows(sid)[0]
    assert row["hint_used"] == 0 and row["hint_wait_ms"] == 3000 and row["response_time_ms"] < 2500


def test_ai_hint_endpoint_logs_a_server_measured_hint_event():
    s = new_student()
    r = start(s)
    sid, qid = r["session_id"], r["id"]
    real = main.ai_hint.generate_hint
    main.ai_hint.generate_hint = lambda q: (time.sleep(0.05), "Think about the core idea.")[1]
    try:
        out = main.ai_hint_for_question(main.HintRequest(session_id=sid, student_id=s, question_id=qid))
    finally:
        main.ai_hint.generate_hint = real
    assert out["hint"]
    wait, used = attempt_store.pending_hint_info(sid, qid)
    assert used is True and wait >= 40
    main.ai_hint.generate_hint = lambda q: (_ for _ in ()).throw(main.ai_hint.HintError("nope"))
    try:
        try:
            main.ai_hint_for_question(main.HintRequest(session_id=sid, student_id=s, question_id=qid))
        except HTTPException:
            pass
    finally:
        main.ai_hint.generate_hint = real
    conn = sqlite3.connect(attempt_store.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM hint_events WHERE session_id = ?", (sid,)).fetchone()[0] == 2
    conn.close()


def test_two_question_quest_has_insufficient_evidence():
    res = analyze_attempts([_a("q1", 1, False, 300), _a("q1", 2, True, 300), _a("q2", 1, False, 300), _a("q2", 2, True, 300)])
    assert res["status"] == "insufficient_data" and "risk" not in res
    assert res["summary"]["level"] == "insufficient_data" and "Not enough data" in res["summary"]["headline"]


def test_chance_baseline_depends_on_the_number_of_options():
    def run(k):
        atts = [_a(f"q{i}", 1, i < 3, 6000, k=k) for i in range(4)] + [_a("q4", 1, True, 6000, mode="short_answer")]
        return analyze_attempts(atts)
    two, four = run(2), run(4)
    assert two["chance_baseline"]["expected_correct_by_guessing"] == 2.0
    assert four["chance_baseline"]["expected_correct_by_guessing"] == 1.0
    assert two["chance_baseline"]["consistent_with_chance"] is True      # 3/4 right is ordinary for coin flips
    assert four["chance_baseline"]["consistent_with_chance"] is False    # ...but unlikely for 1-in-4 guesses


def test_missing_or_untrusted_timing_never_counts_as_rapid():
    atts = []
    for i in range(5):
        atts += [_a(f"q{i}", 1, False, None), _a(f"q{i}", 2, False, 50, valid=False), _a(f"q{i}", 3, True, None)]
    res = analyze_attempts(atts)
    assert res["status"] == "ok"
    assert _signal(res, "repeated_rapid_incorrect")["points"] == 0
    assert _signal(res, "consistently_rapid_first_answers")["points"] == 0
    assert res["metrics"]["response_time"]["timed_first_answers"] == 0


def test_duplicate_submission_is_rejected_and_not_double_counted():
    s = new_student()
    r = start(s)
    sid, qid = r["session_id"], r["id"]
    assert submit(sid, s, qid, wrongs_of(qid)[0])["correct"] is False
    try:
        attempt_store.record_attempt(student_id=s, session_id=sid, question_id=qid, topic="os", selected_answer="x",
                                     is_correct=False, attempt_no=1, response_time_ms=10)
        raise AssertionError("duplicate attempt number must be rejected")
    except sqlite3.IntegrityError:
        pass
    assert len(attempt_rows(sid)) == 1


def test_reload_mid_question_marks_the_next_time_untrusted_only_once():
    s = new_student()
    r = start(s)
    sid, qid = r["session_id"], r["id"]
    quest_session.SESSIONS.clear()                                   # page refresh / backend restart
    assert submit(sid, s, qid, wrongs_of(qid)[0])["correct"] is False
    assert submit(sid, s, qid, right_of(qid))["correct"] is True
    rows = attempt_rows(sid)
    assert [r_["timing_valid"] for r_ in rows] == [0, 1]
    assert quest_session.attempt_view(rows[0])["timing_valid"] is False


def test_aggregation_keeps_separate_quests_separate():
    atts = []
    for session in ("s1", "s2"):
        for i in range(3):                                           # same question ids in both quests
            atts += [_a(f"q{i}", 1, False, 7000, session=session, topic="os"),
                     _a(f"q{i}", 2, True, 7000, session=session, topic="os")]
    merged = analyze_attempts(atts)
    assert merged["status"] == "ok" and merged["metrics"]["evaluated_questions"] == 6
    assert analyze_attempts([a for a in atts if a["session_id"] == "s1"])["status"] == "insufficient_data"
    assert [t["topic"] for t in merged["topic_patterns"]] == ["os"]  # 6 os questions >= the topic threshold


def test_topic_patterns_need_enough_evidence():
    atts = [_a(f"o{i}", 1, False, 7000, topic="os") for i in range(5)] + [_a(f"d{i}", 1, True, 7000, topic="dsa") for i in range(2)]
    res = analyze_attempts(atts)
    topics = {t["topic"]: t for t in res["topic_patterns"]}
    assert "dsa" not in topics, "two questions are not enough to judge a topic"
    assert topics["os"]["needs_practice"] is True


def test_dashboard_reports_summary_and_overall_analysis():
    s = new_student()
    sid, _ = play_quest(s, first_try_wrong=0)
    d = main.get_dashboard(sid, s)
    assert d["analysis"]["summary"]["next_step"] and d["analysis_overall"]["summary"]["headline"]
    assert d["analysis_overall"]["status"] == "ok"


def test_summary_text_only_mentions_fired_signals():
    from guess_analysis import _OBSERVATIONS
    atts = []
    for i in range(5):
        atts += [_a(f"q{i}", 1, False, 6000), _a(f"q{i}", 2, True, 6000)]
    res = analyze_attempts(atts)
    fired = {s["id"] for s in res["risk"]["signals"] if s["triggered"]}
    for sid, phrase in _OBSERVATIONS.items():
        assert (phrase in res["summary"]["observation"]) == (sid in fired), sid


# ------------------------------------------------- minimum of 5 unique questions per level

def _all_levels():
    return [lv for st in main.CATALOG["stages"] for lv in st["stages"]] if False else \
        [lv for st in main.CATALOG["stages"] for lv in st["levels"]]


def test_every_level_has_at_least_five_unique_questions():
    from levels_config import MIN_LEVEL_QUESTIONS
    assert MIN_LEVEL_QUESTIONS == 5
    levels = _all_levels()
    assert len(levels) == 16
    for lv in levels:
        ids = lv["question_ids"]
        assert len(ids) >= 5 and lv["question_count"] == len(ids) and lv["meets_minimum"], lv["id"]
        assert len(set(ids)) == len(ids), f"{lv['id']} repeats a question"
        prompts = [progression._prompt_key(main.QUESTIONS_BY_ID[i]) for i in ids]
        assert len(set(prompts)) == len(prompts), f"{lv['id']} repeats a prompt"
        assert all(main.QUESTIONS_BY_ID[i]["courseId"] == lv["course_id"] for i in ids), "subject must not change"


def test_levels_get_harder_from_stage_to_stage():
    for course in ("os", "dbms", "dsa", "lang"):
        avg = []
        for stage in ("grove", "caverns", "trials", "boss"):
            ids = main.CATALOG["levels"][f"{stage}-{course}"]["question_ids"]
            tiers = [main.QUESTIONS_BY_ID[i]["tier"] for i in ids]
            assert tiers == sorted(tiers), "questions inside a level go easiest first"
            avg.append(sum(tiers) / len(tiers))
        assert avg == sorted(avg) and avg[0] < avg[-1], (course, avg)


def test_a_started_level_serves_all_its_questions_once():
    s = new_student()
    expected = main.CATALOG["levels"]["grove-dbms"]["question_ids"]
    assert isinstance(start_lvl(s, "grove-os"), int) is False
    solve_level(s, "grove-os")
    r = start_lvl(s, "grove-dbms")
    assert r["quest_length"] == len(expected) >= 5 and r["level_info"]["question_count"] == len(expected)
    seen, qid = [], r["id"]
    while qid:
        seen.append(qid)
        res = submit(r["session_id"], s, qid, right_answer(qid))
        qid = res["next_question"]["id"] if res["next_question"] else None
    assert seen == expected


def test_backend_refuses_a_level_session_with_too_few_or_repeated_questions():
    for ids in (["os-mcq-1", "os-mcq-2"], ["os-mcq-1"] * 5, ["os-mcq-1", "os-mcq-2", "os-mcq-3", "os-mcq-4"]):
        try:
            quest_session.create_session("os", "mcq", 0, "someone", len(ids), level_id="grove-os", question_ids=ids)
            raise AssertionError(f"{ids} should have been refused")
        except quest_session.SessionError as e:
            assert e.status_code == 503


def test_duplicate_questions_do_not_count_towards_the_minimum():
    level = {"id": "x", "course_id": "os", "selector": {"max_questions": 5, "pools": [
        {"mode": "mcq", "tier": 1, "count": 5}]}}
    bank = [{"id": f"a{i}", "courseId": "os", "mode": "mcq", "tier": 1, "prompt": "Same question?"} for i in range(3)]
    bank += [{"id": "b", "courseId": "os", "mode": "mcq", "tier": 1, "prompt": "  same QUESTION ? "},
             {"id": "c", "courseId": "os", "mode": "mcq", "tier": 1, "prompt": "A different one"}]
    assert progression.resolve_question_ids(level, bank) == ["a0", "c"]


class _FakeBank:
    """Takes the dsa tier-1 multiple-choice questions out of the bank (so grove-dsa is short) and
    restores everything afterwards, including any questions the test caused to be generated."""

    def __enter__(self):
        self.all = list(main.ALL_QUESTIONS)
        self.gen_path = level_fill.GENERATED_PATH
        level_fill.GENERATED_PATH = os.path.join(_tmpdir, f"generated-{time.time_ns()}.json")
        main.ALL_QUESTIONS[:] = [q for q in self.all if not (q["courseId"] == "dsa" and q["mode"] == "mcq" and q["tier"] == 1)]
        main.rebuild_catalog()
        return self

    def __exit__(self, *exc):
        main.ALL_QUESTIONS[:] = self.all
        for key in [k for k, q in list(main.QUESTIONS_BY_ID.items()) if q.get("generated")]:
            q = main.QUESTIONS_BY_ID.pop(key)
            main.QUESTIONS_BY_COURSE_MODE[(q["courseId"], q["mode"])].remove(q)
            main.QUESTIONS_BY_COURSE_MODE_TIER[(q["courseId"], q["mode"])][q["tier"]].remove(q)
        level_fill.GENERATED_PATH = self.gen_path
        main.rebuild_catalog()


def _model_output(*prompts):
    return json.dumps({"questions": [
        {"prompt": p, "options": [f"{p} A", f"{p} B", f"{p} C", f"{p} D"], "correct_answer": f"{p} A",
         "explanation": "Because."} for p in prompts]})


def _unlock_grove_dsa(student):
    for lv in ("grove-os", "grove-dbms"):
        solve_level(student, lv)


def test_a_short_level_is_topped_up_by_generation_before_it_starts():
    s = new_student()
    _unlock_grove_dsa(s)
    with _FakeBank():
        assert main.CATALOG["levels"]["grove-dsa"]["meets_minimum"] is False
        existing = next(q["prompt"] for q in main.ALL_QUESTIONS if q["courseId"] == "dsa")
        calls = []

        def fake(prompt, system=None, timeout=None, **kw):
            calls.append(prompt)
            return _model_output(existing, "What does a stack do?", "Name a queue property.", "Define a heap.")

        real = level_fill.ollama_client.generate
        level_fill.ollama_client.generate = fake
        try:
            r = start_lvl(s, "grove-dsa")
        finally:
            level_fill.ollama_client.generate = real
        assert isinstance(r, dict) and r["quest_length"] == 5 and len(calls) == 1
        ids = main.CATALOG["levels"]["grove-dsa"]["question_ids"]
        assert len(set(ids)) == 5 and sum(1 for i in ids if i.startswith("gen-dsa-mcq-")) == 2
        assert existing not in [main.QUESTIONS_BY_ID[i]["prompt"] for i in ids if i.startswith("gen-")], "duplicates dropped"
        saved = level_fill.load_generated()
        assert {q["id"] for q in saved} >= {i for i in ids if i.startswith("gen-")}, "generated questions are saved"
        # "Previously saved questions": after a restart the saved ones come back and nothing is generated again.
        gen_ids = [i for i in ids if i.startswith("gen-")]
        for gid in gen_ids:
            q = main.QUESTIONS_BY_ID.pop(gid)
            main.ALL_QUESTIONS.remove(q)
            main.QUESTIONS_BY_COURSE_MODE[("dsa", "mcq")].remove(q)
            main.QUESTIONS_BY_COURSE_MODE_TIER[("dsa", "mcq")][1].remove(q)
        main.register_questions(level_fill.load_generated())
        main.rebuild_catalog()
        assert main.CATALOG["levels"]["grove-dsa"]["question_ids"] == ids
        assert main.CATALOG["levels"]["grove-dsa"]["meets_minimum"]


def test_failed_generation_means_the_level_does_not_start():
    s = new_student()
    _unlock_grove_dsa(s)
    real = level_fill.ollama_client.generate
    cases = {
        "ollama down": lambda *a, **k: (_ for _ in ()).throw(level_fill.ollama_client.OllamaUnavailable("down")),
        "not json": lambda *a, **k: "I am not JSON",
        "only duplicates": lambda *a, **k: _model_output(next(q["prompt"] for q in main.ALL_QUESTIONS if q["courseId"] == "dsa")),
        "malformed options": lambda *a, **k: json.dumps({"questions": [{"prompt": "Q?", "options": ["a"], "correct_answer": "z"}]}),
    }
    for name, fake in cases.items():
        with _FakeBank():
            level_fill.ollama_client.generate = fake
            try:
                r = start_lvl(s, "grove-dsa")
            finally:
                level_fill.ollama_client.generate = real
            assert r == 503, (name, r)
            assert main.CATALOG["levels"]["grove-dsa"]["meets_minimum"] is False, name
            assert level_fill.load_generated() == [], name
    conn = sqlite3.connect(attempt_store.DB_PATH)
    assert conn.execute("SELECT COUNT(*) FROM sessions WHERE student_id = ? AND level_id = 'grove-dsa'", (s,)).fetchone()[0] == 0
    conn.close()


def test_old_short_level_sessions_are_not_resumed():
    s = new_student()
    old = quest_session.QuestSession("os", "mcq", 0, s, 2, level_id="grove-os", question_ids=["os-mcq-1", "os-mcq-2"])
    old.serve("os-mcq-1")
    attempt_store.save_session(old.to_state())
    assert "grove-os" not in attempt_store.open_level_ids(s)
    r = start_lvl(s, "grove-os")
    assert r["resumed"] is False and r["quest_length"] == 5 and r["session_id"] != old.id


def test_completion_results_report_the_real_question_count():
    s = new_student()
    sid, _ = solve_level(s, "grove-os")
    assert main.get_level_results("grove-os", s, sid)["questions"] == 5
    assert main.get_level_results("grove-os", s, sid)["level"]["question_count"] == 5


def test_guesswork_needs_five_different_questions_and_a_finished_quest():
    five = analyze_attempts([_a(f"q{i}", 1, i % 2 == 0, 6000) for i in range(5)])
    assert five["status"] == "ok" and five["metrics"]["attempted_questions"] == 5
    four = analyze_attempts([_a(f"q{i}", 1, True, 6000) for i in range(4)])
    assert four["status"] == "insufficient_data" and "5 different questions" in four["reason"]
    # The same question five times is one question, not five.
    repeated = analyze_attempts([_a("q1", n, n == 5, 6000) for n in range(1, 6)])
    assert repeated["status"] == "insufficient_data"
    # Five attempted but too many answered after a hint: not enough left to judge.
    mostly_hinted = analyze_attempts([_a(f"q{i}", 1, False, 6000, hint=i < 3) for i in range(5)])
    assert mostly_hinted["status"] == "insufficient_data" and "hint" in mostly_hinted["reason"]
    # End to end: unfinished quest -> wait; finished 5-question level -> an estimate.
    s = new_student()
    r = start_lvl(s, "grove-os")
    submit(r["session_id"], s, r["id"], right_answer(r["id"]))
    unfinished = main.get_dashboard(r["session_id"], s)["analysis"]
    assert unfinished["status"] == "insufficient_data" and "Finish the quest" in unfinished["reason"]
    s = new_student()                       # a fresh hero, so the run above is not resumed
    sid, _ = solve_level(s, "grove-os")
    done = main.get_dashboard(sid, s)["analysis"]
    assert done["status"] == "ok" and done["metrics"]["attempted_questions"] == 5


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS  {name}")
        except Exception as e:  # report every failure, then exit non-zero
            failed += 1
            print(f"FAIL  {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} quest-flow tests passed")
    raise SystemExit(1 if failed else 0)
