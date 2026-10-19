# ⚔️ QuestVerse

A gamified, adaptive learning adventure for computer-science students. Walk a pixel-art world map, clear levels in Operating Systems, Databases, Algorithms and Programming Languages, earn XP and stars, and get a report on how you really answered. Optionally, get hints from a local AI companion or turn your own PDF into a quiz.

## Features

-  **Adventure map:** 4 stages × 4 courses = 16 levels that unlock in order. The server decides what is open.
-  **Two quiz formats:** timed multiple choice (15 s) and untimed short answer in your own words.
-  **Adaptive difficulty:** 2 correct in a row raises the tier, 2 wrong lowers it. XP scales with tier.
-  **XP, levels, stars and badges:** plus a lifetime achievements page.
-  **AI hints:** a local [Ollama](https://ollama.com) model nudges you without ever seeing the answer.
-  **PDF → quiz:** upload notes and a local LLM writes 3, 5 or 10 questions (OCR for scanned PDFs).
-  **Quest report:** first-try accuracy, retry rate, an explainable guessing-pattern indicator and practice suggestions.
-  **Persistence:** attempts and sessions are saved in SQLite, so a refresh or restart resumes where you left off.
-  **Offline Mode:** an in-browser engine runs Free Play without the server.

## Tech stack

| Layer | Tools |
|---|---|
| Frontend | React 19, Vite 8, plain CSS |
| Backend | Python, FastAPI, Uvicorn |
| Database | SQLite (standard-library `sqlite3`) |
| PDF / OCR | pypdf, PyMuPDF, pytesseract, Pillow |
| Local AI | Ollama (default model `llama3.2:1b`) |

The backend is the source of truth: correctness, XP, tier, unlocks and timing are all computed server-side, and grading is deterministic (the LLM is only used for hints and PDF questions).

## Getting started

**Prerequisites:** Python 3.10+, Node.js 20.19+ or 22.12+. Optional: [Ollama](https://ollama.com/download) for hints and PDF quizzes, and [Tesseract](https://github.com/tesseract-ocr/tesseract) for scanned PDFs.

### 1. Backend (run from `backend/`, on port 8010)

Windows (PowerShell):

```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --port 8010
```

macOS / Linux:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --port 8010
```

The database is created automatically. API docs are at http://127.0.0.1:8010/docs.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

### 3. (Optional) AI features

```bash
ollama serve
ollama pull llama3.2:1b
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` (frontend `.env.local`) | `http://127.0.0.1:8010` | Backend URL |
| `QUESTVERSE_DB` | `backend/questverse.db` | SQLite file path |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server |
| `OLLAMA_MODEL` | `llama3.2:1b` | Model for hints and PDF quizzes |

## Game rules

- **Stages:** Beginner's Grove (easy MCQ), Knowledge Caverns (medium MCQ), Trial Grounds (short answer), Boss Realm (hardest, mixed).
- **Completing a level:** answer every question correctly. Wrong answers can be retried.
- **XP:** tier × 10 per correct answer, granted once per question per level, so replays can't farm XP.
- **Player level:** `floor(√(XP / 50)) + 1`.
- **Stars:** ★★★ at 80%+ first-try accuracy, ★★ at 50%+, otherwise ★.
- **Misses never reveal the answer.** You get a hint instead.

## Content

86 built-in questions: Operating Systems, Database Systems and Data Structures & Algorithms (12 each, in `backend/course_content.py`), plus 50 Programming Languages questions generated from `ai/data/languages.csv`.

## Project structure

```text
backend/    FastAPI app, sessions, SQLite store, grading, analytics, tests
ai/         Ollama client and the Programming Languages question bank
frontend/   React app (pages, components, gamification, offline engine)
```

## Testing

From `backend/` with the virtual environment active:

```bash
python test_engine.py
python test_quest_flow.py
```

## Troubleshooting

- **`[Errno 10048]` port already in use:** another backend is still running on 8010. Stop it, or find it with `netstat -ano | findstr :8010` and run `taskkill /PID <PID> /F`. You can also use another port and set `VITE_API_BASE_URL`.
- **Map won't load:** the backend isn't running, or isn't on the port `VITE_API_BASE_URL` points to.
- **Hints fail:** make sure Ollama is running and the model is pulled.
- **PDF has no readable text:** install Tesseract so scanned pages can be read with OCR.