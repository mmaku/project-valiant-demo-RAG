# syntax=docker/dockerfile:1

# ---- Builder: install dependencies with uv ----
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /valiant_ai

# Lockfiles only → the dependency layer is cached independently of code changes
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen --no-install-project

# ---- Runtime: slimmed-down final image ----
FROM python:3.13-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/valiant_ai/.venv/bin:$PATH"

RUN useradd -u 1001 -m apiserviceaccount

WORKDIR /valiant_ai/app

# the venv is created next to pyproject.toml → /valiant_ai/.venv
COPY --from=builder --chown=apiserviceaccount:apiserviceaccount /valiant_ai/.venv /valiant_ai/.venv
COPY --chown=apiserviceaccount:apiserviceaccount app/ /valiant_ai/app/

USER apiserviceaccount
EXPOSE 8000

# the venv is on PATH → uvicorn without `uv run`.
# The container serves plain HTTP on port 8000. TLS is terminated upstream
# (platform ingress / reverse proxy); --proxy-headers makes the app read
# X-Forwarded-Proto/For and generate correct https URLs.
CMD ["uvicorn", "main:backend_app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
