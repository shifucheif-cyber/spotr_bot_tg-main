#!/usr/bin/env bash
# =============================================================
# Автоматическая настройка сервера Ubuntu 22.04 для spotr_bot_tg
# Запуск: chmod +x setup_server.sh && sudo ./setup_server.sh
# =============================================================
set -euo pipefail

GREEN='\033[0;32m'
NC='\033[0m'

echo -e "${GREEN}[1/6] Установка системных зависимостей...${NC}"
apt update && apt install -y python3-pip python3-venv postgresql postgresql-contrib libpq-dev

echo -e "${GREEN}[2/6] Запуск PostgreSQL...${NC}"
systemctl enable postgresql
systemctl start postgresql

DB_USER="spotr_bot"
DB_NAME="spotr_bot_db"

echo -e "${GREEN}[3/6] Создание пользователя и БД PostgreSQL...${NC}"
read -sp "Введите пароль для пользователя PostgreSQL '${DB_USER}': " DB_PASS
echo

# Создать пользователя (если не существует)
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -q 1 \
    || sudo -u postgres psql -c "CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';"

# Создать БД (если не существует)
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 \
    || sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"

echo -e "${GREEN}[4/6] Настройка виртуального окружения Python...${NC}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${SCRIPT_DIR}"

python3 -m venv venv
./venv/bin/python -m pip install -U pip
./venv/bin/python -m pip install -r requirements.txt

echo -e "${GREEN}[5/6] Настройка .env...${NC}"
if [ ! -f .env ]; then
    cp .env.example .env
    echo "Создан .env из .env.example"
fi

DATABASE_URL="postgresql://${DB_USER}:${DB_PASS}@localhost:5432/${DB_NAME}"

set_env_var() {
    local key="$1" val="$2"
    if grep -q "^${key}=" .env 2>/dev/null; then
        sed -i "s|^${key}=.*|${key}=${val}|" .env
    elif grep -q "^# *${key}=" .env 2>/dev/null; then
        sed -i "s|^# *${key}=.*|${key}=${val}|" .env
    else
        echo "${key}=${val}" >> .env
    fi
}

set_env_var "DB_BACKEND" "postgres"
set_env_var "DATABASE_URL" "${DATABASE_URL}"

echo -e "${GREEN}[6/6] Preflight-проверка...${NC}"
./venv/bin/python preflight_check.py

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}  Сервер готов! Запуск бота:${NC}"
echo -e "${GREEN}  ./venv/bin/python bot.py${NC}"
echo -e "${GREEN}========================================${NC}"
