#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Error: '$1' is required but not installed." >&2
    exit 1
  fi
}

require_cmd docker

if docker compose version >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  DOCKER_COMPOSE_CMD=(docker-compose)
else
  echo "Error: docker compose plugin or docker-compose binary is required." >&2
  exit 1
fi

random_password() {
  if command -v openssl >/dev/null 2>&1; then
    openssl rand -base64 24 | tr -d '\n'
  else
    python - <<'PY'
import secrets
import string
alphabet = string.ascii_letters + string.digits + string.punctuation
print(''.join(secrets.choice(alphabet) for _ in range(32)))
PY
  fi
}

echo "--- Ben Bot setup wizard ---"
read -rp "Telegram bot token: " BOT_TOKEN
if [[ -z "$BOT_TOKEN" ]]; then
  echo "Bot token is required." >&2
  exit 1
fi

read -rp "Owner user IDs (comma separated): " OWNER_IDS
if [[ -z "$OWNER_IDS" ]]; then
  echo "At least one owner user ID is required." >&2
  exit 1
fi

read -rp "Require channel subscription by default? [Y/n]: " REQUIRE_SUBSCRIPTION
REQUIRE_SUBSCRIPTION=${REQUIRE_SUBSCRIPTION:-Y}
if [[ "$REQUIRE_SUBSCRIPTION" =~ ^[Yy]$ ]]; then
  REQUIRE_SUBSCRIPTION=true
else
  REQUIRE_SUBSCRIPTION=false
fi

read -rp "Required channel usernames (comma separated, optional): " REQUIRED_CHANNELS_INPUT
if [[ -n "$REQUIRED_CHANNELS_INPUT" ]]; then
  REQUIRED_CHANNELS="['${REQUIRED_CHANNELS_INPUT//,/","}' ]"
else
  REQUIRED_CHANNELS="[]"
fi
read -rp "Payment provider token (optional): " PAYMENT_PROVIDER_TOKEN
read -rp "Payment currency [USD]: " PAYMENT_CURRENCY
PAYMENT_CURRENCY=${PAYMENT_CURRENCY:-USD}
read -rp "Invoice payment timeout in minutes [30]: " INVOICE_TIMEOUT
INVOICE_TIMEOUT=${INVOICE_TIMEOUT:-30}

DB_PASSWORD=$(random_password)
DB_ROOT_PASSWORD=$(random_password)

ENV_FILE="$PROJECT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  BACKUP_FILE="$ENV_FILE.bak.$(date +%Y%m%d%H%M%S)"
  echo "Existing .env found. Backing up to $BACKUP_FILE"
  cp "$ENV_FILE" "$BACKUP_FILE"
fi

cat > "$ENV_FILE" <<EOF
BOT_TOKEN=$BOT_TOKEN
BOT_OWNER_USER_IDS=$OWNER_IDS

DB_HOST=mariadb
DB_PORT=3306
DB_USER=ben
DB_PASSWORD=$DB_PASSWORD
DB_NAME=ben_bot
DB_ROOT_PASSWORD=$DB_ROOT_PASSWORD

LOG_LEVEL=INFO

REQUIRE_SUBSCRIPTION_DEFAULT=$REQUIRE_SUBSCRIPTION
REQUIRED_CHANNELS_DEFAULT=$REQUIRED_CHANNELS
MEMBERSHIP_CACHE_TTL=300

PAYMENT_PROVIDER_TOKEN=$PAYMENT_PROVIDER_TOKEN
PAYMENT_CURRENCY=$PAYMENT_CURRENCY
INVOICE_PAYMENT_TIMEOUT_MINUTES=$INVOICE_TIMEOUT
EOF

echo "Generated .env with random database credentials."

echo "Building and starting containers..."
"${DOCKER_COMPOSE_CMD[@]}" up -d --build

echo "Setup complete. Containers are running."
