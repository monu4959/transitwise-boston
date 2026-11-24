import os
import sys
from getpass import getpass
from dotenv import load_dotenv

load_dotenv()

# "anthropic" (Claude API, needs LLM_API_KEY), "bedrock" (Claude on Amazon Bedrock, uses the
# AWS role or profile: no API key), or "openai" (needs LLM_API_KEY holding an OpenAI key).
PROVIDER = (os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID") or "us.anthropic.claude-haiku-5-5"
MAX_TOKENS = 2000
_key = None
_bedrock = None


def available():
    """Whether an LLM is configured (the site shows the data-only explanation otherwise)."""
    return PROVIDER == "bedrock" or bool((os.getenv("LLM_API_KEY") or "").strip())


def _get_key():
    global _key
    if not _key:
        key = (os.getenv("LLM_API_KEY") or "").strip()
        if not key:
            if not (sys.stdin and sys.stdin.isatty()):   # a server: never wait for typed input
                raise RuntimeError("LLM_API_KEY is not set")
            key = getpass(f"{PROVIDER} API key: ")
        _key = key
    return _key


def _bedrock_client():
    global _bedrock
    if _bedrock is None:
        import boto3
        from botocore.config import Config
        _bedrock = boto3.client("bedrock-runtime",
                                config=Config(retries={"max_attempts": 5, "mode": "adaptive"}))
    return _bedrock


def ask_llm(prompt):
    if PROVIDER == "bedrock":
        resp = _bedrock_client().converse(
            modelId=BEDROCK_MODEL_ID,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": MAX_TOKENS},   # always explicit: unset reserves the model max
        )
        text = "".join(b.get("text", "") for b in resp["output"]["message"]["content"])
        return text or f"(No answer text returned. stopReason: {resp.get('stopReason')})"
    if PROVIDER == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=_get_key())
        msg = client.messages.create(
            model="claude-haiku-5-5",
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        if not text:
            text = f"(No answer text returned. stop_reason: {msg.stop_reason})"
        return text
    from openai import OpenAI
    client = OpenAI(api_key=_get_key())
    resp = client.chat.completions.create(
        model="gpt-4o-mini",   # check your OpenAI dashboard for current small models
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content
