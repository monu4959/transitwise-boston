import os
import sys
from getpass import getpass
from dotenv import load_dotenv

load_dotenv()

# "anthropic" (Claude API, needs LLM_API_KEY), "bedrock" (Claude on Amazon Bedrock through the
# Anthropic SDK's Bedrock client: uses the AWS role or profile, no API key), or "openai".
# Anthropic and Bedrock take the same Messages API requests; only the client and model ID differ.
PROVIDER = (os.getenv("LLM_PROVIDER") or "anthropic").strip().lower()
MODEL = (os.getenv("BEDROCK_MODEL_ID") or "anthropic.claude-haiku-5-5") if PROVIDER == "bedrock" \
    else "claude-haiku-5-5"
MAX_TOKENS = 2000
_key = None
_clients = {}


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


def client(use_async=False):
    """The Anthropic SDK client for the configured provider (cached)."""
    kind = ("async-" if use_async else "") + PROVIDER
    if kind not in _clients:
        import anthropic
        if PROVIDER == "bedrock":
            cls = anthropic.AsyncAnthropicBedrockMantle if use_async else anthropic.AnthropicBedrockMantle
            _clients[kind] = cls(aws_region=os.getenv("AWS_REGION") or "us-east-2")
        else:
            cls = anthropic.AsyncAnthropic if use_async else anthropic.Anthropic
            _clients[kind] = cls(api_key=_get_key())
    return _clients[kind]


def ask_llm(prompt):
    if PROVIDER in ("anthropic", "bedrock"):
        msg = client().messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(block.text for block in msg.content if block.type == "text")
        if not text:
            text = f"(No answer text returned. stop_reason: {msg.stop_reason})"
        return text
    from openai import OpenAI
    oa = OpenAI(api_key=_get_key())
    resp = oa.chat.completions.create(
        model="gpt-4o-mini",   # check your OpenAI dashboard for current small models
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content
