#!/bin/bash
# ==========================================================================
#  Деплой РублЪ AI Director
#
#  Что изменилось против прошлой версии:
#   • ставится и настраивается PostgreSQL (раньше его просто не было,
#     и половина разделов молча отдавала 500);
#   • приложение слушает 127.0.0.1, наружу смотрит nginx;
#   • сертификат от Let's Encrypt вместо самоподписанного;
#   • сервис работает от пользователя rubl, а не от root;
#   • пароль больше не печатается в консоль.
# ==========================================================================
set -euo pipefail

VPS="${VPS:-root@95.81.99.227}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_proxy}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VPS_DIR="/opt/rubl-director"
DOMAIN="${DOMAIN:-}"          # например: director.rublbarber.ru
SERVICE_USER="rubl"

SSH="ssh -i $SSH_KEY"
SCP="scp -i $SSH_KEY"

if [ -z "$DOMAIN" ]; then
    cat <<'MSG'
ОШИБКА: не задан домен.

Сервису нужен настоящий домен, чтобы получить сертификат Let's Encrypt.
По голому IP сертификат не выдаётся, а самоподписанный заставляет браузер
ругаться — и пользователь привыкает жать «всё равно перейти».

  1. Заведи A-запись, например director.rublbarber.ru → 95.81.99.227
  2. Запусти: DOMAIN=director.rublbarber.ru ./deploy.sh
MSG
    exit 1
fi

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "ОШИБКА: нет .env. Скопируй .env.example в .env и заполни."
    exit 1
fi

echo "=== Деплой РублЪ AI Director ==="
echo "Домен: $DOMAIN"
echo ""

# ── 1. Сборка фронтенда ───────────────────────────────────────────────────
echo "[1/6] Сборка фронтенда..."
cd "$PROJECT_DIR/frontend"
npm ci --no-audit --no-fund >/dev/null
npm run build 2>&1 | tail -3
rm -rf "$PROJECT_DIR/backend/static"
mkdir -p "$PROJECT_DIR/backend/static"
cp -r "$PROJECT_DIR/frontend/dist/"* "$PROJECT_DIR/backend/static/"
[ -f "$PROJECT_DIR/backend/static/index.html" ] || { echo "ОШИБКА: фронт не собрался"; exit 1; }
echo "       OK ($(du -sh "$PROJECT_DIR/backend/static" | cut -f1))"

# ── 2. Подготовка сервера ─────────────────────────────────────────────────
echo "[2/6] Подготовка сервера..."
$SSH "$VPS" bash -s << PREP
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -qq
apt-get install -y -qq postgresql nginx certbot python3-certbot-nginx curl ufw \
    fonts-dejavu-core >/dev/null

id -u $SERVICE_USER >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin $SERVICE_USER
mkdir -p $VPS_DIR/backend $VPS_DIR/output $VPS_DIR/assets/fonts
PREP

# ── 3. База данных ────────────────────────────────────────────────────────
echo "[3/6] PostgreSQL..."
DB_NAME=$(grep -E '^POSTGRES_DB=' "$PROJECT_DIR/.env" | cut -d= -f2-)
DB_USER=$(grep -E '^POSTGRES_USER=' "$PROJECT_DIR/.env" | cut -d= -f2-)
DB_PASS=$(grep -E '^POSTGRES_PASSWORD=' "$PROJECT_DIR/.env" | cut -d= -f2-)

$SSH "$VPS" DB_NAME="$DB_NAME" DB_USER="$DB_USER" DB_PASS="$DB_PASS" bash -s << 'DBSETUP'
set -euo pipefail
systemctl enable --now postgresql

sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -qc "CREATE ROLE \"$DB_USER\" LOGIN PASSWORD '$DB_PASS'"
sudo -u postgres psql -qc "ALTER ROLE \"$DB_USER\" PASSWORD '$DB_PASS'"

sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres createdb -O "$DB_USER" "$DB_NAME"

echo "       база готова"
DBSETUP

# ── 4. Код и зависимости ──────────────────────────────────────────────────
echo "[4/6] Копируем код..."
$SCP -r "$PROJECT_DIR/backend/app" \
        "$PROJECT_DIR/backend/alembic" \
        "$PROJECT_DIR/backend/alembic.ini" \
        "$PROJECT_DIR/backend/pyproject.toml" \
        "$PROJECT_DIR/backend/uv.lock" \
        "$PROJECT_DIR/backend/static" "$VPS:$VPS_DIR/backend/" >/dev/null
$SCP "$PROJECT_DIR/.env" "$VPS:$VPS_DIR/.env" >/dev/null

$SSH "$VPS" bash -s << SETUP
set -euo pipefail

chmod 600 $VPS_DIR/.env
chown -R $SERVICE_USER:$SERVICE_USER $VPS_DIR

command -v uv >/dev/null 2>&1 || { curl -LsSf https://astral.sh/uv/install.sh | sh; }
export PATH="\$HOME/.local/bin:\$PATH"

cd $VPS_DIR/backend
uv sync --frozen 2>&1 | tail -2
chown -R $SERVICE_USER:$SERVICE_USER $VPS_DIR/backend/.venv

# Схема через миграции, а не через create_all
sudo -u $SERVICE_USER $VPS_DIR/backend/.venv/bin/alembic upgrade head 2>&1 | tail -3

cat > /etc/systemd/system/rubl-director.service << SERVICE
[Unit]
Description=Rubl AI Director
After=network.target postgresql.service
Requires=postgresql.service

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$VPS_DIR/backend
Environment="PYTHONUNBUFFERED=1"
ExecStart=$VPS_DIR/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=10

# Ограничения: даже при дыре в коде процесс не дотянется до остального сервера
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$VPS_DIR/output
ProtectKernelTunables=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable rubl-director >/dev/null
systemctl restart rubl-director
SETUP

# ── 5. Nginx + сертификат ─────────────────────────────────────────────────
echo "[5/6] Nginx и сертификат..."
$SSH "$VPS" DOMAIN="$DOMAIN" bash -s << 'WEB'
set -euo pipefail

cat > /etc/nginx/sites-available/rubl-director << NGINX
server {
    listen 80;
    server_name $DOMAIN;
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl;
    http2 on;
    server_name $DOMAIN;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header Referrer-Policy "same-origin" always;

    client_max_body_size 12M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINX

ln -sf /etc/nginx/sites-available/rubl-director /etc/nginx/sites-enabled/rubl-director
rm -f /etc/nginx/sites-enabled/default

ufw allow 'Nginx Full' >/dev/null 2>&1 || true
# Порт 8443 больше не нужен: наружу торчит только 443
ufw delete allow 8443/tcp >/dev/null 2>&1 || true

certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --register-unsafely-without-email --redirect 2>&1 | tail -3

nginx -t && systemctl reload nginx
WEB

# ── 6. Проверка ───────────────────────────────────────────────────────────
echo "[6/6] Проверка..."
sleep 4
$SSH "$VPS" "curl -s http://127.0.0.1:8000/health"
echo ""
echo "==============================================="
echo "  ГОТОВО"
echo "  URL: https://$DOMAIN"
echo "  Логин и пароль — из .env (в консоль не печатаются)"
echo "==============================================="
