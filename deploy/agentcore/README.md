# TransitWise on AWS (Amazon Bedrock AgentCore)

Work in progress. The Hugging Face Space (`deploy/huggingface`) is still the always-on demo; this
deployment is started for demos and load tests and stopped afterwards.

Everything runs in **us-east-2** (the project's region).

## OpenTripPlanner on EC2 (`otp_ec2/`)

OTP is a Java server that holds the Boston routing graph (about 5 GB) in memory, so it can't run
inside AgentCore Runtime. It runs on its own EC2 instance instead.

| Choice | Why |
|---|---|
| `m7i-flex.large` (2 vCPU, 8 GiB, x86) | Building the graph needs a 6 GB heap. This is the free-tier-eligible type with 8 GiB (the free plan doesn't allow `t4g.large`). Not burstable, so no CPU credits to run out. |
| Ubuntu 24.04 | Java 25 (OTP 2.10 needs it) and `osmium-tool` (map clipping) are standard packages. |
| Default VPC, public IP | OTP downloads the timetable and map and polls MBTA realtime feeds every 30 s. A private subnet would need a NAT gateway (~$32/month). |
| Port 8080 open to one IP only, no SSH | Shell access is through Systems Manager Session Manager (role with `AmazonSSMManagedInstanceCore` only). |
| 30 GB encrypted gp3 disk, IMDSv2 required | The graph survives stop/start, so restarting only reloads it (about a minute). |
| Started for demos, stopped afterwards | ~$0.10/hour running, ~$2.40/month stopped (disk). |

`otp_ec2/user-data.sh` is the first-boot script: it installs Java and osmium, builds the graph with
`otp/setup_otp.py graph`, and runs OTP as a systemd service that starts on every boot.
`/opt/otp/refresh.sh` on the instance rebuilds with a fresh MBTA timetable (run it if the
instance has been stopped for more than a week).

```
py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py up       # start, wait for OTP, print OTP_URL
py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py status
py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py down     # stop when done
```

To point the app at it: `OTP_URL=http://<ip>:8080/otp/gtfs/v1` (printed by `up`). The public IP
changes on every start. If your own IP changes, update the 8080 rule on `transitwise-otp-sg`.

Refresh the timetable (Session Manager shell, or Run Command):
`sudo /opt/otp/refresh.sh`

## Coming next

- AgentCore Runtime hosting `mcp_server.py` (`MCP_TRANSPORT=streamable-http`), behind AgentCore Gateway
- AgentCore Memory for rider preferences (`AGENTCORE_MEMORY_ID`, see `agents/preferences.py`)
- Secrets Manager for MBTA and Snowflake credentials (`TRANSITWISE_SECRET_ID`)
- Claude on Bedrock (`LLM_PROVIDER=bedrock`), tracing, and a Locust load test with real numbers
