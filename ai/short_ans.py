"""
QuestVerse short-answer grading.

Given a question that's really "what does the dataset say about field X of
language Y" and a free-text answer typed by the player, produce an accuracy
score (0-100) and descriptive, plain-English feedback.

Design: grade AND write feedback deterministically from ai/data/languages.csv
and the CONCEPT_EXPLANATIONS glossary below -- no LLM call in this path.
An earlier version asked a local Ollama model to sanity-check answers and
write the feedback sentence, but that made every short-answer submission
wait on a real network call to a local model (several seconds, or an 8s
timeout if Ollama wasn't running) before the player saw any reaction at
all. Writing good explanations by hand instead keeps grading instant while
still explaining the actual concept in plain English, not just stating the
correct value.

grade_short_answer() is the one function the backend/main.py answer route
needs to call.
"""

import re

from ai.dataset import CATEGORICAL_FIELDS, LIST_FIELDS, NUMERIC_FIELDS, get_language

# How forgiving numeric grading is per field: full credit inside the
# tolerance, then linear falloff to 0 at 3x the tolerance.
NUMERIC_TOLERANCE = {
    "year_created": 2,     # +/-2 years still "basically right"
    "popularity": 5,       # +/-5 percentage points
    "difficulty": 1,       # +/-1 point on the 1-5 scale
}

FIELD_QUESTION_TEXT = {
    "year_created": "What year was {language} created?",
    "popularity": "Roughly what percentage popularity does {language} have in this dataset?",
    "difficulty": "On a scale of 1 (easiest) to 5 (hardest), how difficult is {language} rated?",
    "paradigm": "What programming paradigm does {language} use?",
    "typing": "Is {language} statically or dynamically typed?",
    "use_cases": "Name a typical use case for {language}.",
}

# What each field actually represents, as a noun phrase that slots into
# "{language}'s {description} is {value}" -- e.g. "JavaScript's typing style
# is Dynamic".
FIELD_DESCRIPTIONS = {
    "year_created": "release year",
    "popularity": "popularity in this dataset",
    "difficulty": "difficulty rating on a 1-5 scale",
    "paradigm": "programming paradigm",
    "typing": "typing style",
    "use_cases": "typical use cases",
}

# Short, plain-English explanations of what each categorical value actually
# means -- so feedback teaches the concept, not just states the label.
CONCEPT_EXPLANATIONS = {
    "static": "static typing means the type of every variable is checked before the program ever runs, which catches type mistakes early but requires declaring types upfront",
    "dynamic": "dynamic typing means types are checked while the program is running, which makes the language more flexible to write in but lets some type mistakes slip through until that line actually executes",
    "object-oriented": "object-oriented means code is organized around objects that bundle related data and behavior together",
    "multi-paradigm": "multi-paradigm means the language doesn't lock you into one style -- you can freely mix object-oriented, functional, and procedural code depending on what fits the problem",
    "functional": "functional means the language favors building programs out of pure functions and avoiding changing state, rather than step-by-step instructions",
    "procedural": "procedural means the program runs as a straightforward sequence of instructions and function calls, executed roughly top to bottom",
}


def _explain(value: str) -> str:
    """Looks up a plain-English blurb for a categorical value; empty string if unknown."""
    return CONCEPT_EXPLANATIONS.get(value.strip().lower(), "")


def make_question(language: str, field: str, qid: str | None = None) -> dict:
    """Builds a short-answer question dict for one dataset field of one language."""
    row = get_language(language)
    if row is None:
        raise ValueError(f"Unknown language: {language}")
    from ai.dataset import tier_for_difficulty

    return {
        "id": qid or f"lang-sa-{language.lower()}-{field}",
        "courseId": "lang",
        "mode": "short_answer",
        "language": row["language"],
        "field": field,
        "prompt": FIELD_QUESTION_TEXT[field].format(language=row["language"]),
        "tier": tier_for_difficulty(row["difficulty"]),
    }


def _join_naturally(items: list[str]) -> str:
    """['a'] -> 'a'; ['a', 'b'] -> 'a and b'; ['a', 'b', 'c'] -> 'a, b, and c'."""
    items = list(items)
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _numeric_score(user_answer: str, correct_value: float, field: str, language: str) -> tuple[int, str]:
    description = FIELD_DESCRIPTIONS[field]
    match = re.search(r"-?\d+(\.\d+)?", user_answer)
    if not match:
        return 0, (
            f"That answer doesn't seem to include a number, so there's nothing to check it against -- "
            f"for the record, {language}'s {description} is {correct_value:g}."
        )

    guess = float(match.group())
    tolerance = NUMERIC_TOLERANCE.get(field, 1)
    diff = abs(guess - correct_value)

    if diff <= tolerance:
        return 100, f"That's right -- {language}'s {description} really is {correct_value:g}."

    if diff >= tolerance * 3:
        return 0, (
            f"Not quite -- {language}'s {description} is actually {correct_value:g}, "
            f"which is well off from your answer of {guess:g}."
        )

    # linear falloff between 1x and 3x tolerance
    score = round(100 * (1 - (diff - tolerance) / (tolerance * 2)))
    return max(0, min(100, score)), (
        f"Close, but not exact -- {language}'s {description} is {correct_value:g}, "
        f"so your guess of {guess:g} was off by {diff:g}."
    )


