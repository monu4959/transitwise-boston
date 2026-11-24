"""Run the MCP server and the agent locally, the way they will run on AgentCore, but with
Claude on the Anthropic API (LLM_API_KEY in .env) instead of Bedrock.

    py -3.12 deploy/agentcore/run_local.py --otp-url http://<ec2-ip>/otp/gtfs/v1

  * mcp_server.py on http://127.0.0.1:8000/mcp (streamable HTTP, as on AgentCore Runtime)
  * agent_server.py on http://127.0.0.1:8080 (POST /invocations, GET /ping)
  * OTP through the token proxy on EC2 (start it with otp_ec2.py up; use port 80, not 8080).
    The token is read from Secrets Manager (transitwise/otp) and never printed.
    For a local OTP server instead: --otp-url http://localhost:8080/otp/gtfs/v1 --no-token

Ctrl+C stops both servers. Then: otp_ec2.py down.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def otp_token(secret_id, region):
    import boto3
    value = boto3.client("secretsmanager", region_name=region).get_secret_value(SecretId=secret_id)
    return json.loads(value["SecretString"])["OTP_TOKEN"]


def wait_for(url, seconds=120, method="GET"):
    for _ in range(seconds):
        try:
            urllib.request.urlopen(urllib.request.Request(url, method=method), timeout=2)
            return True
        except urllib.error.HTTPError:
            return True                       # the server answered, even if not with 200
        except OSError:
            time.sleep(1)
    return False


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--otp-url", required=True)
    p.add_argument("--no-token", action="store_true", help="OTP without the token proxy")
    p.add_argument("--secret", default="transitwise/otp")
    p.add_argument("--region", default="us-east-2")
    a = p.parse_args()

    env = {**os.environ, "OTP_URL": a.otp_url, "MCP_TRANSPORT": "streamable-http",
           "MCP_HOST": "127.0.0.1", "MCP_URL": "http://127.0.0.1:8000/mcp",
           "LLM_PROVIDER": os.getenv("LLM_PROVIDER", "anthropic"), "PYTHONUNBUFFERED": "1"}
    if not a.no_token:
        env["OTP_TOKEN"] = otp_token(a.secret, a.region)

    procs = [subprocess.Popen([sys.executable, "mcp_server.py"], cwd=ROOT, env=env)]
    try:
        if not wait_for("http://127.0.0.1:8000/mcp"):
            sys.exit("MCP server did not start")
        procs.append(subprocess.Popen([sys.executable, "agent_server.py"], cwd=ROOT, env=env))
        if not wait_for("http://127.0.0.1:8080/ping"):
            sys.exit("Agent did not start")
        print("MCP server: http://127.0.0.1:8000/mcp\nAgent:      http://127.0.0.1:8080/invocations",
              flush=True)
        while all(proc.poll() is None for proc in procs):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for proc in procs:
            proc.terminate()


if __name__ == "__main__":
    main()
