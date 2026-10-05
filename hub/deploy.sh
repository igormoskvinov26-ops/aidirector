#!/bin/bash
# ==========================================================================
#  Деплой общего сервера «Пульт» (hub) на VDS
#
#  Отдельная, лёгкая штука: Docker-контейнер с общими расчётными
#  показателями (смены, касса, пульс базы — без клиентов и записей) плюс
#  PWA-витрина для владельца. Не имеет отношения к старой установке из
#  корневого deploy.sh (rubl-director/postgres/systemd) — та, по ROTATION.md,
#  уже не используется, и этот скрипт её не трогает.
#
#  Запуск: ./hub/deploy.sh   (из корня репозитория, на своей машине —
#  туда, где уже настроен SSH-ключ на сервер)
# ==========================================================================
set -euo pipefail

VPS="${VPS:-root@95.81.99.227}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/id_ed25519_proxy}"
DOMAIN="${DOMAIN:-igor-moskvinov.fvds.ru}"
HUB_DIR="$(cd "$(dirname "$0")" && pwd)"
VPS_DIR="/opt/pult-hub"

SSH="ssh -i $SSH_KEY"
SCP="scp -i $SSH_KEY"

ENV_FILE="$HUB_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi
if [ -z "${HUB_TOKEN:-}" ]; then
    HUB_TOKEN="$(openssl rand -hex 24)"
    echo "HUB_TOKEN=$HUB_TOKEN" > "$ENV_FILE"
    echo "Сгенерировал новый ключ доступа и сохранил в hub/.env (локально, в git не попадёт)."
else
    echo "Использую существующий ключ из hub/.env."
fi

echo "=== Деплой общего сервера «Пульт» ==="
echo "Сервер: $VPS"
echo "Домен:  $DOMAIN"
echo ""

# ── 1. Код на сервер ──────────────────────────────────────────────────────
echo "[1/4] Копирую код..."
$SSH "$VPS" "mkdir -p $VPS_DIR"
$SCP -r "$HUB_DIR/app.py" "$HUB_DIR/dashboard" "$HUB_DIR/Dockerfile" \
        "$HUB_DIR/docker-compose.yml" "$HUB_DIR/requirements.txt" \
        "$VPS:$VPS_DIR/" >/dev/null
$SSH "$VPS" "cat > $VPS_DIR/.env" <<EOF
HUB_TOKEN=$HUB_TOKEN
EOF
$SSH "$VPS" "chmod 600 $VPS_DIR/.env"
echo "       OK"

# ── 2. Docker ─────────────────────────────────────────────────────────────
echo "[2/4] Проверяю Docker..."
$SSH "$VPS" bash -s << 'PREP'
set -euo pipefail
if ! command -v docker >/dev/null 2>&1; then
    curl -fsSL https://get.docker.com | sh
fi
PREP
echo "       OK"

# ── 3. Контейнер ──────────────────────────────────────────────────────────
echo "[3/4] Собираю и запускаю контейнер..."
$SSH "$VPS" "cd $VPS_DIR && docker compose up -d --build" 2>&1 | tail -5
echo "       OK"

# ── 4. Nginx + сертификат ─────────────────────────────────────────────────
echo "[4/4] Nginx и сертификат для $DOMAIN..."
$SSH "$VPS" DOMAIN="$DOMAIN" bash -s << 'WEB'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

if ! command -v nginx >/dev/null 2>&1 || ! command -v certbot >/dev/null 2>&1; then
    apt-get update -qq
    apt-get install -y -qq nginx certbot python3-certbot-nginx ufw >/dev/null
fi

# Не трогаем сайт, если под этим именем уже что-то настроено кем-то другим.
if grep -rl "server_name[[:space:]].*$DOMAIN" /etc/nginx/sites-enabled/ 2>/dev/null \
    | grep -qv "pult-hub"; then
    echo "СТОП: $DOMAIN уже обслуживается другим сайтом nginx — проверьте вручную:"
    grep -rl "server_name[[:space:]].*$DOMAIN" /etc/nginx/sites-enabled/
    exit 1
fi

mkdir -p /var/www/html/.well-known/acme-challenge

# Шаг 1: только порт 80, без ssl-блока — сертификата ещё нет, и nginx
# откажется стартовать "listen ... ssl" без него (курица и яйцо).
# Выдаём его через webroot, уже потом дописываем https-блок.
cat > /etc/nginx/sites-available/pult-hub << NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}
NGINX

ln -sf /etc/nginx/sites-available/pult-hub /etc/nginx/sites-enabled/pult-hub
ufw allow 'Nginx Full' >/dev/null 2>&1 || true
nginx -t && systemctl reload nginx

if [ ! -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" ]; then
    certbot certonly --webroot -w /var/www/html -d "$DOMAIN" --non-interactive \
        --agree-tos --register-unsafely-without-email 2>&1 | tail -5
fi

# Шаг 2: сертификат есть — дописываем https-блок.
cat > /etc/nginx/sites-available/pult-hub << NGINX
server {
    listen 80;
    server_name $DOMAIN;

    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;

    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
NGINX

nginx -t && systemctl reload nginx
WEB
echo "       OK"

echo ""
echo "==============================================="
echo "  ГОТОВО"
echo ""
echo "  Адрес:     https://$DOMAIN"
echo "  Ключ:      $HUB_TOKEN"
echo ""
echo "  Дальше:"
echo "  1. На каждом компьютере с «Пультом»: Настройки → Интеграции →"
echo "     «Общий сервер» → вставить ключ выше → Сохранить."
echo "  2. На айфоне: открыть https://$DOMAIN в Safari, ввести тот же"
echo "     ключ, затем «Поделиться» → «На экран домой»."
echo "==============================================="