def _categorical_score(user_answer: str, correct_value: str, field: str, language: str) -> tuple[int, str]:
    description = FIELD_DESCRIPTIONS[field]
    explanation = _explain(correct_value)
    explanation_clause = f" -- {explanation}" if explanation else ""

    normalized_user = user_answer.strip().lower()
    normalized_correct = correct_value.strip().lower()
    if normalized_correct in normalized_user:
        return 100, f"Exactly right -- {language}'s {description} is {correct_value}{explanation_clause}."

    # cheap synonym table for the two categorical fields we actually have
    synonyms = {
        "dynamic": ["dynamically typed", "dynamic typing", "duck typed"],
        "static": ["statically typed", "static typing"],
        "object-oriented": ["oop", "object oriented", "objectoriented"],
        "multi-paradigm": ["multiparadigm", "multi paradigm", "hybrid"],
    }
    for canonical, aliases in synonyms.items():
        if canonical == normalized_correct and any(a in normalized_user for a in aliases):
            return 100, f"That's correct, just worded differently -- {language}'s {description} is {correct_value}{explanation_clause}."

    return 0, f"Not quite -- {language}'s {description} is actually {correct_value}{explanation_clause}."


def _list_score(user_answer: str, correct_values: list[str], language: str) -> tuple[int, str]:
    normalized_user = user_answer.strip().lower()
    hits = [v for v in correct_values if v.lower() in normalized_user]
    others = [v for v in correct_values if v not in hits]

    if not hits:
        return 0, (
            f"That doesn't match any of the typical use cases for {language} in this dataset, "
            f"which are {_join_naturally(correct_values)}."
        )

    score = round(100 * len(hits) / len(correct_values))
    sentence = f"Good -- {_join_naturally(hits)} {'is' if len(hits) == 1 else 'are'} right for {language}."
    if others:
        sentence += f" It's also commonly used for {_join_naturally(others)}."
    return score, sentence


def deterministic_grade(question: dict, user_answer: str) -> dict:
    row = get_language(question["language"])
    field = question["field"]
    correct_value = row[field]
    language = row["language"]

    if field in NUMERIC_FIELDS:
        score, note = _numeric_score(user_answer, correct_value, field, language)
    elif field in LIST_FIELDS:
        score, note = _list_score(user_answer, correct_value, language)
    elif field in CATEGORICAL_FIELDS:
        score, note = _categorical_score(user_answer, correct_value, field, language)
    else:
        score, note = 0, "Unknown field type."

    return {"accuracy": score, "correct_value": correct_value, "note": note}


def grade_short_answer(question: dict, user_answer: str) -> dict:
    """
    Returns:
        {
          "accuracy": int 0-100,
          "correct": bool,          # accuracy >= PASS_THRESHOLD
          "correct_value": ...,     # what the dataset actually says
          "feedback": str,          # descriptive, plain-English explanation
          "graded_by": "deterministic",
        }
    """
    PASS_THRESHOLD = 65

    if not user_answer or not user_answer.strip():
        row = get_language(question["language"])
        field = question["field"]
        correct_value = row[field]
        language = row["language"]

        if field in LIST_FIELDS:
            verb, fact = "are", _join_naturally(correct_value)
        elif field in CATEGORICAL_FIELDS:
            explanation = _explain(correct_value)
            verb, fact = "is", f"{correct_value}" + (f" -- {explanation}" if explanation else "")
        else:
            verb, fact = "is", f"{correct_value:g}"

        return {
            "accuracy": 0,
            "correct": False,
            "correct_value": correct_value,
            "feedback": f"You didn't write anything for this one -- {language}'s {FIELD_DESCRIPTIONS[field]} {verb} {fact}.",
            "graded_by": "deterministic",
        }

    det = deterministic_grade(question, user_answer)

    return {
        "accuracy": det["accuracy"],
        "correct": det["accuracy"] >= PASS_THRESHOLD,
        "correct_value": det["correct_value"],
        "feedback": det["note"],
        "graded_by": "deterministic",
    }


if __name__ == "__main__":
    q = make_question("Python", "year_created")
    print(q)
    for guess in ["1991", "1990", "1989", "no idea", "2015"]:
        print(guess, "->", grade_short_answer(q, guess))

    q2 = make_question("C++", "paradigm")
    for guess in ["Multi-paradigm", "OOP only", "object oriented and procedural"]:
        print(guess, "->", grade_short_answer(q2, guess))