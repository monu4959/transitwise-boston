"""The TransitWise agent loop (agents/trip_agent.py) with a fake MCP session and a fake Claude
client: no network, no API key, no AWS."""
import asyncio
import json
from types import SimpleNamespace as NS

from agents import trip_agent as A

PLAN_SCHEMA = {"type": "object", "properties": {
    "origin": {"type": "string"}, "destination": {"type": "string"},
    "avoid": {"type": "array", "items": {"type": "string"}},
    "rider_id": {"type": "string"}}, "required": ["origin", "destination"]}
MCP_TOOLS = [NS(name="plan_door_to_door", description="Plan a trip", inputSchema=PLAN_SCHEMA),
             NS(name="get_accessibility_alerts", description="Alerts",
                inputSchema={"type": "object", "properties": {"limit": {"type": "integer"}}})]


class FakeSession:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    async def list_tools(self):
        return NS(tools=MCP_TOOLS)

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if self.fail:
            raise ConnectionError("OTP down")
        return NS(isError=False, structuredContent={"ok": True, "recommended_trip": "Green Line"},
                  content=[])


def text_block(t):
    return NS(type="text", text=t)


def tool_block(name, inp, id_="tu_1"):
    return NS(type="tool_use", name=name, input=inp, id=id_)


class FakeClient:
    """Plays back a list of (stop_reason, content) responses and records the requests."""
    def __init__(self, script):
        self.script, self.requests = list(script), []
        self.messages = self

    async def create(self, **kw):
        self.requests.append(kw)
        stop, content = self.script.pop(0)
        return NS(stop_reason=stop, content=content, usage=NS(input_tokens=100, output_tokens=20))


def run(prompt, rider, session, client):
    return asyncio.run(A.run(prompt, rider, session=session, client=client))


def test_model_never_sees_rider_id():
    specs = A.tool_specs(MCP_TOOLS)
    plan = next(s for s in specs if s["name"] == "plan_door_to_door")
    assert "rider_id" not in plan["input_schema"]["properties"]
    assert "rider_id" in PLAN_SCHEMA["properties"]            # original schema untouched


def test_rider_id_is_injected_and_overrides_the_model():
    session = FakeSession()
    client = FakeClient([
        ("tool_use", [tool_block("plan_door_to_door",
                                 {"origin": "Northeastern", "destination": "Logan", "avoid": ["Kenmore"],
                                  "rider_id": "someone-else"})]),
        ("end_turn", [text_block("Take the Green Line.")]),
    ])
    r = run("Northeastern to Logan, avoid Kenmore", "rider-1", session, client)
    assert r["ok"] and r["answer"] == "Take the Green Line."
    name, args = session.calls[0]
    assert name == "plan_door_to_door" and args["rider_id"] == "rider-1"
    assert args["avoid"] == ["Kenmore"]
    assert r["tool_calls"] == [{"tool": "plan_door_to_door", "is_error": False,
                                "input": {"origin": "Northeastern", "destination": "Logan", "avoid": ["Kenmore"]}}]
    assert r["usage"] == {"input_tokens": 200, "output_tokens": 40}
    # the tool result went back to the model, and the assistant turn was kept whole
    second = client.requests[1]["messages"]
    assert second[1]["role"] == "assistant" and second[2]["content"][0]["tool_use_id"] == "tu_1"
    assert json.loads(second[2]["content"][0]["content"])["recommended_trip"] == "Green Line"


def test_tools_without_rider_id_get_none_added():
    assert A.with_rider("get_accessibility_alerts", {"limit": 5, "rider_id": "x"}, "rider-1", MCP_TOOLS) == {"limit": 5}


def test_no_rider_means_no_rider_id_sent():
    assert A.with_rider("plan_door_to_door", {"origin": "a", "rider_id": "x"}, None, MCP_TOOLS) == {"origin": "a"}


def test_tool_failure_is_reported_to_the_model():
    session = FakeSession(fail=True)
    client = FakeClient([("tool_use", [tool_block("plan_door_to_door", {"origin": "a", "destination": "b"})]),
                         ("end_turn", [text_block("The trip planner is unavailable right now.")])])
    r = run("a to b", None, session, client)
    assert r["tool_calls"][0]["is_error"] is True
    result = client.requests[1]["messages"][2]["content"][0]
    assert result["is_error"] is True and "OTP down" in result["content"]


def test_refusal_is_handled():
    r = run("something", None, FakeSession(), FakeClient([("refusal", [])]))
    assert not r["ok"] and "can't help" in r["answer"]


def test_tool_rounds_are_capped():
    loop = [("tool_use", [tool_block("get_accessibility_alerts", {})])] * (A.MAX_TOOL_ROUNDS + 1)
    session = FakeSession()
    r = run("alerts forever", None, session, FakeClient(loop))
    assert not r["ok"] and "too many tool calls" in r["answer"]
    assert len(session.calls) == A.MAX_TOOL_ROUNDS + 1


def test_sigv4_signs_gateway_requests(monkeypatch):
    import pytest
    pytest.importorskip("botocore")
    import httpx
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIDEXAMPLE")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    req = httpx.Request("POST", "https://gw.example.us-east-2.amazonaws.com/mcp", content=b'{"jsonrpc":"2.0"}')
    signed = next(A.SigV4Auth(region="us-east-2").auth_flow(req))
    auth = signed.headers["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/us-east-2/bedrock-agentcore/aws4_request" in auth and "x-amz-date" in signed.headers


def test_bad_input_rejected_before_any_call():
    assert not run("", None, FakeSession(), FakeClient([]))["ok"]
    assert not run("hi", "../etc/passwd", FakeSession(), FakeClient([]))["ok"]
