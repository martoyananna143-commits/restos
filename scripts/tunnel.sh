#!/bin/bash
# Скрипт для запуска SSH туннелей через serveo.net
# Использование: 
#   ./scripts/tunnel.sh frontend  - туннель для Dioxus (8080)
#   ./scripts/tunnel.sh api       - туннель для FastAPI (8000)
#   ./scripts/tunnel.sh [port]    - туннель для указанного порта

MODE=${1:-frontend}

case $MODE in
    frontend|f|8080)
        PORT=8080
        NAME="Frontend (Dioxus)"
        ENV_VAR="WEBAPP_BASE_URL"
        ;;
    api|a|8000)
        PORT=8000
        NAME="API (FastAPI)"
        ENV_VAR="WEBAPP_API_URL"
        ;;
    *)
        PORT=$MODE
        NAME="Custom"
        ENV_VAR="???"
        ;;
esac

echo "🚀 Запуск SSH туннеля через serveo.net..."
echo "📡 Сервис: $NAME"
echo "📡 Локальный порт: $PORT"
echo ""
echo "⚠️  ВАЖНО: Скопируйте полученный URL в .env файл:"
echo "   $ENV_VAR=https://xxxxx.serveo.net"
echo ""
echo "📝 Для двух туннелей запустите в разных терминалах:"
echo "   ./scripts/tunnel.sh frontend"
echo "   ./scripts/tunnel.sh api"
echo ""
echo "Нажмите Ctrl+C для остановки туннеля"
echo "----------------------------------------"

ssh -R 80:localhost:$PORT serveo.net
