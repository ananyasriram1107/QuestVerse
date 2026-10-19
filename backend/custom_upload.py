"""
Generates quiz questions from a player-uploaded PDF via the local Ollama
model. This is the one feature in the app with no offline/deterministic
fallback -- there's no way to invent original questions from arbitrary
uploaded text without an LLM, so it hard-requires Ollama to be running
(see ai/ollama_client.py for setup).

Text extraction tries pypdf's selectable-text layer first (fast, exact),
and falls back to OCR (PyMuPDF renders each page to an image, Tesseract
reads it) whenever that comes back empty or too short -- e.g. scanned
lecture notes or a PDF made from photos. OCR needs the Tesseract binary
installed on the host; if it isn't, extraction just degrades to "no text
found" instead of crashing.

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

MIN_TEXT_CHARS = 40  # below this, pypdf's "text" is noise -- treat the page as scanned and OCR it
OCR_MAX_PAGES = 15  # OCR is slow -- cap it so a huge scanned deck doesn't hang the request
OCR_RENDER_DPI = 200  # enough resolution for Tesseract without huge images


class PdfHasNoTextError(Exception):
    """Raised when the PDF has no extractable text (e.g. a scanned image)
    and OCR either isn't available or couldn't read it either."""


class GenerationFailedError(Exception):
    """Raised when Ollama is unreachable, or never returned usable questions."""


def _extract_selectable_text(file_bytes: bytes) -> str:
    """Text already embedded in the PDF (fast, exact) -- works for anything
    that isn't a scanned image."""
    reader = PdfReader(io.BytesIO(file_bytes), strict=False)
    pages_text = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(t for t in pages_text if t.strip()).strip()


def _ocr_pdf_text(file_bytes: bytes) -> str:
    """Rasterizes each page and runs Tesseract OCR over it -- the fallback
    for scanned PDFs that have no selectable text layer at all. Requires the
    Tesseract binary to be installed on the host (the pytesseract package is
    just a wrapper around it); if it's missing, we degrade to "no text found"
    rather than crashing the request.
    """
    try:
        import pymupdf as fitz  # renders PDF pages to images with no external binary needed
        import pytesseract
    except ImportError:
        return ""

    try:
        doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception:
        return ""

    zoom = OCR_RENDER_DPI / 72  # PDF points are 72 per inch
    matrix = fitz.Matrix(zoom, zoom)
    ocr_pages = []

    try:
        for page in doc[:OCR_MAX_PAGES]:
            pixmap = page.get_pixmap(matrix=matrix)
            image_bytes = pixmap.tobytes("png")
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes))
            try:
                page_text = pytesseract.image_to_string(image)
            except pytesseract.TesseractNotFoundError:
                return ""
            if page_text.strip():
                ocr_pages.append(page_text)
    finally:
        doc.close()

    return "\n".join(ocr_pages).strip()


def extract_pdf_text(file_bytes: bytes) -> str:
    """Selectable text first (fast, exact); if the PDF turns out to be a
    scanned image with little or no text layer, OCR it instead so scanned
    notes/handouts still work."""
    text = _extract_selectable_text(file_bytes)
    if len(text) < MIN_TEXT_CHARS:
        ocr_text = _ocr_pdf_text(file_bytes)
        if len(ocr_text) > len(text):
            text = ocr_text
    return text[:MAX_PDF_CHARS]


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
            "Couldn't find any readable text in that PDF, even after trying OCR on it -- "
            "it might be a low-quality scan, or the server may be missing the Tesseract OCR "
            "engine. Try a clearer scan or a different file."
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
