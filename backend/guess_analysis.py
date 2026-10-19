"""
Guessing-pattern analysis -- an explainable, rule-based baseline.

Goal: estimate whether an answer pattern is CONSISTENT WITH guessing. It cannot
know a student's intent: repeated mistakes are just as likely to be a real
knowledge gap, and fast answers are just as likely to be a confident student.
So the output keeps two things strictly apart:

  * "metrics"  -- observed facts computed directly from the attempt log.
  * "risk"     -- an INFERRED indicator (low / moderate / high) produced by
                  the documented points formula below, with every signal and
                  the rule that fired listed so it can be audited.

No ML/LLM: just counts, medians, and one exact binomial calculation. The score
is a heuristic, NOT a calibrated probability.

Scoring formula (all thresholds live in CONFIG):
  Accuracy-based signals (can stand on their own):
    low_first_attempt_accuracy        1 pt if first-attempt accuracy < 60%, 2 pts if < 40%
    high_retry_rate                   1 pt if retry rate >= 60%
    chance_consistent_mcq             2 pts if first-attempt MCQ results are a typical
                                      outcome of pure guessing (see below)
    unresolved_after_repeated_misses  1 pt if a question stayed unsolved after 3+ wrong tries
  Timing signals (only count in combination, never on their own):
    repeated_rapid_incorrect          1 pt if one question had 2+ consecutive rapid wrong
                                      submissions, 2 pts if 2+ questions did.
    consistently_rapid_first_answers  1 pt if 60%+ of first answers (and at least 3) were rapid.
                                      Both are added ONLY if an accuracy-based signal also fired.
  Level:  score <= 1 low | 2-3 moderate | >= 4 high.
  "high" additionally requires at least two different signals to have fired;
  otherwise it is capped at "moderate".

Chance baseline: for a multiple-choice question with k options a random
FIRST attempt succeeds with probability 1/k (25% for 4 options). k is the
number of options actually selectable at that attempt. We take the questions'
own k values, compute the exact probability of getting at least the observed
number right by guessing alone (Poisson-binomial), and call the result
"consistent with chance" when that probability is >= chance_p_typical. Only
first attempts are used: after a miss, later attempts are not independent 1/k
draws. Short-answer questions have no meaningful chance baseline and are
excluded from this signal entirely.

Evidence rules added with the AI hint system:
  * Hints are neutral. Asking for an AI hint is treated as active learning, so a
    question whose FIRST attempt came after a hint is left out of every accuracy,
    retry, chance and speed signal (it only appears in metrics as hinted_questions).
    A miss made BEFORE asking for a hint still counts.
  * Time spent waiting for the hint is removed from response times by the server
    (see quest_session.apply_answer); attempts whose clock restarted mid-question
    (timing_valid false) or that have no time are ignored by the timing signals.
  * Questions are keyed by (session, question), so attempts from several quests
    can be analysed together without merging two plays of the same question.
  * Unresolved questions (never solved) count: repeated misses with no resolution
    are a signal, and the correction rate is the share of first-try misses solved later.
  * Topic patterns are reported only for topics with enough evaluated questions.
Every result carries a plain-language `summary` built only from the signals that fired.
"""

from statistics import median
from typing import Optional

from levels_config import MIN_LEVEL_QUESTIONS

CONFIG = {
    "min_questions": MIN_LEVEL_QUESTIONS,  # fewer DIFFERENT questions attempted -> insufficient_data (same minimum a level must have)
    "min_evaluated": 3,                   # ...and at least this many of them answered without a hint first
    "min_mcq_for_chance": 4,              # fewer first-attempt MCQs -> chance signal not evaluated
    "chance_p_typical": 0.30,             # P(guessing does at least this well) >= this => "consistent with chance"
    "low_first_attempt_moderate": 60.0,   # percent
    "low_first_attempt_severe": 40.0,
    "high_retry_rate": 60.0,              # percent
    # Plausible minimum time (ms) to read and answer, by format. Retries are
    # judged more leniently because the student has just seen feedback.
    "rapid_ms_first": {"mcq": 2000, "short_answer": 5000},
    "rapid_ms_retry": {"mcq": 1000, "short_answer": 3000},
    "rapid_streak_len": 2,                # consecutive rapid wrong submissions on one question
    "rapid_first_share": 0.6,             # share of first answers that are rapid => "uniformly quick" pattern
    "rapid_first_min": 3,                 # ...and at least this many rapid first answers
    "unresolved_min_attempts": 3,         # wrong attempts on a never-solved question that count as "unresolved"
    "topic_min_questions": 4,             # evaluated questions needed before a topic is judged on its own
    "moderate_score": 2,
    "high_score": 4,
}

MAX_SCORE = 9

