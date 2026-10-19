"""
Guessing-pattern analysis -- an explainable, rule-based baseline.

Goal: estimate whether a completed test's answer pattern is CONSISTENT WITH
guessing. It cannot know a student's intent: repeated mistakes are just as
likely to be a real knowledge gap, and fast answers are just as likely to be
a confident student. So the output keeps two things strictly apart:

  * "metrics"  -- observed facts computed directly from the attempt log.
  * "risk"     -- an INFERRED indicator (low / moderate / high) produced by
                  the documented points formula below, with every signal and
                  the rule that fired listed so it can be audited.

No ML/LLM: just counts, medians, and one exact binomial calculation.

Scoring formula (all thresholds live in CONFIG):
  Accuracy-based signals (can stand on their own):
    low_first_attempt_accuracy  1 pt if first-attempt accuracy < 60%, 2 pts if < 40%
    high_retry_rate             1 pt if retry rate >= 60%
    chance_consistent_mcq       2 pts if first-attempt MCQ results are a typical
                                outcome of pure guessing (see below)
  Timing signal (only counts in combination, never on its own):
    repeated_rapid_incorrect    1 pt if one question had 2+ consecutive rapid
                                wrong submissions, 2 pts if 2+ questions did.
                                Added ONLY if an accuracy-based signal also fired.
  Level:  score <= 1 low | 2-3 moderate | >= 4 high.
  "high" additionally requires at least two different signals to have fired;
  otherwise it is capped at "moderate".

Chance baseline: for a multiple-choice question with k options a random
FIRST attempt succeeds with probability 1/k (25% for 4 options). k is the
number of options actually selectable at that attempt, so a student who
asked for a 50/50 hint is compared against 1-in-2, not 1-in-4. We take the
questions' own k values, compute the exact probability of getting at least
the observed number right by guessing alone (Poisson-binomial), and call the
result "consistent with chance" when that probability is >= chance_p_typical.
Only first attempts are used: after a miss the hint crosses out options, so
later attempts are not independent 1/k draws. Short-answer questions have no
meaningful chance baseline and are excluded from this signal entirely.
"""

from statistics import median
from typing import Optional

CONFIG = {
    "min_questions": 5,                   # fewer solved questions -> insufficient_data
    "min_mcq_for_chance": 4,              # fewer first-attempt MCQs -> chance signal not evaluated
    "chance_p_typical": 0.30,             # P(guessing does at least this well) >= this => "consistent with chance"
    "low_first_attempt_moderate": 60.0,   # percent
    "low_first_attempt_severe": 40.0,
    "high_retry_rate": 60.0,              # percent
    # Plausible minimum time (ms) to read and answer, by format. Retries are
    # judged more leniently because the student has just read a hint.
    "rapid_ms_first": {"mcq": 2000, "short_answer": 5000},
    "rapid_ms_retry": {"mcq": 1000, "short_answer": 3000},
    "rapid_streak_len": 2,                # consecutive rapid wrong submissions on one question
    "moderate_score": 2,
    "high_score": 4,
}

MAX_SCORE = 7

LIMITATIONS = [
    "This is a pattern estimate, not a judgement of intent: repeated mistakes often reflect a real knowledge gap.",
    "Fast answers are not evidence of guessing on their own; they only count alongside accuracy-based signals.",
    "The chance baseline applies to first attempts on multiple-choice questions only, and a short test is a small sample.",
    "Response time is measured by the server from when a question (or a retry) was shown until the answer arrived, "
    "so it includes any time spent reading hints.",
]


def _pct(num: int, den: int) -> Optional[float]:
    return round(100 * num / den, 1) if den else None


def _p_at_least(probs: list, k: int) -> float:
    """P(sum of independent Bernoulli(probs) >= k) via dynamic programming."""
    dist = [1.0]
    for p in probs:
        nxt = [0.0] * (len(dist) + 1)
        for i, d in enumerate(dist):
            nxt[i] += d * (1 - p)
            nxt[i + 1] += d * p
        dist = nxt
    return sum(dist[k:])


