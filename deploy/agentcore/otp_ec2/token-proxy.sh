#!/bin/bash
# Token-protected proxy in front of OpenTripPlanner, so AgentCore Runtime (whose outbound IPs
# change) can reach OTP without opening it to everyone.
#
#   AgentCore Runtime --HTTP :80, header X-OTP-Token--> nginx --> OTP on 127.0.0.1:8080
#
# The token lives in the Secrets Manager secret transitwise/otp ({"OTP_TOKEN": "..."}); the
# instance role may read only that secret. otp-token.service copies it into nginx's config at
# every boot, so rotating the token is: update the secret, then reboot (or restart the service).
# Requests without the right header get 403; anything outside /otp/ gets 404.
# Run once as root (Session Manager or Run Command); user-data.sh runs it on new instances.
set -euxo pipefail

DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends nginx python3-boto3

cat > /usr/local/bin/otp-token-sync <<'EOF'
#!/usr/bin/env python3
"""Write the OTP token from Secrets Manager into nginx's token map (root-only file)."""
import json, os, re, urllib.request
import boto3

def region():
    tok = urllib.request.urlopen(urllib.request.Request(
        "http://169.254.169.254/latest/api/token", method="PUT",
        headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"}), timeout=5).read().decode()
    return urllib.request.urlopen(urllib.request.Request(
        "http://169.254.169.254/latest/meta-data/placement/region",
        headers={"X-aws-ec2-metadata-token": tok}), timeout=5).read().decode()

secret = boto3.client("secretsmanager", region_name=region()).get_secret_value(SecretId="transitwise/otp")
token = json.loads(secret["SecretString"])["OTP_TOKEN"]
if not re.fullmatch(r"[A-Za-z0-9_-]{32,128}", token):
    raise SystemExit("OTP_TOKEN must be 32-128 URL-safe characters")
path = "/etc/nginx/otp-token.map"
fd = os.open(path + ".tmp", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(f'"{token}" 1;\n')
os.replace(path + ".tmp", path)
EOF
chmod 755 /usr/local/bin/otp-token-sync

cat > /etc/systemd/system/otp-token.service <<'EOF'
[Unit]
Description=Copy the OTP proxy token from Secrets Manager into nginx
After=network-online.target
Wants=network-online.target
Before=nginx.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/otp-token-sync
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

cat > /etc/nginx/conf.d/otp-proxy.conf <<'EOF'
map $http_x_otp_token $otp_token_ok {
    default 0;
    include /etc/nginx/otp-token.map;
}

server {
    listen 80 default_server;
    server_name _;
    server_tokens off;
    client_max_body_size 64k;

    location /otp/ {
        if ($otp_token_ok = 0) { return 403; }
        proxy_pass http://127.0.0.1:8080;
        proxy_read_timeout 60s;
    }
    location / { return 404; }
}
EOF
rm -f /etc/nginx/sites-enabled/default

systemctl daemon-reload
systemctl enable otp-token nginx
systemctl restart otp-token
nginx -t
systemctl restart nginx
