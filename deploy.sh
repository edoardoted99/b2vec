#!/usr/bin/env bash
set -euo pipefail

DOMAIN="b2vec.org"
APP_DIR="/opt/b2vec"
COMPOSE="docker compose -f docker-compose.prod.yml"

echo "=== b2vec production deployment ==="

# ── 1. Clone or pull ─────────────────────────────────────────────
if [ -d "$APP_DIR/.git" ]; then
    echo "[1/6] Pulling latest changes..."
    cd "$APP_DIR"
    git pull
else
    echo "[1/6] Cloning repository..."
    git clone https://github.com/tedesco/b2vec.git "$APP_DIR"
    cd "$APP_DIR"
fi

# ── 2. .env.prod ─────────────────────────────────────────────────
if [ ! -f "$APP_DIR/.env.prod" ]; then
    echo "[2/6] Creating .env.prod – please edit it with the correct values!"
    cp "$APP_DIR/.env.prod.example" "$APP_DIR/.env.prod" 2>/dev/null || cat > "$APP_DIR/.env.prod" <<'ENVEOF'
# Django
DEBUG=False
DJANGO_SECRET_KEY=CHANGE_ME
ALLOWED_HOSTS=b2vec.org
CSRF_TRUSTED_ORIGINS=https://b2vec.org

# Database (PostgreSQL on host)
DB_NAME=b2vec
DB_USER=b2vec
DB_PASSWORD=CHANGE_ME
DB_HOST=host.docker.internal
DB_PORT=5432

# Ollama (on host)
OLLAMA_BASE_URL=http://host.docker.internal:11435
ENVEOF
    echo ">>> Edit $APP_DIR/.env.prod before continuing, then re-run this script."
    exit 1
else
    echo "[2/6] .env.prod already exists, skipping."
fi

# ── 3. Configure PostgreSQL for Docker connections ───────────────
echo "[3/6] Checking PostgreSQL configuration..."
PG_HBA=$(find /etc/postgresql -name pg_hba.conf 2>/dev/null | head -1)
if [ -n "$PG_HBA" ]; then
    if ! grep -q "172.16.0.0/12" "$PG_HBA"; then
        echo "Adding Docker subnet to pg_hba.conf..."
        echo "# Docker containers" >> "$PG_HBA"
        echo "host    all    all    172.16.0.0/12    md5" >> "$PG_HBA"
        systemctl reload postgresql
        echo "PostgreSQL reloaded."
    else
        echo "Docker subnet already in pg_hba.conf."
    fi
else
    echo "WARNING: pg_hba.conf not found. Make sure PostgreSQL accepts connections from 172.16.0.0/12."
fi

# ── 4. Obtain SSL certificate ───────────────────────────────────
CERT_PATH="/var/lib/docker/volumes/$(basename "$APP_DIR")_certbot_conf/_data/live/$DOMAIN/fullchain.pem"
if [ ! -f "$CERT_PATH" ]; then
    echo "[4/6] Obtaining SSL certificate..."
    # Stop anything on port 80
    $COMPOSE down 2>/dev/null || true
    # Run certbot standalone (needs port 80 free)
    docker run --rm -p 80:80 \
        -v "$(basename "$APP_DIR")_certbot_conf:/etc/letsencrypt" \
        -v "$(basename "$APP_DIR")_certbot_www:/var/www/certbot" \
        certbot/certbot certonly --standalone \
        -d "$DOMAIN" --non-interactive --agree-tos \
        -m "admin@$DOMAIN"
else
    echo "[4/6] SSL certificate already exists, skipping."
fi

# ── 5. Build and start services ──────────────────────────────────
echo "[5/6] Building and starting services..."
$COMPOSE build
$COMPOSE up -d

# ── 6. Run migrations ────────────────────────────────────────────
echo "[6/6] Running Django migrations..."
$COMPOSE exec web python manage.py migrate --noinput
$COMPOSE exec web python manage.py collectstatic --noinput

echo ""
echo "=== Deployment complete ==="
echo "Verify: curl https://$DOMAIN"
echo "Logs:   $COMPOSE logs -f"
echo "Status: $COMPOSE ps"
