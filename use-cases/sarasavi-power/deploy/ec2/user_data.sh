#!/bin/bash
# First-boot setup: runtime dependencies + service skeletons. Code and secrets
# arrive later via deploy.ps1 / deploy.sh (scp), which also writes the Caddyfile
# with the final Elastic IP hostname and starts both services.
set -euxo pipefail

# 1 GB swap — belt-and-braces for PyAV/ADK memory spikes on small instances.
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab

apt-get update
apt-get install -y python3.12 python3.12-venv curl debian-keyring debian-archive-keyring apt-transport-https

# uv (Python package manager used by the project)
curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Caddy (auto-HTTPS reverse proxy for the Meta webhook)
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list
apt-get update && apt-get install -y caddy

mkdir -p /opt/sarasavi
chown ubuntu:ubuntu /opt/sarasavi

cat > /etc/systemd/system/sarasavi.service <<'EOF'
[Unit]
Description=Sarasavi Power (Agent Kernel WhatsApp + voice)
After=network-online.target

[Service]
User=ubuntu
WorkingDirectory=/opt/sarasavi
ExecStart=/usr/local/bin/uv run python app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
# Enabled but not started: waits for code + .env from the deploy script.
systemctl enable sarasavi
