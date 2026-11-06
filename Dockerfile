# Kestrel Sentinel: adjudication engine + HTTP API + reviewer dashboard.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    KESTREL_DATA_PACK=/app/data/KCCS_Sentinel_Reference_Data_Pack.xlsx \
    KESTREL_DB_PATH=/var/lib/kestrel/kestrel.sqlite \
    KESTREL_EVIDENCE_DIR=/var/lib/kestrel/evidence \
    KESTREL_API_HOST=0.0.0.0 \
    KESTREL_API_PORT=8080

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir ".[api]"

COPY data ./data

RUN useradd --create-home --uid 10001 kestrel \
    && mkdir -p /var/lib/kestrel \
    && chown -R kestrel:kestrel /var/lib/kestrel
USER kestrel

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=4)"

CMD ["kestrel", "serve"]
