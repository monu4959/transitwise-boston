# TransitWise on AWS (Amazon Bedrock AgentCore)

Work in progress. The Hugging Face Space (`deploy/huggingface`) is still the always-on demo; this
deployment is started for demos and load tests and stopped afterwards.

Everything runs in **us-east-2** (the project's region).

## Architecture

```
rider ──> agent (agent_server.py)  ──MCP──>  MCP server (mcp_server.py)  ──> OTP on EC2 (token proxy)
           Claude picks tools                 deterministic tools          ──> MBTA live alerts
           and writes the answer              rider preferences             ──> Snowflake
```

| Piece | Locally (works today) | On AWS (ready, waiting on account limits) |
|---|---|---|
| Agent | `agent_server.py` on 127.0.0.1:8080 | AgentCore Runtime, HTTP protocol (`agent/Dockerfile`) |
| Model | Claude on the Anthropic API (`LLM_API_KEY`) | Claude on Bedrock (`LLM_PROVIDER=bedrock`) |
| Agent → tools | `http://127.0.0.1:8000/mcp` | AgentCore Gateway (`MCP_URL`, `MCP_AUTH=sigv4`) |
| MCP server | `mcp_server.py` on 127.0.0.1:8000 | AgentCore Runtime, MCP protocol (`mcp/Dockerfile`) |
| Rider preferences | in the MCP server process | AgentCore Memory (`AGENTCORE_MEMORY_ID`) |
| Credentials | `.env` | Secrets Manager `transitwise/app`, `transitwise/otp` |
| Trip planner | OTP on EC2 through the token proxy | same |

**Who decides what.** Claude reads the request, picks the tool and its arguments, and writes the
answer from the tool results. The tools are deterministic: they plan step-free routes, check
live elevator outages, and apply the rider's saved preferences; Claude can't override them. The
rider ID is added to tool calls by the agent's code, never by the model, so a prompt can't read
or change another rider's preferences.

## Run it locally

Needs `.env` (MBTA, Snowflake, `LLM_API_KEY`) and AWS credentials (`aws login`) to read the OTP
token. On Windows with `aws login`, boto3 also needs `pip install "botocore[crt]"`.

```
py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py up            # prints OTP_URL; use port 80 below
py -3.12 deploy/agentcore/run_local.py --otp-url http://<ip>/otp/gtfs/v1

curl -X POST http://127.0.0.1:8080/invocations -H "Content-Type: application/json" \
     -d '{"prompt": "Northeastern to Logan Terminal B, avoid Kenmore", "rider_id": "rider-42"}'

py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py down          # when done
```

First local end-to-end run (2026-11-24, Claude Haiku 5.5 on the Anthropic API, OTP on EC2):

| Request (rider `demo-rider-2`) | Tool calls | Time | Tokens in/out | Claude cost |
|---|---|---|---|---|
| Northeastern → Logan Terminal B, avoid Kenmore | `plan_door_to_door` | 17.2 s (cold) | 5,618 / 860 | ~$0.0010 |
| Northeastern → Kendall/MIT (Kenmore not mentioned) | `plan_door_to_door`, saved "avoid Kenmore" applied | 6.3 s | 5,366 / 527 | ~$0.0008 |

Single runs, not a load test. The first request includes warm-up (Snowflake connection, station
graph). A first version of the prompt let Claude double-check trips with extra tool calls
(3 calls, 31 s, 12.5k input tokens); telling it the trip tool already includes the outage checks
fixed that.

## OpenTripPlanner on EC2 (`otp_ec2/`)

OTP is a Java server that holds the Boston routing graph (about 5 GB) in memory, so it can't run
inside AgentCore Runtime. It runs on its own EC2 instance instead.

| Choice | Why |
|---|---|
| `m7i-flex.large` (2 vCPU, 8 GiB, x86) | Building the graph needs a 6 GB heap. This is the free-tier-eligible type with 8 GiB (the free plan doesn't allow `t4g.large`). Not burstable, so no CPU credits to run out. |
| Ubuntu 24.04 | Java 25 (OTP 2.10 needs it) and `osmium-tool` (map clipping) are standard packages. |
| Default VPC, public IP | OTP downloads the timetable and map and polls MBTA realtime feeds every 30 s. A private subnet would need a NAT gateway (~$32/month). |
| Token proxy on port 80; 8080 open to one IP only; no SSH | AgentCore's outbound IPs change, so nginx checks an `X-OTP-Token` header instead (403 without it). The token lives in Secrets Manager and the instance role can read only that secret. Shell access is through Session Manager. |
| 30 GB encrypted gp3 disk, IMDSv2 required | The graph survives stop/start, so restarting only reloads it (about a minute). |
| Started for demos, stopped afterwards | ~$0.10/hour running, ~$2.40/month stopped (disk). |

`otp_ec2/user-data.sh` is the first-boot script: it installs Java and osmium, sets up the token
proxy (`otp_ec2/token-proxy.sh`), builds the graph with `otp/setup_otp.py graph`, and runs OTP as
a systemd service that starts on every boot. `sudo /opt/otp/refresh.sh` on the instance rebuilds
with a fresh MBTA timetable (do it if the instance has been stopped for more than a week).

```
py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py up       # start, wait for OTP, print OTP_URL
py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py status
py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py down     # stop when done
```

## AWS status

Created and working: OTP instance and token proxy, secrets `transitwise/app` and
`transitwise/otp`, S3 build bucket, ECR repository `transitwise-mcp`, CodeBuild project
`transitwise-image-build`.

Blocked until AWS Support lifts new-account limits: Bedrock model calls ("Operation not
allowed"), AgentCore Memory (`CreateMemory` access denied), AgentCore Runtime (0 agents allowed)
and CodeBuild (0 concurrent builds). Remaining steps once lifted:

1. Build both images: `package_source.py mcp|agent`, upload to `s3://transitwise-build-<account>-us-east-2/src/`, start `transitwise-image-build`.
2. Create the Memory resource; deploy the MCP server on Runtime (MCP protocol, IAM inbound) with `TRANSITWISE_SECRET_ID=transitwise/app,transitwise/otp`, `OTP_URL`, `AGENTCORE_MEMORY_ID`.
3. Create the Gateway (IAM inbound) with the Runtime as its target (IAM outbound).
4. Deploy the agent on Runtime (HTTP protocol) with `MCP_URL` set to the Gateway.
5. Turn on tracing, screenshot a trace, run the Locust load test, stop everything.
