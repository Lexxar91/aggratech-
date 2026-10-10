FROM node:22.22.1-bookworm-slim@sha256:4f77a690f2f8946ab16fe1e791a3ac0667ae1c3575c3e4d0d4589e9ed5bfaf3d AS frontend-build
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM python:3.14.4-slim@sha256:2ca02f32b4d9d893863367ce07ec1972819f476dd38d8612f2a9cb6a41cbb727 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /opt/aggratech
RUN pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY app ./app
COPY runner ./runner
COPY --from=frontend-build /frontend/dist ./frontend/dist
COPY migrations ./migrations
COPY bank ./bank
COPY fixtures ./fixtures
COPY alembic.ini ./
ENV PATH="/opt/aggratech/.venv/bin:$PATH"
RUN useradd --uid 10001 --create-home appuser
USER appuser
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]

FROM base AS check
USER root
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/browsers
RUN uv sync --locked --no-install-project && .venv/bin/playwright install --with-deps chromium && rm -rf /var/lib/apt/lists/*
COPY tests ./tests
COPY runner ./runner
USER appuser
CMD ["pytest", "-q", "-m", "not runner"]

FROM docker:28.5.2-cli@sha256:625d9431a9f54c5a2bc90f24f0e1c3d55b1349fd857dd85035f98c2c9acbdd4d AS docker-cli

FROM python:3.14.4-slim@sha256:2ca02f32b4d9d893863367ce07ec1972819f476dd38d8612f2a9cb6a41cbb727 AS runner-controller
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=never UV_CACHE_DIR=/tmp/uv-cache
WORKDIR /opt/aggratech
RUN apt-get update && apt-get install -y --no-install-recommends openssl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.12.23
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY --from=docker-cli /usr/local/bin/docker /usr/local/bin/docker
COPY app/__init__.py ./app/__init__.py
COPY app/core/__init__.py app/core/config.py ./app/core/
COPY app/assessment/__init__.py app/assessment/runner.py ./app/assessment/
COPY app/tools/__init__.py app/tools/create_runner_pki.py ./app/tools/
COPY runner ./runner
ENV PATH="/opt/aggratech/.venv/bin:$PATH"
CMD ["python", "-m", "runner.server"]
