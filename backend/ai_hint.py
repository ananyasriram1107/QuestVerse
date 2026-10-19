"""
AI verbal hints: a short nudge from the local Ollama model.

The model is shown the question (and the options for multiple choice) but never
the correct answer, so it can't repeat what it was never told. The reply is
still screened afterwards, in case the model happens to name the answer anyway.
"""

import re

from ai import ollama_client
from ai.dataset import get_language

HINT_TIMEOUT_S = 75  # CPU-only local inference is slow on the first call (model load)
MAX_HINT_CHARS = 280
MAX_REGENERATIONS = 2  # extra tries (with a stricter prompt) when a hint is rejected
FRIENDLY_FAILURE = "Your companion couldn't find a clue. Try again!"

SYSTEM_PROMPT = (
    "You are a friendly quest companion. Give ONE hint of at most two short sentences that helps a student "
    "reason about the question. Prefer a guiding question, or point at the core concept to think about. "
    "Do not state facts that settle the question, never say which option is right or wrong, never rule options "
    "out, never quote an option. Stay on the question's topic. Reply with the hint only."
)

# Used for the automatic re-tries after a hint was rejected for being too explicit.
STRICT_SYSTEM_PROMPT = (
    "You are a quest companion giving a very subtle clue. Reply with ONE short guiding question or nudge "
    "(one sentence) about the general idea behind the question. Do NOT use any specific name, number, term, "
    "value or option that could be the answer, and do not say what something is or equals. "
    "Never mention the options. Reply with the clue only."
)

# Short, cheap generations: ~60 tokens is plenty for two sentences, and a small context
# keeps prompt processing fast. keep_alive stops Ollama unloading the model between hints.
GENERATION_OPTIONS = {"num_predict": 60, "temperature": 0.4, "num_ctx": 1024}
KEEP_ALIVE = "30m"


class HintError(Exception):
    """A hint could not be produced; `message` is safe to show the player."""

    def __init__(self, message: str, status: int = 503):
        super().__init__(message)
        self.message = message
        self.status = status


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9()+ ]+", " ", str(text).lower())).strip()


def _forbidden_terms(question: dict) -> list:
    """Strings a hint must not contain: the correct answer / the grading keywords."""
    terms = []
    if question["mode"] == "mcq":
        terms.append(question["correct_answer"])
    elif question.get("field"):  # dataset question: the answer is the dataset value
        value = (get_language(question.get("language", "")) or {}).get(question["field"])
        for item in value if isinstance(value, list) else [value]:
            if isinstance(item, float) and item.is_integer():
                item = int(item)
            terms.append(str(item) if item is not None else "")
    else:
        for cluster in question.get("keyword_clusters", []) or []:
            terms.append(cluster.get("name", ""))
    return [t for t in (_norm(t) for t in terms) if len(t) >= 2]


GIVEAWAY_PHRASES = re.compile(r"\b(the (correct )?answer is|correct answer|the right answer|is the answer)\b", re.I)


def _mentions(text: str, term: str) -> bool:
    """Whole-word match, but a single word also matches its longer forms (dynamic -> dynamically)."""
    pattern = r"\b" + re.escape(term) + (r"\w*" if " " not in term and len(term) >= 4 else r"\b")
    return re.search(pattern, text) is not None


def leaks_answer(hint: str, question: dict) -> bool:
    """True if the hint gives the answer away: states it, quotes any option, or names a grading keyword."""
    if GIVEAWAY_PHRASES.search(hint):
        return True
    text = _norm(hint)
    terms = _forbidden_terms(question)
    if question["mode"] == "mcq":
        terms += [t for t in (_norm(o) for o in question["options"]) if len(t) >= 3]
    return any(_mentions(text, term) for term in terms)


def _build_prompt(question: dict) -> str:
    lines = [f"Question: {question['prompt']}"]
    if question["mode"] == "mcq":
        lines.append("Options (do not mention them): " + " | ".join(question["options"]))
    else:
        lines.append("The student must answer in their own words.")
    return "\n".join(lines)


def _parse(raw: str) -> str:
    text = " ".join(str(raw).split())
    text = re.sub(r"^(here'?s? (is )?(a |your )?(hint|clue)|a student asks|hint|clue)\s*:\s*", "", text, flags=re.I)
    text = text.replace('"', "").replace("“", "").replace("”", "").strip()
    sentences = re.findall(r"[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$", text)
    text = " ".join(s.strip() for s in sentences[:2]).strip()
    if len(text) > MAX_HINT_CHARS and len(sentences) > 1:
        text = sentences[0].strip()  # too long for two sentences -- keep one complete sentence
    return text[:MAX_HINT_CHARS].rsplit(" ", 1)[0] + "…" if len(text) > MAX_HINT_CHARS else text


def _ask(prompt: str, system: str, temperature: float) -> str:
    try:
        return ollama_client.generate(
            prompt, system=system, timeout=HINT_TIMEOUT_S, json_mode=False,
            options={**GENERATION_OPTIONS, "temperature": temperature}, keep_alive=KEEP_ALIVE,
        )
    except ollama_client.OllamaUnavailable as e:
        msg = str(e)
        if "404" in msg:
            raise HintError(
                f"The hint model '{ollama_client.OLLAMA_MODEL}' isn't installed. Run: ollama pull {ollama_client.OLLAMA_MODEL}"
            ) from e
        if "timed out" in msg:
            raise HintError("Your companion took too long to think. Try again.") from e
        raise HintError("Your companion can't be reached. Make sure Ollama is running (ollama serve).") from e


def generate_hint(question: dict) -> str:
    """One normal attempt, then up to MAX_REGENERATIONS stricter ones. Rejected drafts are
    discarded silently; the caller only ever sees an accepted hint or the friendly failure."""
    prompt = _build_prompt(question)
    plan = [(SYSTEM_PROMPT, 0.4)] + [(STRICT_SYSTEM_PROMPT, 0.7)] * MAX_REGENERATIONS
    for system, temperature in plan:
        hint = _parse(_ask(prompt, system, temperature))
        if hint and not leaks_answer(hint, question):
            return hint
    raise HintError(FRIENDLY_FAILURE, status=502)
