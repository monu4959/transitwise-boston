"""Start, stop and check the OpenTripPlanner EC2 instance (tag Name=transitwise-otp, us-east-2).

    py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py status
    py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py up      # start, wait for OTP, print OTP_URL
    py -3.12 deploy/agentcore/otp_ec2/otp_ec2.py down    # stop (disk kept, ~$2.40/month)

Running costs about $0.10/hour, so stop it after every demo or load test. The public IP changes
on each start; `up` prints the new OTP_URL. Uses the AWS CLI login (`aws login`), profile default.
"""
import json
import sys
import time
import urllib.request

import boto3

REGION = "us-east-2"
NAME = "transitwise-otp"


def instance(ec2):
    resp = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [NAME]},
                                           {"Name": "instance-state-name",
                                            "Values": ["pending", "running", "stopping", "stopped"]}])
    found = [i for r in resp["Reservations"] for i in r["Instances"]]
    if not found:
        sys.exit(f"No instance tagged Name={NAME} in {REGION}.")
    return found[0]


def otp_ready(ip):
    req = urllib.request.Request(f"http://{ip}:8080/otp/gtfs/v1", method="POST",
                                 data=json.dumps({"query": "{ feeds { feedId } }"}).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return "feedId" in r.read().decode()
    except OSError:
        return False


def main(cmd):
    ec2 = boto3.client("ec2", region_name=REGION)
    i = instance(ec2)
    iid, state, ip = i["InstanceId"], i["State"]["Name"], i.get("PublicIpAddress")
    if cmd == "status":
        print(f"{iid}: {state}" + (f", OTP {'ready' if otp_ready(ip) else 'not answering'} "
                                   f"at http://{ip}:8080" if ip else ""))
    elif cmd == "down":
        ec2.stop_instances(InstanceIds=[iid])
        ec2.get_waiter("instance_stopped").wait(InstanceIds=[iid])
        print(f"{iid} stopped. Disk kept; compute billing has stopped.")
    elif cmd == "up":
        if state != "running":
            ec2.start_instances(InstanceIds=[iid])
            ec2.get_waiter("instance_running").wait(InstanceIds=[iid])
        ip = instance(ec2)["PublicIpAddress"]
        print(f"{iid} running at {ip}; waiting for OTP to load its graph (about a minute)...")
        for _ in range(60):
            if otp_ready(ip):
                print(f"OTP ready.\nOTP_URL=http://{ip}:8080/otp/gtfs/v1")
                print("Remember: otp_ec2.py down when you're done (about $0.10/hour while running).")
                return
            time.sleep(5)
        sys.exit("OTP did not answer within 5 minutes. Check: Session Manager -> journalctl -u otp")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) == 2 else "")
