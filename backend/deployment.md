# Static-IP VPS Deployment Notes

Target: one-user BreezePilot backend on a VPS whose public IP is registered with ICICI Direct for Breeze API trading.

## Required Environment

Copy `.env.example` to `.env` and set only the values needed for the server.

```bash
BREEZEPILOT_DB_PATH=/opt/breezepilot/data/breezepilot.db
BREEZEPILOT_ENCRYPTION_KEY_PATH=/opt/breezepilot/data/fernet.key
TRADING_MODE=paper
BREEZE_APP_KEY=
BREEZE_SECRET_KEY=
STATIC_IP_READY=false
ENFORCE_MARKET_HOURS=true
BREEZE_BASE_URL=https://api.icicidirect.com/breezeapi/api/v1
HERMES_ENABLED=true
HERMES_PROVIDER=kimi
HERMES_BASE_URL=https://api.moonshot.ai/v1
HERMES_MODEL=kimi-k2.6
HERMES_API_KEY=
HERMES_TIMEOUT_SECONDS=60
AUTOMATION_ENABLED=false
AUTO_PAPER_SCAN_INTERVAL_SECONDS=300
AUTO_PAPER_MONITOR_INTERVAL_SECONDS=30
SCANNER_MAX_SYMBOLS_PER_CYCLE=20
AUTO_LIVE_EXITS_ENABLED=false
AUTO_LIVE_ENTRIES_ENABLED=false
```

Set `TRADING_MODE=live` and `STATIC_IP_READY=true` only after the VPS IP is registered and verified. Live orders are still blocked until the daily session, saved credentials, strategy eligibility, and safety gates pass.
Keep `AUTO_LIVE_ENTRIES_ENABLED=false` until paper validation, backtests, and live exit monitoring have passed.
Keep `SCANNER_MAX_SYMBOLS_PER_CYCLE` modest because each scanned symbol can consume both quote and history Breeze API calls.

## GCP Deploy Helper

From your local project folder, deploy the backend to the configured GCP VM:

```bash
bash scripts/deploy_gcp_backend.sh
```

Defaults:

- project: `nifty-digit-491412-d6`
- zone: `asia-south2-a`
- instance: `breezepilot-vps`
- remote app: `/opt/breezepilot/app`
- remote data: `/opt/breezepilot/data`

Override if needed:

```bash
PROJECT_ID=your-project ZONE=asia-south2-a INSTANCE=breezepilot-vps bash scripts/deploy_gcp_backend.sh
```

The deploy helper does not copy local `.env`, SQLite data, Fernet keys, `node_modules`, or build output. If the remote `.env` does not exist, it creates a safe paper-automation profile.

## Kimi Agent Key On VPS

Keep `HERMES_API_KEY` on the VPS backend only. Do not store it in the Chrome extension.

To merge a one-line env file into the VPS `.env`:

```bash
cd /opt/breezepilot/app
python3 scripts/merge_env_file.py --env-file .env --values-file /tmp/breezepilot-hermes.env --delete-values-file
sudo systemctl restart breezepilot
curl -fsS http://127.0.0.1:8000/api/agent/status
```

Expected safe response fields:

```json
{"enabled":true,"provider":"kimi","apiKeyConfigured":true,"tradingMode":"paper"}
```

The endpoint must never return the API key value.

## Environment Profiles

Run these on the VPS from `/opt/breezepilot/app`:

```bash
python3 scripts/set_env_profile.py paper-automation --env-file .env
sudo systemctl restart breezepilot
```

After ICICI has registered the VPS static IP and the paper/backtest gates are ready, switch to manual live:

```bash
python3 scripts/set_env_profile.py manual-live --env-file .env
sudo systemctl restart breezepilot
```

After one manual live order has been prepared, confirmed, refreshed, and exited safely, enable live exits:

```bash
python3 scripts/set_env_profile.py live-exits --env-file .env
sudo systemctl restart breezepilot
```

Enable automatic live entries only after live exits are proven:

```bash
python3 scripts/set_env_profile.py live-entries --env-file .env
sudo systemctl restart breezepilot
```

## Readiness Check

Run this on the VPS:

```bash
cd /opt/breezepilot/app
. .venv/bin/activate
python3 scripts/check_real_trading_readiness.py
```

Use JSON output for automation:

```bash
python3 scripts/check_real_trading_readiness.py --json
```

The readiness script exits with a non-zero code when live blockers exist. That is expected while the system is in paper mode, missing the daily Breeze session, waiting for ICICI static-IP approval, or before paper/backtest gates pass.

Do not bypass these blockers. The intended order is:

1. Paper automation on the VPS.
2. Five paper-trading days and at least ten completed paper trades.
3. Passing backtest gate.
4. Manual-confirm live limit orders.
5. Automatic live exits.
6. Automatic live entries with small capital.

## Systemd Service

Example unit file: `/etc/systemd/system/breezepilot.service`

```ini
[Unit]
Description=BreezePilot FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
User=breezepilot
Group=breezepilot
WorkingDirectory=/opt/breezepilot/app
EnvironmentFile=/opt/breezepilot/app/.env
ExecStart=/opt/breezepilot/app/.venv/bin/uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

Commands:

```bash
sudo systemctl daemon-reload
sudo systemctl enable breezepilot
sudo systemctl start breezepilot
sudo systemctl status breezepilot
```

## Nginx Reverse Proxy

Use HTTPS in front of the local FastAPI process. Example server block:

```nginx
server {
    listen 443 ssl http2;
    server_name api.your-domain.example;

    ssl_certificate /etc/letsencrypt/live/api.your-domain.example/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.your-domain.example/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
```

Keep port `8000` bound to `127.0.0.1`. Do not expose the backend directly without HTTPS.

## Health Checks

Use the public health endpoint:

```bash
curl -fsS https://api.your-domain.example/api/health
```

Expected shape:

```json
{"status":"ok","database":"ok","tradingMode":"paper","staticIpReady":false}
```

Operational endpoints after login:

- `GET /api/safety/status`
- `GET /api/audit`
- `POST /api/safety/kill-switch`
- `POST /api/reports/daily/send`

## Backup And Restore

Back up these files together:

- SQLite database: `BREEZEPILOT_DB_PATH`
- Fernet key: `BREEZEPILOT_ENCRYPTION_KEY_PATH`
- `.env`

Example backup:

```bash
sudo systemctl stop breezepilot
tar -czf breezepilot-backup-$(date +%F).tar.gz /opt/breezepilot/data /opt/breezepilot/app/.env
sudo systemctl start breezepilot
```

Restore by stopping the service, replacing the database/key/env files from the backup, then starting the service. The Fernet key must match the encrypted credential rows in SQLite.

## Live Safety Checklist

- VPS public IP is registered with ICICI Direct.
- `STATIC_IP_READY=true` only on that registered VPS.
- `TRADING_MODE=live` is set intentionally.
- Daily Breeze session is active.
- Backtest gate has passed for the strategy.
- Paper validation has passed.
- `/api/safety/status` shows no kill switch, emergency lock, daily loss lock, or session lock.
- Live order flow is tested first through manual confirmation with small capital.
