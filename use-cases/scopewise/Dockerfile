FROM python:3.12-slim AS build
RUN pip install --no-cache-dir uv==0.9.17
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --compile-bytecode

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH" SCOPEWISE_DATA=/app/data
RUN groupadd --gid 10001 scopewise && useradd --uid 10001 --gid scopewise --no-create-home scopewise
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY scopewise ./scopewise
COPY static ./static
COPY scripts ./scripts
COPY config.yaml ./
RUN mkdir -p /app/data && chown -R scopewise:scopewise /app
USER scopewise
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3)"
CMD ["uvicorn", "scopewise.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8080", "--workers", "1", "--no-access-log", "--limit-concurrency", "32", "--timeout-keep-alive", "5"]
