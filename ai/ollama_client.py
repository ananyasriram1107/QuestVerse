"""
QuestVerse local LLM client (Ollama).

Talks to a locally-running Ollama server (https://ollama.com) over its plain
HTTP API. Nothing here needs an API key or internet access at request time --
Ollama itself runs entirely on the demo laptop, which is the whole point.

Setup (run once on the machine that will run the demo):

    macOS:    brew install ollama          (or download from ollama.com)
    Linux:    curl -fsSL https://ollama.com/install.sh | sh
    Windows:  download the installer from https://ollama.com/download

Then in a terminal:

    ollama serve            # starts the local server on :11434 (often auto-started)
    ollama pull llama3.2:1b # ~1.3GB, good speed/quality balance on a CPU laptop

Other model options if you want to try them (set OLLAMA_MODEL env var):
    phi3:mini    (~2.3GB, slightly stronger reasoning, a bit slower)
    gemma2:2b    (~1.6GB, good all-rounder)
    llama3.2:1b  (default -- fastest, fine for short JSON-graded answers)

Nothing in this module raises if Ollama isn't running -- every call site
should treat OllamaUnavailable as "fall back to the deterministic grader",
which is exactly what ai/short_ans.py does. That's what keeps a demo alive
if Ollama hiccups or was never started.
"""

import json
import os
import urllib.error
import urllib.request

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:1b")
DEFAULT_TIMEOUT_S = float(os.environ.get("OLLAMA_TIMEOUT_S", "8"))


class OllamaUnavailable(Exception):
    """Raised whenever we can't get a usable response from the local model."""


def is_running(timeout: float = 1.5) -> bool:
    """Quick health check -- hits /api/tags, which lists pulled models."""
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def list_models(timeout: float = 2.0) -> list[str]:
    try:
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/tags")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def generate(
    prompt: str,
    system: str | None = None,
    model: str = OLLAMA_MODEL,
    timeout: float = DEFAULT_TIMEOUT_S,
    json_mode: bool = True,
    options: dict | None = None,
    keep_alive: str | None = None,
) -> str:
    """
    Calls Ollama's /api/generate with streaming off, returns the raw text
    response. Raises OllamaUnavailable on any connection/timeout/HTTP error
    so callers can fall back cleanly instead of crashing the request.
    """
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
    }
    if system:
        payload["system"] = system
    if json_mode:
        payload["format"] = "json"
    if options:
        payload["options"] = options  # e.g. num_predict / temperature / num_ctx
    if keep_alive:
        payload["keep_alive"] = keep_alive  # how long Ollama keeps the model in memory after this call

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_HOST}/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip()
    except urllib.error.HTTPError as e:
        raise OllamaUnavailable(f"Ollama HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise OllamaUnavailable(f"Cannot reach Ollama at {OLLAMA_HOST}: {e.reason}") from e
    except TimeoutError as e:
        raise OllamaUnavailable(f"Ollama timed out after {timeout}s") from e


def warm_up(model: str = OLLAMA_MODEL, keep_alive: str = "30m", timeout: float = 120.0) -> bool:
    """Loads the model into memory (Ollama unloads idle models after ~5 minutes, which is
    what makes the first request after a pause take tens of seconds). Never raises."""
    try:
        generate("hi", model=model, timeout=timeout, json_mode=False, keep_alive=keep_alive,
                 options={"num_predict": 1})
        return True
    except OllamaUnavailable:
        return False


if __name__ == "__main__":
    if is_running():
        print(f"Ollama is up. Models available: {list_models()}")
        print(generate("Say hello in 5 words.", json_mode=False))
    else:
        print(f"Ollama not reachable at {OLLAMA_HOST}. Start it with `ollama serve`.")