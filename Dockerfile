# Cloud Run / GKE: Gemini + Firestore (no Torch). Set AI_BACKEND=gemini, GEMINI_USE_VERTEX=1, etc.
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV PORT=8080

EXPOSE 8080

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
