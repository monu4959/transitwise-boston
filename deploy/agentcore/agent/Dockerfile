# TransitWise agent for Amazon Bedrock AgentCore Runtime (HTTP protocol: GET /ping and
# POST /invocations on 0.0.0.0:8080). ARM64, built in CodeBuild (deploy/agentcore/agent/buildspec.yml).
# Build context: the repository root. No credentials in the image.

FROM --platform=linux/arm64 python:3.12.16-slim-bookworm AS builder
ENV PIP_NO_CACHE_DIR=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
COPY deploy/agentcore/agent/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

FROM --platform=linux/arm64 python:3.12.16-slim-bookworm
RUN useradd --system --uid 1001 --create-home appuser
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY agents/__init__.py agents/llm.py agents/preferences.py agents/aws_secrets.py agents/trip_agent.py ./agents/
COPY agent_server.py .
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    AGENT_HOST=0.0.0.0 \
    LLM_PROVIDER=bedrock \
    MCP_AUTH=sigv4
USER appuser
EXPOSE 8080
CMD ["opentelemetry-instrument", "python", "agent_server.py"]
