# Multi-stage: (1) build Next.js static export bằng Node; (2) runtime chỉ có Python.
# TRẠNG THÁI: CHƯA KIỂM CHỨNG bằng `docker build` tại môi trường agent (registry bị chặn) — xem docs/PREFLIGHT.md.

FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ROOT=/app \
    FRONTEND_DIR=/app/frontend_out
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/app backend/app
COPY policy policy
COPY ground_truth ground_truth
COPY GROUND_TRUTH.sha256 GROUND_TRUTH.sha256
COPY --from=web /web/out frontend_out
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
# Một tiến trình, một worker, một cổng do Railway cấp qua $PORT.
CMD ["sh", "-c", "exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
