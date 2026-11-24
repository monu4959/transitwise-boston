# TransitWise MCP server for Amazon Bedrock AgentCore Runtime (MCP protocol).
# AgentCore runs on Graviton, so the image is ARM64; it's built in AWS CodeBuild on an ARM host
# (deploy/agentcore/mcp/buildspec.yml). Build context: the repository root.
# Contract: stateless streamable HTTP on 0.0.0.0:8000/mcp (set by MCP_TRANSPORT in mcp_server.py).
# No credentials in the image: they come from Secrets Manager at startup (TRANSITWISE_SECRET_ID).

FROM --platform=linux/arm64 python:3.12.16-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1 HF_HOME=/opt/hf
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
# CPU-only torch keeps the image small (the default ARM wheel can pull in GPU libraries)
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu
COPY deploy/agentcore/mcp/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt
# Bake the embedding model into the image: no download from Hugging Face on a cold start
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

FROM --platform=linux/arm64 python:3.12.16-slim-bookworm
RUN useradd --system --uid 1001 --create-home appuser
COPY --from=builder /opt/venv /opt/venv
COPY --from=builder --chown=appuser /opt/hf /opt/hf
WORKDIR /app
COPY agents ./agents
COPY mcp_server.py .
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf \
    HF_HUB_OFFLINE=1 \
    MCP_TRANSPORT=streamable-http
USER appuser
EXPOSE 8000
CMD ["opentelemetry-instrument", "python", "mcp_server.py"]
