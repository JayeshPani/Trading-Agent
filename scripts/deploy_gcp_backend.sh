#!/usr/bin/env bash
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-nifty-digit-491412-d6}"
ZONE="${ZONE:-asia-south2-a}"
INSTANCE="${INSTANCE:-breezepilot-vps}"
REMOTE_DIR="${REMOTE_DIR:-/opt/breezepilot/app}"
REMOTE_DATA_DIR="${REMOTE_DATA_DIR:-/opt/breezepilot/data}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud CLI is required." >&2
  exit 1
fi

echo "Deploying BreezePilot backend to ${INSTANCE} (${PROJECT_ID}/${ZONE})"
gcloud config set project "${PROJECT_ID}" >/dev/null

ARCHIVE="$(mktemp -t breezepilot-deploy.XXXXXX.tar.gz)"
COPYFILE_DISABLE=1 tar \
  --exclude="./.git" \
  --exclude="./.env" \
  --exclude="./node_modules" \
  --exclude="./dist" \
  --exclude="./backend/data" \
  --exclude="./__pycache__" \
  --exclude="*.pyc" \
  -czf "${ARCHIVE}" .

gcloud compute ssh "${INSTANCE}" --zone "${ZONE}" --command \
  "sudo mkdir -p '${REMOTE_DIR}' '${REMOTE_DATA_DIR}' && sudo chown -R \$USER:\$USER /opt/breezepilot"

gcloud compute scp "${ARCHIVE}" "${INSTANCE}:/tmp/breezepilot-deploy.tar.gz" --zone "${ZONE}"

gcloud compute ssh "${INSTANCE}" --zone "${ZONE}" --command "
set -euo pipefail
REMOTE_USER=\$(id -un)
REMOTE_GROUP=\$(id -gn)
mkdir -p '${REMOTE_DIR}' '${REMOTE_DATA_DIR}'
tar -xzf /tmp/breezepilot-deploy.tar.gz -C '${REMOTE_DIR}'
cd '${REMOTE_DIR}'
sudo apt-get update
sudo apt-get install -y python3-venv python3-pip
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
if [ ! -f .env ]; then
  cp .env.example .env
  python3 scripts/set_env_profile.py paper-automation --env-file .env
  sed -i 's#^BREEZEPILOT_DB_PATH=.*#BREEZEPILOT_DB_PATH=${REMOTE_DATA_DIR}/breezepilot.db#' .env
  sed -i 's#^BREEZEPILOT_ENCRYPTION_KEY_PATH=.*#BREEZEPILOT_ENCRYPTION_KEY_PATH=${REMOTE_DATA_DIR}/fernet.key#' .env
  echo 'Created safe paper-automation .env. Add HERMES_API_KEY on the VPS before agent testing.'
fi
sudo tee /etc/systemd/system/breezepilot.service >/dev/null <<UNIT
[Unit]
Description=BreezePilot FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
User=\${REMOTE_USER}
Group=\${REMOTE_GROUP}
WorkingDirectory=${REMOTE_DIR}
EnvironmentFile=${REMOTE_DIR}/.env
ExecStart=${REMOTE_DIR}/.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable breezepilot
sudo systemctl restart breezepilot
sleep 2
sudo systemctl --no-pager status breezepilot | sed -n '1,12p'
"

rm -f "${ARCHIVE}"
echo "Deployment complete. SSH to the VPS and run:"
echo "  cd ${REMOTE_DIR} && . .venv/bin/activate && python3 scripts/check_real_trading_readiness.py"
