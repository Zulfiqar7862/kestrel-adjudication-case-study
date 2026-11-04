FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY data ./data
RUN pip install --no-cache-dir .
ENV KESTREL_DATA_PACK=/app/data/KCCS_Sentinel_Reference_Data_Pack.xlsx
ENV KESTREL_DB_PATH=/app/.data/kestrel.sqlite
ENV KESTREL_EVIDENCE_DIR=/app/.data/evidence
EXPOSE 8080
CMD ["kestrel", "serve", "--host", "0.0.0.0", "--port", "8080"]
