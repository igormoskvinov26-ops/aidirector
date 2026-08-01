#!/bin/bash
echo "=== РублЪ AI Director ==="
echo ""

# Kill old processes
pkill -f "uvicorn app.main" 2>/dev/null
pkill -f "vite" 2>/dev/null
sleep 1

# Start backend
cd "$(dirname "$0")/backend"
echo "[1/2] Запуск бэкенда на порту 8000..."
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!
sleep 2

# Check backend
if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "       Бэкенд: OK (http://localhost:8000)"
else
    echo "       Бэкенд: ошибка запуска"
    exit 1
fi

# Start frontend
cd "$(dirname "$0")/frontend"
echo "[2/2] Запуск фронтенда на порту 3000..."
npx vite --host 0.0.0.0 --port 3000 &
FRONTEND_PID=$!
sleep 3

echo ""
echo "==============================================="
echo "  ГОТОВО!"
echo "  Открой в браузере: http://localhost:3000"
echo ""
echo "  Остановка: kill $BACKEND_PID $FRONTEND_PID"
echo "==============================================="

wait