LIMITATIONS = [
    "This is a pattern estimate, not a judgement of intent: repeated mistakes often reflect a real knowledge gap.",
    "Fast answers are not evidence of guessing on their own; they only count alongside accuracy-based signals.",
    "The chance baseline applies to first attempts on multiple-choice questions only, and a short test is a small sample.",
    "Response time is measured by the server from when a question (or a retry) was shown until the answer arrived, "
    "minus time spent waiting for an AI hint.",
    "The score is a rule-of-thumb heuristic, not a calibrated probability; it has not been validated against real data.",
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


def _usable_time(a: dict) -> bool:
    return a.get("time_taken_ms") is not None and a.get("timing_valid", True)


def _group_questions(attempts: list) -> list:
    """Attempt lists per (session, question), each ordered by attempt number."""
    by_q: dict = {}
    for a in attempts:
        by_q.setdefault((a.get("session_id"), a["question_id"]), []).append(a)
    return [sorted(qa, key=lambda x: x.get("attempt_no", 0)) for qa in by_q.values()]


def analyze_attempts(attempts: list, config: dict = CONFIG) -> dict:
    """`attempts`: dicts with question_id, correct, attempt_no, time_taken_ms, mode
    ("mcq"/"short_answer") and n_options (int or None); optionally session_id, topic,
    hint_used and timing_valid. May span several quests."""
    all_questions = _group_questions(attempts)
    hinted = [qa for qa in all_questions if qa[0].get("hint_used")]
    questions = [qa for qa in all_questions if not qa[0].get("hint_used")]   # evidence we can judge
    n = len(questions)
    attempted = len(all_questions)

    if attempted < config["min_questions"] or n < config["min_evaluated"]:
        if attempted < config["min_questions"]:
            reason = (f"A guessing-pattern estimate needs at least {config['min_questions']} different questions "
                      f"answered; this quest has {attempted}.")
        else:
            reason = (f"Too many of the {attempted} questions were answered after asking for a hint, so there "
                      f"isn't enough left to judge (at least {config['min_evaluated']} are needed).")
        result = {
            "status": "insufficient_data",
            "reason": reason,
            "solved_questions": sum(1 for qa in questions if any(x["correct"] for x in qa)),
            "attempted_questions": attempted,
            "evaluated_questions": n,
            "hinted_questions": len(hinted),
            "limitations": LIMITATIONS,
        }
        result["summary"] = summarize(result)
        return result

    solved = [qa for qa in questions if any(x["correct"] for x in qa)]
    unsolved = [qa for qa in questions if not any(x["correct"] for x in qa)]
    first_correct = sum(1 for qa in questions if qa[0]["correct"])
    retried = [qa for qa in questions if not qa[0]["correct"]]
    corrected = [qa for qa in retried if any(x["correct"] for x in qa)]
    total_submissions = sum(len(qa) for qa in questions)

    # ---- response-time analysis (observed) ----
    def is_rapid(a: dict) -> bool:
        table = config["rapid_ms_first"] if a["attempt_no"] == 1 else config["rapid_ms_retry"]
        return _usable_time(a) and a["time_taken_ms"] < table.get(a["mode"], 0)

    rapid_wrong_questions = 0
    rapid_wrong_submissions = 0
    for qa in questions:
        run = best = 0
        for a in qa:
            if not a["correct"] and not a.get("hint_used") and is_rapid(a):
                rapid_wrong_submissions += 1
                run += 1
                best = max(best, run)
            else:
                run = 0
        if best >= config["rapid_streak_len"]:
            rapid_wrong_questions += 1

    timed_firsts = [qa[0] for qa in questions if _usable_time(qa[0])]
    rapid_firsts = sum(1 for a in timed_firsts if is_rapid(a))
    times_by_format: dict = {}
    for mode in ("mcq", "short_answer"):
        firsts = [a["time_taken_ms"] for a in timed_firsts if a["mode"] == mode]
        if firsts:
            times_by_format[mode] = {
                "questions": len(firsts),
                "median_first_attempt_ms": int(median(firsts)),
                "rapid_threshold_ms": config["rapid_ms_first"][mode],
            }

    metrics = {
        "solved_questions": len(solved),
        "attempted_questions": attempted,
        "evaluated_questions": n,
        "hinted_questions": len(hinted),
        "unresolved_questions": len(unsolved),
        "total_submissions": total_submissions,
        "first_attempt_accuracy_pct": _pct(first_correct, n),
        "retry_rate_pct": _pct(len(retried), n),
        "avg_attempts_per_question": round(total_submissions / n, 2),
        # Of the questions missed first, the share eventually solved.
        "correction_rate_pct": _pct(len(corrected), len(retried)) if retried else None,
        "correction_rate_note": None if retried else "Not applicable: no question was answered incorrectly first.",
        "response_time": {
            "by_format": times_by_format,
            "rapid_wrong_submissions": rapid_wrong_submissions,
            "questions_with_repeated_rapid_wrong": rapid_wrong_questions,
            "rapid_first_answers": rapid_firsts,
            "timed_first_answers": len(timed_firsts),
        },
    }

    # ---- chance comparison (MCQ first attempts only; k = options actually selectable) ----
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

    # ---- risk indicator (inferred) ----
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

    stuck = [qa for qa in unsolved if sum(1 for x in qa if not x["correct"]) >= config["unresolved_min_attempts"]]
    add("unresolved_after_repeated_misses",
        f"{len(stuck)} question(s) stayed unsolved after repeated attempts",
        1 if stuck else 0,
        f"a never-solved question with {config['unresolved_min_attempts']}+ wrong attempts = 1 pt", "accuracy")

    accuracy_points = sum(s["points"] for s in signals)

    rq = rapid_wrong_questions
    add("repeated_rapid_incorrect",
        f"{rq} question(s) had repeated very quick wrong submissions",
        (2 if rq >= 2 else 1 if rq == 1 else 0) if accuracy_points > 0 else 0,
        "1 pt for one question, 2 pts for two or more; only counted when an accuracy signal also fired",
        "timing")

    uniformly_quick = (
        rapid_firsts >= config["rapid_first_min"] and len(timed_firsts) > 0
        and rapid_firsts / len(timed_firsts) >= config["rapid_first_share"]
    )
    add("consistently_rapid_first_answers",
        f"{rapid_firsts} of {len(timed_firsts)} first answers were very quick",
        1 if uniformly_quick and accuracy_points > 0 else 0,
        f"{round(100 * config['rapid_first_share'])}% or more of first answers very quick = 1 pt; "
        "only counted when an accuracy signal also fired", "timing")

    score = sum(s["points"] for s in signals)
    fired = sum(1 for s in signals if s["triggered"])
    level = "high" if score >= config["high_score"] else "moderate" if score >= config["moderate_score"] else "low"
    if level == "high" and fired < 2:
        level = "moderate"

    # ---- topic-specific patterns: only where there is enough evidence ----
    by_topic: dict = {}
    for qa in questions:
        if qa[0].get("topic"):
            by_topic.setdefault(qa[0]["topic"], []).append(qa)
    topic_patterns = []
    for topic, qas in sorted(by_topic.items()):
        if len(qas) < config["topic_min_questions"]:
            continue
        acc = _pct(sum(1 for qa in qas if qa[0]["correct"]), len(qas))
        topic_patterns.append({"topic": topic, "questions": len(qas), "first_attempt_accuracy_pct": acc,
                               "needs_practice": acc < config["low_first_attempt_moderate"]})

    result = {
        "status": "ok",
        "metrics": metrics,                       # observed
        "chance_baseline": chance,                # observed vs. theoretical
        "topic_patterns": topic_patterns,
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
    result["summary"] = summarize(result)
    return result


def incomplete_result() -> dict:
    """Shown while a quest is still being played: the estimate is made once it is finished."""
    result = {
        "status": "insufficient_data",
        "reason": "Finish the quest to see your guessing pattern.",
        "solved_questions": 0, "attempted_questions": 0, "evaluated_questions": 0, "hinted_questions": 0,
        "limitations": LIMITATIONS,
    }
    result["summary"] = summarize(result)
    return result


# What each signal means in plain, non-judgemental words (used only when it fired).
_OBSERVATIONS = {
    "low_first_attempt_accuracy": "many questions weren't right on the first try",
    "high_retry_rate": "several questions needed more than one attempt",
    "chance_consistent_mcq": "first-try multiple-choice results were close to what random picking gives",
    "unresolved_after_repeated_misses": "some questions stayed unsolved after several tries",
    "repeated_rapid_incorrect": "a few wrong answers were sent in very quickly",
    "consistently_rapid_first_answers": "most first answers came in very quickly",
}
_HEADLINES = {
    "low": "No guessing pattern stood out.",
    "moderate": "Some answers may have been quick picks.",
    "high": "Your answers look a lot like quick picks.",
}


def summarize(result: dict) -> dict:
    """Short explanation + one next step, built only from what the analysis found."""
    if result["status"] != "ok":
        return {
            "level": "insufficient_data",
            "headline": "Not enough data yet.",
            "observation": result["reason"],
            "next_step": "Complete a few more questions and a pattern can be estimated.",
        }
    risk = result["risk"]
    fired = [s["id"] for s in risk["signals"] if s["triggered"]]
    if risk["level"] == "low" or not fired:
        observation = "Your answers looked thoughtful - mostly right on the first try, at a steady pace."
    else:
        parts = [_OBSERVATIONS[i] for i in fired if i in _OBSERVATIONS]
        joined = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        observation = "This estimate is based on the answer pattern: " + joined + "."
    weak = [t for t in result.get("topic_patterns", []) if t["needs_practice"]]
    if risk["level"] == "low":
        step = "Keep it up - try the next level whenever you're ready."
    elif {"repeated_rapid_incorrect", "consistently_rapid_first_answers"} & set(fired):
        step = "Next time, take a moment to read the question and every option before answering."
    elif weak:
        step = f"Practise {weak[0]['topic'].upper()} again - it's where first tries were hardest."
    else:
        step = "Review the questions you missed, then replay the level."
    return {"level": risk["level"], "headline": _HEADLINES[risk["level"]], "observation": observation, "next_step": step}
