# Build context: repo root (see render.yaml)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY Rag/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY Rag/ .
EXPOSE 10000
# Render sets PORT; migrations run as the pre-deploy command (python -m app.migrate)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
