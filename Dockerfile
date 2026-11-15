FROM node:24.11.1-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.12.18 AS uv
FROM python:3.12.12-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH" PLAYWRIGHT_BROWSERS_PATH=/ms-playwright PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev && uv run --no-sync playwright install --with-deps chromium
COPY pharmacyflow/ pharmacyflow/
COPY migrations/ migrations/
COPY alembic.ini ./
COPY fixtures/ fixtures/
COPY scripts/ scripts/
COPY evaluation/ evaluation/
COPY --from=frontend /build/dist frontend/dist
RUN useradd --create-home --uid 10001 pharmacy && mkdir -p /app/data /app/reports && chown -R pharmacy:pharmacy /app/data /app/reports /ms-playwright
USER pharmacy
EXPOSE 8000
CMD ["uvicorn","pharmacyflow.api:app","--host","0.0.0.0","--port","8000"]
