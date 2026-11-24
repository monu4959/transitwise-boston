#!/bin/bash
# First-boot script for the OpenTripPlanner EC2 instance (Ubuntu 24.04, m7i-flex.large, 8 GiB).
# Installs Java and osmium, builds the Boston routing graph (fresh MBTA timetable + OpenStreetMap,
# about 10-15 minutes), and runs OTP as a systemd service on port 8080. The service starts by
# itself on every later boot, so stopping and starting the instance only reloads the graph
# (about a minute). Progress: /var/log/cloud-init-output.log, then `journalctl -u otp`.
set -euxo pipefail

OTP_VERSION=2.10.0
HOME_DIR=/opt/otp
REPO=https://github.com/monu4959/transitwise-boston.git

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  openjdk-25-jre-headless osmium-tool python3 git curl ca-certificates   # OTP 2.10 needs Java 25

useradd --system --create-home --home-dir "$HOME_DIR" --shell /usr/sbin/nologin otp || true
curl -fsSL -o "$HOME_DIR/otp.jar" \
  "https://repo1.maven.org/maven2/org/opentripplanner/otp-shaded/${OTP_VERSION}/otp-shaded-${OTP_VERSION}.jar"
git clone --depth 1 "$REPO" "$HOME_DIR/app"

# Rebuild script: new MBTA timetable -> new graph -> restart. Run it before a demo or load test
# if the instance has been stopped for more than a week (the timetable goes stale).
cat > "$HOME_DIR/refresh.sh" <<'EOF'
#!/bin/bash
set -euxo pipefail
systemctl stop otp || true
sudo -u otp git -C /opt/otp/app pull --ff-only     # as the owner (git refuses other users' repos)
sudo -u otp env OTP_JAR=/opt/otp/otp.jar OTP_DATA_DIR=/opt/otp OTP_BUILD_HEAP=6g \
  python3 /opt/otp/app/otp/setup_otp.py graph
rm -f /opt/otp/download/*.pbf
systemctl start otp
EOF
chmod 755 "$HOME_DIR/refresh.sh"
chown -R otp:otp "$HOME_DIR"

cat > /etc/systemd/system/otp.service <<'EOF'
[Unit]
Description=OpenTripPlanner (TransitWise Boston)
After=network-online.target
Wants=network-online.target

[Service]
User=otp
WorkingDirectory=/opt/otp
ExecStart=/usr/bin/java -Xmx5g -jar /opt/otp/otp.jar --load --serve /opt/otp/data
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable otp

"$HOME_DIR/refresh.sh"     # first graph build, then starts the service