def analyze_attempts(attempts: list, config: dict = CONFIG) -> dict:
    """`attempts`: ordered dicts with question_id, correct, attempt_no,
    time_taken_ms, mode ("mcq"/"short_answer") and n_options (int or None)."""
    by_q: dict = {}
    for a in attempts:
        by_q.setdefault(a["question_id"], []).append(a)
    questions = [qa for qa in by_q.values() if any(x["correct"] for x in qa)]  # solved
    n = len(questions)

    if n < config["min_questions"]:
        return {
            "status": "insufficient_data",
            "reason": f"A guessing-pattern estimate needs at least {config['min_questions']} solved questions; this test has {n}.",
            "solved_questions": n,
            "limitations": LIMITATIONS,
        }

    first_correct = sum(1 for qa in questions if qa[0]["correct"])
    retried = [qa for qa in questions if not qa[0]["correct"]]
    total_submissions = sum(len(qa) for qa in questions)

    # ---- E. response-time analysis (observed) ----
    def is_rapid(a: dict) -> bool:
        table = config["rapid_ms_first"] if a["attempt_no"] == 1 else config["rapid_ms_retry"]
        return a["time_taken_ms"] < table.get(a["mode"], 0)

    rapid_wrong_questions = 0
    rapid_wrong_submissions = 0
    for qa in questions:
        run = best = 0
        for a in qa:
            if not a["correct"] and is_rapid(a):
                rapid_wrong_submissions += 1
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best >= config["rapid_streak_len"]:
            rapid_wrong_questions += 1

    times_by_format: dict = {}
    for mode in ("mcq", "short_answer"):
        firsts = [qa[0]["time_taken_ms"] for qa in questions if qa[0]["mode"] == mode]
        if firsts:
            times_by_format[mode] = {
                "questions": len(firsts),
                "median_first_attempt_ms": int(median(firsts)),
                "rapid_threshold_ms": config["rapid_ms_first"][mode],
            }

    metrics = {
        "solved_questions": n,
        "total_submissions": total_submissions,
        "first_attempt_accuracy_pct": _pct(first_correct, n),
        "retry_rate_pct": _pct(len(retried), n),
        "avg_attempts_per_question": round(total_submissions / n, 2),
        # Of the questions missed first, the share eventually solved. Within a
        # completed quest this is always 100% (every question must be solved).
        "correction_rate_pct": _pct(len(retried), len(retried)) if retried else None,
        "correction_rate_note": None if retried else "Not applicable: no question was answered incorrectly first.",
        "response_time": {
            "by_format": times_by_format,
            "rapid_wrong_submissions": rapid_wrong_submissions,
            "questions_with_repeated_rapid_wrong": rapid_wrong_questions,
        },
    }

    # ---- chance comparison (MCQ first attempts only) ----
    mcq_first = [qa[0] for qa in questions if qa[0]["mode"] == "mcq" and (qa[0].get("n_options") or 0) >= 2]
    chance = {"applicable": len(mcq_first) >= config["min_mcq_for_chance"], "mcq_questions": len(mcq_first)}
    if chance["applicable"]:
        probs = [1 / a["n_options"] for a in mcq_first]
        observed = sum(1 for a in mcq_first if a["correct"])
        p_typical = _p_at_least(probs, observed)
        chance.update({
            "expected_correct_by_guessing": round(sum(probs), 1),
            "observed_correct": observed,
            "chance_of_doing_at_least_this_well_by_guessing_pct": round(100 * p_typical),
            "consistent_with_chance": p_typical >= config["chance_p_typical"],
        })
    else:
        chance["note"] = (f"Not evaluated: needs at least {config['min_mcq_for_chance']} first-attempt "
                          "multiple-choice questions.")

    # ---- F. risk indicator (inferred) ----
    signals = []

    def add(sid, label, points, rule, kind):
        signals.append({"id": sid, "label": label, "points": points, "triggered": points > 0, "rule": rule, "kind": kind})

    fa = metrics["first_attempt_accuracy_pct"]
    pts = 2 if fa < config["low_first_attempt_severe"] else 1 if fa < config["low_first_attempt_moderate"] else 0
    add("low_first_attempt_accuracy", f"First-attempt accuracy was {fa:.0f}%", pts,
        f"below {config['low_first_attempt_moderate']:.0f}% = 1 pt, below {config['low_first_attempt_severe']:.0f}% = 2 pts",
        "accuracy")

    rr = metrics["retry_rate_pct"]
    add("high_retry_rate", f"{rr:.0f}% of questions needed a retry", 1 if rr >= config["high_retry_rate"] else 0,
        f"{config['high_retry_rate']:.0f}% or more of questions needing a retry = 1 pt", "accuracy")

    add("chance_consistent_mcq",
        "First-attempt multiple-choice results are typical of random picking" if chance.get("consistent_with_chance")
        else "First-attempt multiple-choice results are better than random picking" if chance["applicable"]
        else "Chance comparison not evaluated (too few multiple-choice questions)",
        2 if chance.get("consistent_with_chance") else 0,
        f"random picking does at least this well {round(100 * config['chance_p_typical'])}% of the time or more = 2 pts",
        "accuracy")

    accuracy_points = sum(s["points"] for s in signals)
    rq = rapid_wrong_questions
    timing_pts = (2 if rq >= 2 else 1 if rq == 1 else 0) if accuracy_points > 0 else 0
    add("repeated_rapid_incorrect",
        f"{rq} question(s) had repeated very quick wrong submissions",
        timing_pts, "1 pt for one question, 2 pts for two or more; only counted when an accuracy signal also fired",
        "timing")

    score = sum(s["points"] for s in signals)
    fired = sum(1 for s in signals if s["triggered"])
    level = "high" if score >= config["high_score"] else "moderate" if score >= config["moderate_score"] else "low"
    if level == "high" and fired < 2:
        level = "moderate"

    return {
        "status": "ok",
        "metrics": metrics,                       # observed
        "chance_baseline": chance,                # observed vs. theoretical
        "risk": {                                 # inferred
            "level": level,
            "score": score,
            "max_score": MAX_SCORE,
            "signals": signals,
            "meaning": "How consistent the answer pattern is with guessing -- not proof of it. "
                       "Repeated mistakes may simply show a knowledge gap.",
        },
        "limitations": LIMITATIONS,
    }
