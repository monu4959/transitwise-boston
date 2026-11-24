import os
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

from agents.aws_secrets import load_secrets
load_secrets()        # on AWS: MBTA/Snowflake credentials from Secrets Manager (no-op locally)

from agents import preferences
from agents.db import get_connection
from agents.planner import planner_agent
from agents.checker import checker_agent, get_live_alerts, access_alerts, service_disruptions
from agents.replanner import _ids
from agents.retriever import search_policies

# On AgentCore Runtime (MCP protocol) the server must listen on 0.0.0.0:8000 at /mcp, stateless.
TRANSPORT = (os.getenv("MCP_TRANSPORT") or "stdio").strip()
mcp = (FastMCP("transitwise", host="0.0.0.0", port=8000, stateless_http=True)
       if TRANSPORT == "streamable-http" else FastMCP("transitwise"))
MBTA_KEY = os.getenv("MBTA_KEY") or os.getenv("MBTA_API_KEY")
_conn = None


def conn():
    global _conn
    if _conn is None:
        _conn = get_connection()
    return _conn


def _station_names(ids):
    from agents import planner
    if planner._cache is None:
        planner._cache = planner.build_graph(conn())
    names = planner._cache[1]
    return [names[i] for i in ids if i in names]


@mcp.tool()
def plan_route(origin: str, destination: str, avoid: list[str] | None = None,
               rider_id: str | None = None) -> dict:
    """Find a step-free MBTA subway route between two stations (ignores live alerts).
    Optionally stay away from station IDs such as 'place-dwnxg' (Downtown Crossing);
    if that's impossible, the route may pass through them (listed in passes_through_avoided).
    rider_id: optional; the rider's saved stations to avoid are applied, and new ones remembered."""
    if not origin.strip() or not destination.strip():
        return {"ok": False, "reason": "Origin and destination are required."}
    ids = (avoid or [])[:10]
    if rider_id:
        prefs = preferences.apply(rider_id, avoid=_station_names(ids))
        ids = list(dict.fromkeys(ids + _ids(conn(), prefs["avoid"])))[:10]
    return planner_agent(conn(), origin.strip(), destination.strip(), exclude=ids)


@mcp.tool()
def check_route(origin: str, destination: str) -> dict:
    """Plan a route and check it against live MBTA elevator/escalator outages and service
    changes (suspensions, shuttles, closures). Returns whether the trip is safe, any blocking
    problems, and a route that avoids suspended segments and closed stops."""
    if not origin.strip() or not destination.strip():
        return {"ok": False, "reason": "Origin and destination are required."}
    plan = planner_agent(conn(), origin.strip(), destination.strip())
    if not plan["ok"]:
        return plan
    try:
        alerts = get_live_alerts(MBTA_KEY)
    except Exception:
        return {"route": plan["stations"],
                "error": "Live outage data unavailable. Check mbta.com/alerts/access."}
    result = {"route": plan["stations"], "check": checker_agent(plan, MBTA_KEY, alerts=alerts)}
    live = planner_agent(conn(), origin.strip(), destination.strip(),
                         disruptions=service_disruptions(alerts))
    if live["ok"] and live["path"] != plan["path"]:
        result["route_with_service_changes"] = live["stations"]
    return result


@mcp.tool()
def get_accessibility_alerts(limit: int = 20) -> list[dict]:
    """List current MBTA elevator and escalator outage alerts (max 50)."""
    limit = max(1, min(limit, 50))
    alerts = access_alerts(get_live_alerts(MBTA_KEY))[:limit]
    return [{"effect": a["attributes"]["effect"], "header": a["attributes"]["header"]}
            for a in alerts]


