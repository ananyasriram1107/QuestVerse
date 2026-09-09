"""
Generates quiz questions from a player-uploaded PDF via the local Ollama
model. This is the one feature in the app with no offline/deterministic
fallback -- there's no way to invent original questions from arbitrary
uploaded text without an LLM, so it hard-requires Ollama to be running
(see ai/ollama_client.py for setup).

generate_questions_from_pdf() is the one function main.py's /custom/generate
route needs to call.
"""

import io
import json
import time

from pypdf import PdfReader

from ai import ollama_client

MAX_PDF_CHARS = 8000  # keeps the prompt small enough for a fast local model
GENERATION_TIMEOUT_S = 150  # CPU-only local inference varies a lot under system load -- generous margin per attempt


class PdfHasNoTextError(Exception):
    """Raised when the PDF has no extractable text (e.g. a scanned image)."""


class GenerationFailedError(Exception):
    """Raised when Ollama is unreachable, or never returned usable questions."""


def extract_pdf_text(file_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(file_bytes), strict=False)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    full_text = "\n".join(t for t in pages_text if t.strip())
    return full_text.strip()[:MAX_PDF_CHARS]


_MCQ_SYSTEM_PROMPT = """You are a quiz-writing assistant. You are given source material and must
write multiple-choice questions that test understanding of it.
Return ONLY raw JSON, no markdown, matching exactly this shape:
{"questions": [{"prompt": "<question text>", "options": ["<option 1>", "<option 2>", "<option 3>", "<option 4>"], "correct_answer": "<must exactly match one of the options>", "explanation": "<1-2 sentence explanation grounded in the source material>"}]}
Write exactly %(count)s questions, each answerable from the source material
alone. Options should be plausible and similar in length. Never invent facts
that aren't in the source material.
"""

_SHORT_ANSWER_SYSTEM_PROMPT = """You are a quiz-writing assistant. You are given source material and must
write short-answer questions that test understanding of it.
Return ONLY raw JSON, no markdown, matching exactly this shape:
{"questions": [{"prompt": "<question text>", "model_answer": "<a full reference-answer sentence>", "keywords": ["<key term 1>", "<key term 2>", "<key term 3>"]}]}
Write exactly %(count)s questions. "keywords" are the 3-5 essential words or
short phrases a correct answer must mention -- pick ones a student would
actually type, not full sentences. Never invent facts that aren't in the
source material.
"""


def _parse_generated(raw: str, mode: str, count: int) -> list[dict]:
    parsed = json.loads(raw)
    items = parsed.get("questions", [])
    if not isinstance(items, list):
        raise ValueError("Model did not return a list of questions")

    questions = []
    for index, item in enumerate(items[:count]):
        try:
            if mode == "mcq":
                options = [str(o).strip() for o in item["options"] if str(o).strip()]
                correct_answer = str(item["correct_answer"]).strip()
                if len(options) < 2 or correct_answer not in options:
                    continue
                questions.append({
                    "id": f"custom-mcq-{index}",
                    "courseId": "custom",
                    "mode": "mcq",
                    "tier": 1,
                    "prompt": str(item["prompt"]).strip(),
                    "options": options,
                    "correct_answer": correct_answer,
                    "explanation": str(item.get("explanation", "")).strip(),
                })
            else:
                keywords = [str(k).strip() for k in item.get("keywords", []) if str(k).strip()]
                if not keywords or not str(item.get("prompt", "")).strip():
                    continue
                questions.append({
                    "id": f"custom-sa-{index}",
                    "courseId": "custom",
                    "mode": "short_answer",
                    "tier": 1,
                    "prompt": str(item["prompt"]).strip(),
                    "model_answer": str(item.get("model_answer", "")).strip(),
                    "min_clusters_required": min(2, len(keywords)),
                    "keyword_clusters": [
                        {"name": keyword, "aliases": [keyword.lower()]}
                        for keyword in keywords
                    ],
                })
        except (KeyError, TypeError, ValueError):
            continue  # skip a malformed entry rather than failing the whole batch

    return questions


def generate_questions_from_pdf(file_bytes: bytes, mode: str, count: int) -> list[dict]:
    source_text = extract_pdf_text(file_bytes)
    if not source_text:
        raise PdfHasNoTextError(
            "This PDF doesn't seem to contain selectable text (it might be a scanned image) -- try a different file."
        )

    system_template = _MCQ_SYSTEM_PROMPT if mode == "mcq" else _SHORT_ANSWER_SYSTEM_PROMPT
    system_prompt = system_template % {"count": count}
    prompt = f"Source material:\n{source_text}\n\nWrite {count} questions from this material."

    # Small local models sometimes slip up on strict JSON (a missing comma,
    # a stray key) even with format="json", and Ollama itself can be
    # momentarily slow to respond while it loads a model into memory --
    # neither is a reason to fail outright on the first hiccup, so retry
    # the whole generation a couple of times before giving up.
    ATTEMPTS = 3
    last_error: Exception | None = None
    ollama_unreachable = False

    for attempt in range(ATTEMPTS):
        if attempt > 0:
            time.sleep(1.5)  # give Ollama a moment if it was just busy/loading

        try:
            raw = ollama_client.generate(prompt, system=system_prompt, timeout=GENERATION_TIMEOUT_S)
        except ollama_client.OllamaUnavailable as e:
            last_error = e
            ollama_unreachable = True
            continue

        ollama_unreachable = False

        try:
            questions = _parse_generated(raw, mode, count)
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            continue

        if questions:
            return questions
        last_error = ValueError("model returned no usable questions")

    if ollama_unreachable:
        raise GenerationFailedError(
            "Couldn't reach the local AI model. Make sure Ollama is running (`ollama serve`) and try again."
        ) from last_error

    if isinstance(last_error, (json.JSONDecodeError, ValueError)) and "no usable" not in str(last_error):
        raise GenerationFailedError(
            "The AI model kept returning malformed output. Try again, or use a shorter/clearer PDF."
        ) from last_error

    raise GenerationFailedError(
        "Couldn't generate any usable questions from this PDF. Try a different file, question type, or a stronger Ollama model."
    )
