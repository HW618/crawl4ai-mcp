FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY configs/ configs/
COPY src/ src/

RUN pip install --no-cache-dir .

ENV MCP_HOST=0.0.0.0 \
    MCP_PORT=8000 \
    CRAWL4AI_MCP_DATA_DIR=/data

VOLUME ["/data"]
EXPOSE 8000

CMD ["crawl4ai-mcp", "serve"]
