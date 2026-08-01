#!/bin/bash
set -e

VPS="root@95.81.99.227"
SSH_KEY="$HOME/.ssh/id_ed25519_proxy"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VPS_DIR="/opt/rubl-director"
VPS_PORT=8443

SSH="ssh -i $SSH_KEY -o StrictHostKeyChecking=no"
SCP="scp -i $SSH_KEY -o StrictHostKeyChecking=no"

echo "=== Деплой РублЪ AI Director ==="
echo "VPS: 95.81.99.227:$VPS_PORT"
echo ""

# 1. Build frontend
echo "[1/5] Сборка React-фронтенда..."
cd "$PROJECT_DIR/frontend"
npm run build -- --outDir "$PROJECT_DIR/backend/static" 2>&1 | tail -3

if [ ! -f "$PROJECT_DIR/backend/static/index.html" ]; then
    echo "ОШИБКА: фронтенд не собрался"
    exit 1
fi
echo "       OK ($(du -sh "$PROJECT_DIR/backend/static" | cut -f1))"

# 2. Copy backend to VPS
echo "[2/5] Копируем бэкенд на VPS..."
$SSH "$VPS" "mkdir -p $VPS_DIR/backend/app"
$SCP -r "$PROJECT_DIR/backend/app" "$PROJECT_DIR/backend/pyproject.toml" "$PROJECT_DIR/backend/uv.lock" "$PROJECT_DIR/backend/static" "$VPS:$VPS_DIR/backend/" 2>&1 | tail -3

# 3. Copy .env
echo "[3/5] Копируем .env..."
$SSH "$VPS" "mkdir -p $VPS_DIR"
$SCP "$PROJECT_DIR/.env" "$VPS:$VPS_DIR/.env" 2>&1

# 4. Setup on VPS
echo "[4/5] Настройка VPS..."
$SSH "$VPS" bash -s << DEPLOY_SCRIPT
set -e

VPS_DIR="$VPS_DIR"
VPS_PORT="$VPS_PORT"

# Install uv if missing
if ! command -v uv &>/dev/null; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    source \$HOME/.local/bin/env
fi

# Install Python deps
cd "\$VPS_DIR/backend"
uv sync 2>&1 | tail -3

# Generate self-signed SSL cert
if [ ! -f "\$VPS_DIR/cert.pem" ]; then
    openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
        -keyout "\$VPS_DIR/key.pem" \
        -out "\$VPS_DIR/cert.pem" \
        -subj "/CN=rubl-director/O=Rubl/ST=Moscow/C=RU" 2>&1
    echo "SSL cert generated"
fi

# Allow port 8443 in UFW (only if not already allowed)
ufw status | grep -q "\$VPS_PORT" || ufw allow "\$VPS_PORT/tcp"

# Create systemd service
cat > /etc/systemd/system/rubl-director.service << SERVICE
[Unit]
Description=Rubl AI Director
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=\$VPS_DIR/backend
Environment="PYTHONUNBUFFERED=1"
ExecStart=\$VPS_DIR/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port \$VPS_PORT --ssl-keyfile \$VPS_DIR/key.pem --ssl-certfile \$VPS_DIR/cert.pem
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable rubl-director
systemctl restart rubl-director

echo "OK"
DEPLOY_SCRIPT

echo ""
echo "[5/5] Проверка..."
sleep 3
$SSH "$VPS" "curl -sk https://localhost:$VPS_PORT/health" 2>&1

echo ""
echo "==============================================="
echo "  ГОТОВО!"
echo "  URL: https://95.81.99.227:$VPS_PORT"
echo "  Логин: admin"
echo "  Пароль: <REDACTED>"
echo "==============================================="
