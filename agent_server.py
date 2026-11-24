"""TransitWise agent over HTTP, in AgentCore Runtime's HTTP protocol contract:
GET /ping (health) and POST /invocations on 0.0.0.0:8080.

    py -3.12 agent_server.py          # needs mcp_server.py running (MCP_TRANSPORT=streamable-http)

    curl -X POST localhost:8080/invocations -H "Content-Type: application/json" \
         -d '{"prompt": "Northeastern to Logan Terminal B, avoid Kenmore", "rider_id": "rider-42"}'

Same code locally and on AgentCore: locally the agent calls the MCP server at localhost:8000 and
Claude on the Anthropic API; on AWS it calls AgentCore Gateway (MCP_URL, MCP_AUTH=sigv4) and
Claude on Bedrock (LLM_PROVIDER=bedrock).
"""
import os

from dotenv import load_dotenv

load_dotenv()

from agents.aws_secrets import load_secrets  # noqa: E402
load_secrets()                    # on AWS: credentials from Secrets Manager (no-op locally)

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

from agents import trip_agent  # noqa: E402

app = FastAPI(title="TransitWise agent")


class Invocation(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=2000)
    rider_id: str | None = Field(None, max_length=64)


@app.get("/ping")
def ping():
    return {"status": "Healthy"}


@app.post("/invocations")
async def invocations(req: Invocation):
    return await trip_agent.run(req.prompt, req.rider_id)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.getenv("AGENT_HOST", "127.0.0.1"), port=int(os.getenv("AGENT_PORT", "8080")))
