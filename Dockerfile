FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 UV_PYTHON_DOWNLOADS=0 UV_LINK_MODE=copy

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server.py ./
# Not COPY --chmod: ACR Tasks builds without BuildKit. Files from some hosts arrive as 0600.
RUN chmod 0644 server.py
RUN useradd --system --no-create-home app
USER app

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "--factory", "server:create_app", "--host", "0.0.0.0", "--port", "8000"]
