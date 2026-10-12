# Workbench: Angular SPA + FastAPI BFF + Benchmark runner. Build context: repo root (see render.yaml)
FROM node:24-slim AS web
WORKDIR /web
COPY UI/web/package.json UI/web/package-lock.json ./
RUN npm ci
COPY UI/web/ .
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    BENCH_DIR=/app/Benchmark \
    WEB_DIST=/app/UI/web/dist/web/browser
WORKDIR /app
COPY UI/server/requirements.txt /tmp/ui.txt
COPY Benchmark/requirements.txt /tmp/bench.txt
RUN pip install --no-cache-dir -r /tmp/ui.txt -r /tmp/bench.txt
COPY Benchmark/ Benchmark/
COPY UI/server/ UI/server/
COPY --from=web /web/dist/ UI/web/dist/
WORKDIR /app/UI/server
EXPOSE 10000
# Benchmark runs are spawned with this same interpreter (bench_python defaults to it when no venv exists)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips='*'"]
