"""TransitWise agent: Claude picks MCP tools and their arguments; the tools decide routes.

    prompt + rider_id -> Claude (tool use) -> TransitWise MCP tools -> grounded answer

Division of labour, on purpose for a safety-critical domain:
  * Claude reads the rider's request, chooses which tool to call and with what arguments, and
    writes the final answer from the tool results.
  * The MCP tools (mcp_server.py) are deterministic: they plan step-free routes, check live
    elevator outages and apply the rider's saved preferences. Claude can't override them.
  * The rider ID is added by this code, never by the model, so a prompt can't read or change
    another rider's preferences.

The MCP server is reached over streamable HTTP: http://localhost:8000/mcp locally, AgentCore
Gateway on AWS (MCP_URL, with MCP_AUTH=sigv4 for IAM-signed requests). The model is Claude on
the Anthropic API or on Bedrock, from agents/llm.py (LLM_PROVIDER).
"""
import json
import os
import time

from agents import llm, preferences

MCP_URL = os.getenv("MCP_URL") or "http://localhost:8000/mcp"
MAX_TOOL_ROUNDS = 6            # hard cap on model <-> tool round trips per request
MAX_TOKENS = 16000
INJECTED = "rider_id"          # filled in by code, hidden from the model

SYSTEM = """You are TransitWise, an accessibility assistant for wheelchair users, walker users and \
anyone who needs step-free trips on the MBTA (Boston's transit system).

Use the tools to answer. For a trip between two places, call plan_door_to_door once. Pass \
stations the rider asks to avoid in `avoid`, a limit on rolling or walking in `max_roll_minutes`, \
and set `fewer_transfers` when they ask for fewer changes. Leave out anything they didn't mention: \
the tool applies the rider's saved preferences on its own. Its result already includes the live \
elevator, escalator and service checks for that trip, so don't call check_route or \
get_accessibility_alerts to double-check it; those are for station-to-station subway questions \
and outage lists the rider asks for directly. To show or forget what's remembered about the \
rider, use get_rider_preferences or forget_rider_preferences.

Only state facts that come from tool results. If a tool reports an elevator outage or a \
problem, say so plainly and give the step-free alternative it returned. If no step-free trip \
exists, say that instead of guessing. Keep the answer short: the route, departure and arrival \
times, warnings, and which saved preferences were applied."""


def tool_specs(mcp_tools):
    """MCP tool definitions -> Anthropic tool definitions, with rider_id hidden from the model."""
    specs = []
    for t in mcp_tools:
        schema = json.loads(json.dumps(t.inputSchema or {"type": "object", "properties": {}}))
        schema.get("properties", {}).pop(INJECTED, None)
        if INJECTED in schema.get("required", []):
            schema["required"] = [r for r in schema["required"] if r != INJECTED]
        specs.append({"name": t.name, "description": t.description or "", "input_schema": schema})
    return specs


def with_rider(name, args, rider_id, mcp_tools):
    """Set rider_id on tools that take one, overriding anything the model sent."""
    args = dict(args or {})
    takes_rider = any(t.name == name and INJECTED in (t.inputSchema or {}).get("properties", {})
                      for t in mcp_tools)
    args.pop(INJECTED, None)
    if takes_rider and rider_id:
        args[INJECTED] = rider_id
    return args


def result_text(result):
    """An MCP CallToolResult as text for a tool_result block."""
    if getattr(result, "structuredContent", None):
        return json.dumps(result.structuredContent)[:20000]
    parts = [c.text for c in (result.content or []) if getattr(c, "type", "") == "text"]
    return ("\n".join(parts) or "(no output)")[:20000]


