⚔️ QuestVerse

AI-powered gamified & adaptive learning platform.

QuestVerse turns academic material into an RPG-style learning experience that adapts to each learner's performance.

🔄 How It Works

PDF / Learning Content
        ↓
AI Concept Extraction
        ↓
Knowledge & Question Generation
        ↓
Adaptive Learning Engine
        ↓
Personalized Questions / Hints
        ↓
XP • Streaks • Levels • Boss Battles
        ↓
Mastery & Learning Insights

🧠 Tech Stack

- Frontend: React + Vite + Tailwind CSS + Framer Motion
- Backend: FastAPI + Python
- Database: SQLite + SQLModel
- AI: LLM-powered content generation & learner insights
- State: Zustand
- Visualization: Recharts
- Content: PDF → AI → validated question bank
- AI Safety: Static content fallback when LLM is unavailable

✨ Core Features

- 📚 AI-powered learning content generation
- 🧠 Adaptive difficulty & mastery tracking
- 🎯 Personalized hints and interventions
- ⚔️ RPG-style quests & boss battles
- 🔥 XP, streaks, levels & badges
- 📊 Learner progress & mastery insights
- 🛡️ Offline fallback for reliable demos

Built for an 18-hour hackathon.
## Running locally

```
# 1. Backend (from backend/). Creates/migrates backend/questverse.db on first start.
./venv/Scripts/python.exe -m uvicorn main:app --port 8010

# 2. Frontend (from frontend/). Talks to http://127.0.0.1:8010 via frontend/.env.development.
npm run dev            # http://localhost:5173

# Tests (from backend/)
./venv/Scripts/python.exe test_engine.py
./venv/Scripts/python.exe test_quest_flow.py
```

Port 8000 is often taken by other local APIs, which makes the map fail to load, so QuestVerse
uses 8010. To use 8000 instead, free it and delete `frontend/.env.development` (or override
`VITE_API_BASE_URL` in `frontend/.env.local`).
