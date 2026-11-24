"""Per-rider preferences that carry over between trips: stations to avoid, the longest single
roll, and whether to favour fewer transfers.

Stored in Amazon Bedrock AgentCore Memory when AGENTCORE_MEMORY_ID is set (one event per change,
under the rider's ID; the newest event wins), otherwise in this process only (local runs, tests).

Merging is plain code, not the LLM: stations to avoid accumulate until the rider removes them,
and a value given in the current request replaces the saved one and becomes the new saved value.
"""
import json
import os
import re
import time

MAX_AVOID = 10
SESSION = "preferences"           # all of a rider's preference events share one Memory session
_RIDER_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
EMPTY = {"avoid": [], "max_roll_minutes": None, "fewer_transfers": None}


def valid_rider_id(rider_id):
    return isinstance(rider_id, str) and bool(_RIDER_ID.fullmatch(rider_id))


def _dedupe(names):
    if isinstance(names, str):                    # one station given as a plain string
        names = [names]
    seen, out = set(), []
    for n in names or []:
        n = str(n).strip()
        if n and n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def normalize(prefs):
    """A well-formed copy of stored preferences (tolerates missing or junk fields)."""
    prefs = prefs if isinstance(prefs, dict) else {}
    roll = prefs.get("max_roll_minutes")
    fewer = prefs.get("fewer_transfers")
    return {"avoid": _dedupe(prefs.get("avoid"))[:MAX_AVOID],
            "max_roll_minutes": float(roll) if isinstance(roll, (int, float)) else None,
            "fewer_transfers": fewer if isinstance(fewer, bool) else None}


def merge(saved, avoid=None, max_roll_minutes=None, fewer_transfers=None, forget=None):
    """Combine saved preferences with this request. Returns (merged, changed)."""
    saved = normalize(saved)
    drop = {n.lower() for n in _dedupe(forget)}
    kept = [n for n in saved["avoid"] if n.lower() not in drop]
    merged = normalize({
        "avoid": kept + _dedupe(avoid),
        "max_roll_minutes": saved["max_roll_minutes"] if max_roll_minutes is None else max_roll_minutes,
        "fewer_transfers": saved["fewer_transfers"] if fewer_transfers is None else fewer_transfers,
    })
    return merged, merged != saved


class LocalStore:
    """Preferences kept in this process (lost on restart)."""
    def __init__(self):
        self._data = {}

    def load(self, rider_id):
        return normalize(self._data.get(rider_id))

    def save(self, rider_id, prefs):
        self._data[rider_id] = normalize(prefs)


class MemoryStore:
    """Preferences in AgentCore Memory: each save is a CreateEvent holding the full snapshot."""
    def __init__(self, memory_id, client=None):
        self.memory_id = memory_id
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import boto3
            self._client = boto3.client("bedrock-agentcore")
        return self._client

    def load(self, rider_id):
        events, token = [], None
        while True:
            args = {"memoryId": self.memory_id, "actorId": rider_id, "sessionId": SESSION,
                    "includePayloads": True, "maxResults": 100}
            if token:
                args["nextToken"] = token
            resp = self.client.list_events(**args)
            events += resp.get("events", [])
            token = resp.get("nextToken")
            if not token:
                break
        snapshots = []
        for e in events:
            for part in e.get("payload", []):
                data = _parse(part["blob"]) if "blob" in part else None
                if isinstance(data, dict):
                    snapshots.append((_ts(e.get("eventTimestamp")), data.get("seq", 0), data))
        if not snapshots:
            return normalize(None)
        # Newest wins. Timestamps can tie (fast saves, rounding), so `seq` breaks the tie.
        return normalize(max(snapshots, key=lambda s: (s[0], s[1]))[2])

    def save(self, rider_id, prefs):
        global _last_seq
        _last_seq = max(time.time_ns(), _last_seq + 1)
        self.client.create_event(
            memoryId=self.memory_id, actorId=rider_id, sessionId=SESSION,
            eventTimestamp=time.time(),
            payload=[{"blob": json.dumps({**normalize(prefs), "seq": _last_seq})}],
        )


_last_seq = 0


def _ts(value):
    return value.timestamp() if hasattr(value, "timestamp") else float(value or 0)


def _parse(blob):
    if isinstance(blob, (bytes, bytearray)):
        blob = blob.decode("utf-8")
    try:
        return json.loads(blob) if isinstance(blob, str) else blob
    except ValueError:
        return None


_store = None


def store():
    global _store
    if _store is None:
        memory_id = (os.getenv("AGENTCORE_MEMORY_ID") or "").strip()
        _store = MemoryStore(memory_id) if memory_id else LocalStore()
    return _store


def apply(rider_id, avoid=None, max_roll_minutes=None, fewer_transfers=None):
    """Load the rider's preferences, merge this request in, save if anything changed, and return
    the preferences to plan with. Without a valid rider_id, just the request itself."""
    if not valid_rider_id(rider_id):
        return merge(None, avoid, max_roll_minutes, fewer_transfers)[0]
    merged, changed = merge(store().load(rider_id), avoid, max_roll_minutes, fewer_transfers)
    if changed:
        store().save(rider_id, merged)
    return merged
