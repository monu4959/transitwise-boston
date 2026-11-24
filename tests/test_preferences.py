"""Rider preferences (agents/preferences.py), the Bedrock LLM path and the Secrets Manager
loader. Fake AWS clients only: no network, no boto3 calls."""
import json

import pytest

from agents import aws_secrets, llm, preferences as P


def test_merge_accumulates_avoids_and_request_overrides():
    saved = {"avoid": ["Kenmore"], "max_roll_minutes": 8.0, "fewer_transfers": True}
    merged, changed = P.merge(saved, avoid=["kenmore", "Park Street"], max_roll_minutes=12)
    assert merged == {"avoid": ["Kenmore", "Park Street"], "max_roll_minutes": 12.0,
                      "fewer_transfers": True}
    assert changed


def test_merge_without_new_info_is_unchanged():
    saved = {"avoid": ["Kenmore"], "max_roll_minutes": None, "fewer_transfers": None}
    merged, changed = P.merge(saved)
    assert merged == saved and not changed


def test_forget_removes_stations_case_insensitively():
    merged, changed = P.merge({"avoid": ["Kenmore", "State"]}, forget=["kenmore"])
    assert merged["avoid"] == ["State"] and changed


def test_avoid_list_is_capped():
    merged, _ = P.merge(None, avoid=[f"S{i}" for i in range(25)])
    assert len(merged["avoid"]) == P.MAX_AVOID


def test_normalize_tolerates_junk():
    assert P.normalize({"avoid": "Kenmore", "max_roll_minutes": "ten", "fewer_transfers": 1}) == \
        {"avoid": ["Kenmore"], "max_roll_minutes": None, "fewer_transfers": None}
    assert P.normalize(None) == P.EMPTY


@pytest.mark.parametrize("rider_id, ok", [("rider-42", True), ("a_b", True), ("", False),
                                          ("has space", False), ("../etc", False), ("x" * 65, False),
                                          (None, False)])
def test_rider_id_validation(rider_id, ok):
    assert P.valid_rider_id(rider_id) is ok


def test_apply_remembers_between_trips(monkeypatch):
    monkeypatch.setattr(P, "_store", P.LocalStore())
    first = P.apply("rider-1", avoid=["Kenmore"], fewer_transfers=True)
    second = P.apply("rider-1")                          # next trip, nothing asked
    assert second == first == {"avoid": ["Kenmore"], "max_roll_minutes": None, "fewer_transfers": True}
    assert P.apply("rider-2") == P.EMPTY                 # riders don't share preferences


def test_apply_without_rider_id_stores_nothing(monkeypatch):
    store = P.LocalStore()
    monkeypatch.setattr(P, "_store", store)
    assert P.apply(None, avoid=["Kenmore"])["avoid"] == ["Kenmore"]
    assert store._data == {}


class FakeMemory:
    """Stands in for the bedrock-agentcore client: CreateEvent / ListEvents, two pages."""
    def __init__(self):
        self.events = []

    def create_event(self, **kw):
        self.events.append({"eventTimestamp": kw["eventTimestamp"], "payload": kw["payload"],
                            "actorId": kw["actorId"], "sessionId": kw["sessionId"]})

    def list_events(self, **kw):
        mine = [e for e in self.events if e["actorId"] == kw["actorId"]
                and e["sessionId"] == kw["sessionId"]]
        if "nextToken" in kw:
            return {"events": mine[1:]}
        return {"events": mine[:1], "nextToken": "page2"} if len(mine) > 1 else {"events": mine}


def test_memory_store_round_trip_newest_wins():
    fake = FakeMemory()
    store = P.MemoryStore("transitwise-abc1234567", client=fake)
    assert store.load("rider-1") == P.EMPTY
    store.save("rider-1", {"avoid": ["Kenmore"]})
    store.save("rider-1", {"avoid": ["Kenmore", "State"], "fewer_transfers": True})
    assert store.load("rider-1") == {"avoid": ["Kenmore", "State"], "max_roll_minutes": None,
                                     "fewer_transfers": True}
    assert store.load("rider-2") == P.EMPTY
    assert json.loads(fake.events[0]["payload"][0]["blob"])["avoid"] == ["Kenmore"]


def test_bedrock_provider(monkeypatch):
    from types import SimpleNamespace as NS
    sent = {}

    class FakeMessages:
        def create(self, **kw):
            sent.update(kw)
            return NS(content=[NS(type="text", text="Take the "), NS(type="text", text="Green Line.")],
                      stop_reason="end_turn")
    monkeypatch.setattr(llm, "PROVIDER", "bedrock")
    monkeypatch.setattr(llm, "_clients", {"bedrock": NS(messages=FakeMessages())})
    assert llm.ask_llm("hi") == "Take the Green Line."
    assert sent["max_tokens"] == llm.MAX_TOKENS   # never left unset
    assert sent["model"] == llm.MODEL
    assert llm.available()


def test_secrets_loader_off_by_default(monkeypatch):
    monkeypatch.delenv("TRANSITWISE_SECRET_ID", raising=False)
    assert aws_secrets.load_secrets() == []


def test_secrets_loader_fills_only_missing(monkeypatch):
    import sys
    import types

    class FakeSM:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps({"MBTA_KEY": "from-aws", "SNOWFLAKE_USER": "aws-user"})}
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name: FakeSM()))
    monkeypatch.setenv("TRANSITWISE_SECRET_ID", "transitwise/app")
    monkeypatch.setenv("SNOWFLAKE_USER", "local-user")
    monkeypatch.delenv("MBTA_KEY", raising=False)
    assert aws_secrets.load_secrets() == ["MBTA_KEY"]
    import os
    assert os.environ["MBTA_KEY"] == "from-aws" and os.environ["SNOWFLAKE_USER"] == "local-user"


def test_secrets_loader_reads_several_secrets(monkeypatch):
    import sys
    import types
    store = {"transitwise/app": {"MBTA_KEY": "k"}, "transitwise/otp": {"OTP_TOKEN": "t"}}

    class FakeSM:
        def get_secret_value(self, SecretId):
            return {"SecretString": json.dumps(store[SecretId])}
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda name: FakeSM()))
    monkeypatch.setenv("TRANSITWISE_SECRET_ID", "transitwise/app, transitwise/otp")
    monkeypatch.delenv("MBTA_KEY", raising=False)
    monkeypatch.delenv("OTP_TOKEN", raising=False)
    assert aws_secrets.load_secrets() == ["MBTA_KEY", "OTP_TOKEN"]


def test_otp_token_header(monkeypatch):
    from agents import otp
    monkeypatch.delenv("OTP_TOKEN", raising=False)
    assert otp._headers() == {}                          # local OTP: no header
    monkeypatch.setenv("OTP_TOKEN", "abc")
    assert otp._headers() == {"X-OTP-Token": "abc"}