@mcp.tool()
def plan_door_to_door(origin: str, destination: str, depart_at: str | None = None,
                      max_roll_minutes: float | None = None, fewer_transfers: bool | None = None,
                      avoid: list[str] | None = None, rider_id: str | None = None) -> dict:
    """Plan a step-free door-to-door trip in the Boston area (rolling + bus + subway + Commuter
    Rail) with live MBTA times, checked against live elevator outages, stop changes and service
    problems. origin/destination: an address, place, station name, or "lat, lon".
    depart_at: ISO time with offset (e.g. 2026-11-14T09:00-05:00); omit to leave now.
    avoid: station names to stay away from (e.g. ["Kenmore"]).
    rider_id: optional; the rider's saved preferences (stations to avoid, longest roll, fewer
    transfers) are applied, and anything given here is remembered for their next trip.
    Defaults without saved preferences: 10-minute longest roll, normal transfers.
    Needs the OpenTripPlanner server (otp/setup_otp.py)."""
    from agents import planner
    from agents.door_to_door import plan_door_to_door as plan, describe_trip
    from agents.places import resolve_place
    if planner._cache is None:
        planner._cache = planner.build_graph(conn())
    o, d = resolve_place(origin[:200]), resolve_place(destination[:200])
    for p in (o, d):
        if not p["ok"]:
            return {"ok": False, "reason": p["reason"]}
    if max_roll_minutes is not None:
        max_roll_minutes = max(2.0, min(float(max_roll_minutes), 30.0))
    rider = preferences.apply(rider_id, avoid=(avoid or [])[:10],
                              max_roll_minutes=max_roll_minutes, fewer_transfers=fewer_transfers)
    roll = rider["max_roll_minutes"] or 10.0
    prefs = {"max_roll_min": roll, "max_total_roll_min": max(20.0, 2 * roll),
             "transfer_penalty": 15.0 if rider["fewer_transfers"] else 5.0}
    r = plan(conn(), o, d, MBTA_KEY, depart_at=depart_at, prefs=prefs,
             avoid_ids=_ids(conn(), rider["avoid"]), explain=False, log_source="mcp")
    if not r["ok"]:
        return {"ok": False, "reason": r["reason"]}
    issue = lambda p: {"where": p["station"], "role": p["role"], "alert": p["alert"]}
    return {"ok": True, "from": o["name"], "to": d["name"], "preferences_used": rider,
            "usual_trip_clear": not r["changed"],
            "problems_on_usual_trip": [issue(p) for p in r["problems"]],
            "recommended_trip": describe_trip(r["trip"]) if r["trip"] else None,
            "departs": r["trip"]["departs"] if r["trip"] else None,
            "arrives": r["trip"]["arrives"] if r["trip"] else None,
            "warnings": [issue(p) for p in r["warnings"]],
            "note": None if r["trip"] else r["explanation"]}


@mcp.tool()
def get_rider_preferences(rider_id: str) -> dict:
    """Show what TransitWise remembers about a rider: stations to avoid, longest single roll
    (minutes) and whether they prefer fewer transfers."""
    if not preferences.valid_rider_id(rider_id):
        return {"ok": False, "reason": "rider_id must be 1-64 letters, digits, '-' or '_'."}
    return {"ok": True, "rider_id": rider_id, **preferences.store().load(rider_id)}


@mcp.tool()
def forget_rider_preferences(rider_id: str, stations: list[str] | None = None) -> dict:
    """Remove stations from a rider's avoid list, or (with no stations) forget everything
    remembered about the rider."""
    if not preferences.valid_rider_id(rider_id):
        return {"ok": False, "reason": "rider_id must be 1-64 letters, digits, '-' or '_'."}
    s = preferences.store()
    if stations:
        prefs, changed = preferences.merge(s.load(rider_id), forget=stations)
    else:
        prefs, changed = dict(preferences.EMPTY), s.load(rider_id) != preferences.EMPTY
    if changed:
        s.save(rider_id, prefs)
    return {"ok": True, "rider_id": rider_id, **prefs}


@mcp.tool()
def search_mbta_policy(question: str, k: int = 4) -> list[dict]:
    """Search official MBTA accessibility policy documents (max 10 results).
    Returns the most relevant passages with their source files."""
    if not question.strip():
        return []
    k = max(1, min(k, 10))
    return search_policies(conn(), question.strip()[:500], k=k)


if __name__ == "__main__":
    # Load the embedding model before serving: loading it lazily inside a tool call
    # (which runs in a worker thread) hangs the server on Windows.
    from agents.retriever import get_model
    get_model()
    mcp.run(transport=TRANSPORT)
    #py -3.12 mcp_server.py