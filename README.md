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
-  **Accounts:** log in or create an account; each user's heroes, levels, XP, accuracy and achievements are saved to the database.
-  **Weekly report:** a Monday-to-Monday summary of your questions, first-try accuracy, XP, levels and achievements (optionally emailed).
-  **Persistence:** attempts and sessions are saved in SQLite, so a refresh or restart resumes where you left off.
-  **Offline Mode:** an in-browser engine runs Free Play without the server ("Play offline without an account" on the login page).

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
pip install -r requirements-dev.txt   # requirements.txt for runtime only
uvicorn main:app --port 8010
```

macOS / Linux:

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
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

Backend (environment variables; see [`backend/.env.example`](backend/.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `10000` in Docker, `8010` for `python main.py` | Port to listen on (Render sets it) |
| `QUESTVERSE_ENV` | `development` | Set to `production` to stop localhost origins being allowed by CORS |
| `FRONTEND_URL` | – | Allowed frontend origin(s), comma separated, no trailing slash. `*` is refused |
| `QUESTVERSE_DB` | `backend/questverse.db` | SQLite file. Its folder is created if missing |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server for hints and PDF quizzes (optional) |
| `OLLAMA_MODEL` | `llama3.2:1b` | Model for hints and PDF quizzes |
| `QUESTVERSE_SMTP_HOST`, `QUESTVERSE_SMTP_FROM` (+ `_PORT`, `_USER`, `_PASSWORD`) | – | Set host and from-address to email weekly reports |

Frontend (see [`frontend/.env.example`](frontend/.env.example)):

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8010` in `npm run dev` only | Public URL of the API. **Required for production builds.** It is baked into the public bundle, so never put a secret in it |

## Deployment (Vercel + Render)

The frontend is a static Vite build on **Vercel**; the API is a Docker service on **Render**. Deploy the API first, then the frontend, then tell the API where the frontend lives.

### 1. Backend on Render

1. Push this repository to GitHub and create a **Blueprint** on Render pointing at it. [`render.yaml`](render.yaml) defines a Docker web service built from `backend/Dockerfile` (the build context is the repo root because the app imports the sibling `ai/` package). The image installs Tesseract so scanned PDFs can be OCR'd.
2. When prompted, leave `FRONTEND_URL` blank for now (or enter your Vercel URL if you already know it).
3. After the first deploy, open `https://<your-service>.onrender.com/health`. It should return `{"status":"ok"}`. It needs no login, no database content and no Ollama.

**Persistence.** The database is SQLite, a single file. The container's own filesystem is erased on every deploy and restart, so accounts and progress only survive if the file is on a **persistent disk**. `render.yaml` attaches one at `/var/data` and sets `QUESTVERSE_DB=/var/data/questverse.db`. Persistent disks need a paid Render plan (the blueprint uses `starter`). Without a disk, all data is lost on each restart; do not run production that way. A disk can only be attached to one instance, so keep the service at **one instance**, and keep one uvicorn worker (the image already does): quest sessions are held in process memory. Back the disk up (Render disk snapshots, or copy `questverse.db`) before risky changes. The app never deletes or resets the database on startup; it only creates it and applies missing schema migrations.

**Free-tier caveat.** A service that sleeps also stops the weekly-report job, which runs inside the API process.

### 2. Frontend on Vercel

1. Import the repository into Vercel and set **Root Directory** to `frontend`. [`frontend/vercel.json`](frontend/vercel.json) sets the build (`npm run build`, output `dist`).
2. Add the environment variable `VITE_API_BASE_URL` = your Render URL (for example `https://questverse-api.onrender.com`, no trailing slash) and deploy. It must be set before the build, because Vite bakes it in; change it and redeploy to apply.
3. Copy the Vercel URL into Render as `FRONTEND_URL` (several origins can be comma separated, for example a custom domain and a preview URL) and redeploy the API. CORS only lets those origins call it.

The app uses hash routes (`/#/map`), so no server-side routing is needed; the rewrite in `vercel.json` is just a safe fallback.

### 3. Optional services

- **AI hints and PDF quizzes (Ollama).** Render cannot run Ollama for you at a useful size. Host Ollama separately on a machine the API can reach (a GPU box or VM, or a private network), pull the model there, and set `OLLAMA_HOST` (for example `http://my-ollama-host:11434`) and optionally `OLLAMA_MODEL` on Render. Without it, the game works normally: **Get a hint** shows "Your companion can't be reached", PDF quiz generation returns a clear error, and nothing is ever replaced by made-up AI output. Do not expose an Ollama port to the whole internet without authentication.
- **Scanned-PDF OCR (Tesseract).** Included in the Docker image. Text-based PDFs never need it; if it is missing, scanned pages simply report "no readable text".
- **Weekly report emails.** Set `QUESTVERSE_SMTP_HOST` and `QUESTVERSE_SMTP_FROM` (plus port, user and password if your provider requires them). Reports are always available in the app regardless.

### 4. Deployment checklist

- [ ] `/health` on the Render URL returns ok
- [ ] Render has a persistent disk and `QUESTVERSE_DB` points into it
- [ ] `FRONTEND_URL` is your exact Vercel origin (scheme included, no trailing slash)
- [ ] `VITE_API_BASE_URL` is set on Vercel and the site was redeployed after setting it
- [ ] You can register, play a level, log out and log back in with progress intact (also after a Render restart)
- [ ] No `.env` files or `.db` files are committed

### Running the production image locally

```bash
docker build -f backend/Dockerfile -t questverse-api .
docker run -p 10000:10000 -e FRONTEND_URL=http://localhost:5173 -e QUESTVERSE_ENV=development \
  -e QUESTVERSE_DB=/var/data/questverse.db -v questverse-data:/var/data questverse-api
```

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
backend/    FastAPI app, accounts, sessions, SQLite store, grading, analytics, weekly reports, Dockerfile, tests
ai/         Ollama client and the Programming Languages question bank
render.yaml Render blueprint (API); frontend/vercel.json configures Vercel
frontend/   React app (pages, components, gamification, offline engine)
```

## Testing

From `backend/` with the virtual environment active:

```bash
python test_engine.py
python test_quest_flow.py   # takes a few minutes: it plays every level
python test_deploy.py      # CORS, configuration and start-up without Ollama
```

## Troubleshooting

- **`[Errno 10048]` port already in use:** another backend is still running on 8010. Stop it, or find it with `netstat -ano | findstr :8010` and run `taskkill /PID <PID> /F`. You can also use another port and set `VITE_API_BASE_URL`.
- **Map won't load:** the backend isn't running, or isn't on the port `VITE_API_BASE_URL` points to.
- **Hints fail:** make sure Ollama is running (locally, or reachable at `OLLAMA_HOST`) and the model is pulled.
- **Browser shows a CORS error in production:** `FRONTEND_URL` on Render must exactly equal the page's origin (for example `https://questverse.vercel.app`), then redeploy the API.
- **"doesn't know where its server is":** `VITE_API_BASE_URL` was not set when the Vercel build ran. Set it and redeploy.
- **Accounts or progress vanish after a restart on Render:** the database is not on a persistent disk (see Deployment).
- **PDF has no readable text:** install Tesseract so scanned pages can be read with OCR.