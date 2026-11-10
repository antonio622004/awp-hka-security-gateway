ARG UV_VERSION=0.11.0
ARG PYTHON_MAIN_VERSION=3.14

FROM ghcr.io/astral-sh/uv:${UV_VERSION}-python${PYTHON_MAIN_VERSION}-trixie-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=0 \
    UV_NO_MANAGED_PYTHON=true UV_SYSTEM_PYTHON=true
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-default-groups --no-editable
COPY src ./src
RUN uv sync --frozen --no-default-groups --no-editable

FROM builder AS test-builder
RUN uv sync --frozen --group dev --no-editable

FROM python:${PYTHON_MAIN_VERSION}-slim-trixie AS runtime
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
RUN useradd --uid 10001 --create-home gateway
COPY --from=builder /app/.venv ./.venv
USER 10001:10001
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request,urllib.parse; host=urllib.parse.urlsplit(os.environ['GW_PUBLIC_URL']).netloc; urllib.request.urlopen(urllib.request.Request('http://localhost:8080/healthz',headers={'Host':host}),timeout=2)"]
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log", "--no-proxy-headers"]

FROM runtime AS test
COPY --from=test-builder /app/.venv ./.venv
COPY pyproject.toml ./
COPY src ./src
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider"]

FROM runtime AS final
