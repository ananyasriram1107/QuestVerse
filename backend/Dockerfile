# QuestVerse backend image (used by Render, see ../render.yaml).
#
# Build context is the REPOSITORY ROOT, not backend/: the app imports the sibling `ai/` package
# (Ollama client + Programming Languages question bank and dataset).
#
#   docker build -f backend/Dockerfile -t questverse-api .
#   docker run -p 10000:10000 -e FRONTEND_URL=http://localhost:5173 -v questverse-data:/var/data \
#              -e QUESTVERSE_DB=/var/data/questverse.db questverse-api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    QUESTVERSE_ENV=production

# Tesseract is what lets scanned (image-only) PDFs be read. Text PDFs don't need it, and the app
# degrades to "no readable text" if it is missing -- it is installed here so OCR works out of the box.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

COPY ai ai
COPY backend backend

WORKDIR /app/backend

# Render sets PORT; 10000 is Render's default and a fine fallback elsewhere.
ENV PORT=10000
EXPOSE 10000

# One worker on purpose: quest sessions and locks live in this process's memory (they are rebuilt
# from SQLite after a restart, but two workers would each hold their own copy).
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
