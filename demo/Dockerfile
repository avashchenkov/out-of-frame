FROM ghcr.io/astral-sh/uv:0.12.12 AS uv
FROM python:3.14-slim-bookworm AS build

COPY --from=uv /uv /usr/local/bin/uv
ENV UV_PYTHON_DOWNLOADS=never UV_LINK_MODE=copy
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
RUN uv sync --locked --no-dev --extra demo --no-editable

FROM python:3.14-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    AEGRA_CONFIG=/app/demo/aegra.json
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY demo/aegra.json demo/aegra.json
COPY demo/backend/ demo/backend/
USER 10001:10001
CMD ["python", "-m", "uvicorn", "aegra_api.main:app", "--host", "0.0.0.0", "--port", "2026", "--no-access-log"]