async def run(prompt, rider_id=None, session=None, client=None):
    """Answer one rider request. `session` is an initialized MCP ClientSession (opened here from
    MCP_URL when not given); `client` an async Anthropic client (from agents/llm.py by default)."""
    if not isinstance(prompt, str) or not prompt.strip():
        return {"ok": False, "error": "prompt is required"}
    if rider_id is not None and not preferences.valid_rider_id(rider_id):
        return {"ok": False, "error": "rider_id must be 1-64 letters, digits, '-' or '_'"}
    if session is None:
        async with open_session() as s:
            return await run(prompt, rider_id, session=s, client=client)

    client = client or llm.client(use_async=True)
    t0 = time.perf_counter()
    mcp_tools = (await session.list_tools()).tools
    tools = tool_specs(mcp_tools)
    messages = [{"role": "user", "content": prompt.strip()[:2000]}]
    calls, usage = [], {"input_tokens": 0, "output_tokens": 0}

    for _ in range(MAX_TOOL_ROUNDS + 1):
        response = await client.messages.create(model=llm.MODEL, max_tokens=MAX_TOKENS,
                                                system=SYSTEM, tools=tools, messages=messages)
        usage["input_tokens"] += response.usage.input_tokens
        usage["output_tokens"] += response.usage.output_tokens
        if response.stop_reason == "refusal":
            return _done(False, "I can't help with that request.", calls, usage, rider_id, t0)
        if response.stop_reason != "tool_use":
            text = "".join(b.text for b in response.content if b.type == "text").strip()
            return _done(True, text or "(no answer)", calls, usage, rider_id, t0)
        if len(calls) >= MAX_TOOL_ROUNDS * 3:
            break
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in (b for b in response.content if b.type == "tool_use"):
            args = with_rider(block.name, block.input, rider_id, mcp_tools)
            try:
                out = await session.call_tool(block.name, args)
                text, is_error = result_text(out), bool(out.isError)
            except Exception as e:                       # tool crashed or server unreachable
                text, is_error = f"Tool error: {e.__class__.__name__}: {str(e)[:300]}", True
            calls.append({"tool": block.name,
                          "input": {k: v for k, v in args.items() if k != INJECTED},
                          "is_error": is_error})
            results.append({"type": "tool_result", "tool_use_id": block.id,
                            "content": text, "is_error": is_error})
        messages.append({"role": "user", "content": results})
    return _done(False, "Stopped: too many tool calls for one request.", calls, usage, rider_id, t0)


def _done(ok, answer, calls, usage, rider_id, t0):
    return {"ok": ok, "answer": answer, "tool_calls": calls, "rider_id": rider_id,
            "model": llm.MODEL, "provider": llm.PROVIDER, "usage": usage,
            "ms": round((time.perf_counter() - t0) * 1000)}


def open_session(url=None):
    """Async context manager yielding an initialized MCP ClientSession over streamable HTTP."""
    from contextlib import asynccontextmanager
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    @asynccontextmanager
    async def _open():
        auth = SigV4Auth() if (os.getenv("MCP_AUTH") or "").lower() == "sigv4" else None
        async with streamablehttp_client(url or MCP_URL, auth=auth, timeout=60) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
    return _open()


try:
    import httpx

    class SigV4Auth(httpx.Auth):
        """Sign MCP requests with the caller's AWS credentials (AgentCore Gateway, IAM inbound)."""
        requires_request_body = True

        def __init__(self, service="bedrock-agentcore", region=None):
            self.service = service
            self.region = region or os.getenv("AWS_REGION") or "us-east-2"

        def auth_flow(self, request):
            import boto3
            from botocore.auth import SigV4Auth as _Signer
            from botocore.awsrequest import AWSRequest
            creds = boto3.Session().get_credentials().get_frozen_credentials()
            headers = {k: v for k, v in request.headers.items() if k.lower() != "connection"}
            aws = AWSRequest(method=request.method, url=str(request.url), data=request.content,
                             headers=headers)
            _Signer(creds, self.service, self.region).add_auth(aws)
            request.headers.update(dict(aws.headers.items()))
            yield request
except ImportError:                                      # httpx comes with mcp; just in case
    SigV4Auth = None
