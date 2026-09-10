# РублЪ — AI Director

**AI-powered управленческая система для барбершопа «РублЪ».**

## Стек

| Слой | Технологии |
|------|-----------|
| Backend | Python 3.11+, FastAPI, SQLAlchemy 2, Pydantic, httpx, loguru |
| Database | PostgreSQL 16 (Docker) |
| Frontend | React 19, Vite, TypeScript, Tailwind CSS, Recharts |
| Отчёты | Внутренняя логика (без внешних API) |
| Data | YCLIENTS API (REST, партнёрский токен) |

## Быстрый старт

### 1. Клонировать и настроить

```bash
cp .env.example .env
# Заполнить .env актуальными ключами
```

### 2. Запустить PostgreSQL

```bash
docker compose -f docker/docker-compose.yml up -d postgres
```

### 3. Запустить Backend

```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### 4. Запустить Frontend

```bash
cd frontend
npm install
npm run dev
```

### 5. Синхронизировать данные

```bash
curl -X POST http://localhost:8000/api/sync/trigger
curl -X POST http://localhost:8000/api/sync/calculate-kpi?days_back=30
```

### 6. Открыть дашборд

http://localhost:3000

## API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| GET | `/health` | Статус сервера |
| GET | `/api/info` | Информация о системе |
| GET | `/api/dashboard/` | Дашборд (30 дней) |
| GET | `/api/dashboard/range` | Дашборд за период |
| GET | `/api/employees/` | Список мастеров |
| GET | `/api/employees/{id}` | Детали мастера |
| GET | `/api/sync/status` | Статус синхронизации |
| POST | `/api/sync/trigger` | Запустить синхронизацию |
| POST | `/api/sync/calculate-kpi` | Пересчитать KPI |
| POST | `/api/ai/report` | AI-отчёт за период |
| GET | `/api/ai/quick` | Быстрый AI-анализ |

## Структура проекта

```
ai-director/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── yclients.py          # YCLIENTS REST client
│   │   │   └── routes/
│   │   │       ├── dashboard.py     # Дашборд
│   │   │       ├── employees.py     # Мастера
│   │   │       ├── sync.py          # Синхронизация
│   │   │       └── ai.py            # AI-отчёты
│   │   ├── models/models.py         # SQLAlchemy модели
│   │   ├── repositories/            # Data access layer
│   │   ├── services/
│   │   │   ├── sync.py              # Синхронизация данных
│   │   │   ├── kpi.py               # Расчёт KPI
│   │   │   └── ai.py                # AI-генератор отчётов
│   │   ├── schemas/schemas.py       # Pydantic схемы
│   │   ├── config.py                # Конфигурация
│   │   ├── database.py              # SQLAlchemy engine
│   │   └── main.py                  # FastAPI app
│   ├── alembic/                     # Миграции
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx                  # Дашборд
│   │   ├── main.tsx                 # Entry point
│   │   └── index.css                # Tailwind + тема
│   └── vite.config.ts
├── docker/
│   └── docker-compose.yml           # PostgreSQL + backend + frontend
├── database/
│   └── init.sql
├── .env.example
└── README.md
```

## Ключевые метрики

- Выручка (общая, по дням, по мастерам)
- Средний чек
- Новые / повторные клиенты
- Возвращаемость (Retention Rate)
- LTV (пожизненная ценность)
- Доля отмен и неявок
- Продажи косметики
- Загрузка мастеров

## Отчёты директора

Система генерирует управленческие отчёты внутренними правилами (без внешних
API и платных сервисов):

1. **Главные выводы** — ключевые инсайты из метрик
2. **Риски** — что может пойти не так
3. **Возможности** — точки роста
4. **Действия на завтра** — конкретные шаги

Пример запроса:
```bash
curl -X POST http://localhost:8000/api/ai/report \
  -H "Content-Type: application/json" \
  -d '{"period_from": "2026-07-01", "period_to": "2026-07-31"}'
```
