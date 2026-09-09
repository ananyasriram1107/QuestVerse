"""
Grading for the OS/DBMS/DSA short-answer questions in course_content.py.

Concept coverage -- WHICH key ideas the player actually mentioned -- is
decided deterministically from keyword_clusters. That part has to stay
trustworthy and demo-safe, and a small local LLM has no business being the
judge of whether a fact is present in a paragraph; keyword/alias matching
does that job reliably.

Feedback text ("computer-y" labels like "Missing: Page Faults, CPU Drop")
used to get handed to a local Ollama model to turn into natural sentences.
That made every short-answer submission wait on a real network call before
the player saw any reaction -- several seconds if Ollama was running, or an
8-second timeout if it wasn't. _fallback_feedback below is written by hand
to read the same way a TA would talk you through it, grounded in the
question's model_answer so it can't drift from the real explanation, and
it's instant since there's no network call involved.
"""


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


def _fallback_feedback(user_answer: str, matched: list[str], missing: list[str], correct: bool, model_answer: str) -> str:
    """Natural-language feedback with no LLM involved -- used whenever Ollama isn't reachable."""
    if not user_answer or not user_answer.strip():
        return f"You didn't write anything for this one -- here's the idea in a nutshell: {model_answer}"

    if correct and not missing:
        return f"Nice work -- your answer covers everything it needs to, including {_join_naturally(matched)}."

    if correct:
        return f"Good answer overall. You clearly explained {_join_naturally(matched)}, which is really the heart of it."

    if matched:
        return (
            f"You're on the right track -- you touched on {_join_naturally(matched)}, but the answer is still "
            f"missing a piece. Here's the fuller picture: {model_answer}"
        )

    return f"That doesn't quite capture it yet. Here's what this one is really about: {model_answer}"


def grade_keyword_answer(question: dict, user_answer: str) -> dict:
    clusters = question.get("keyword_clusters", [])
    model_answer = question.get("model_answer", "")
    normalized = (user_answer or "").lower()

    matched = []
    missing = []
    for cluster in clusters:
        aliases = cluster.get("aliases", [])
        if any(alias.lower() in normalized for alias in aliases):
            matched.append(cluster["name"])
        else:
            missing.append(cluster["name"])

    threshold = question.get("min_clusters_required", 2)
    total = len(clusters) or 1
    accuracy = round(100 * len(matched) / total)
    correct = len(matched) >= threshold

    feedback = _fallback_feedback(user_answer or "", matched, missing, correct, model_answer)
    graded_by = "deterministic"

    return {
        "accuracy": accuracy,
        "correct": correct,
        "matched_concepts": matched,
        "missing_concepts": missing,
        "correct_value": model_answer,  # lets the review screen show the reference answer, same as the lang course
        "feedback": feedback,
        "graded_by": graded_by,
    }


if __name__ == "__main__":
    q = {
        "prompt": "Explain how Thrashing occurs in Virtual Memory.",
        "model_answer": "Thrashing happens when there are too many processes competing for too little RAM, causing constant page faults and swapping, which drops CPU utilization because the OS spends its time paging instead of running processes.",
        "keyword_clusters": [
            {"name": "Page Faults", "aliases": ["page fault", "page faults", "paging"]},
            {"name": "Swapping", "aliases": ["swapping", "swap", "disk i/o"]},
            {"name": "CPU Drop", "aliases": ["cpu utilization drops", "low cpu", "cpu idle"]},
        ],
        "min_clusters_required": 2,
    }
    for answer in [
        "Thrashing happens when there are too many page faults and constant swapping, so the cpu is idle.",
        "It's when the computer gets slow.",
        "",
    ]:
        print(answer, "->", grade_keyword_answer(q, answer))