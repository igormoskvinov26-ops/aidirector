# Пульт «РублЪ»

Программа управления барбершопом «РублЪ»: FastAPI + PostgreSQL + React в Docker, данные из YCLIENTS.
Работает локально на компьютере салона; имена и телефоны клиентов не покидают этот компьютер.

- Для разработчиков и поддержки: [docs/РАЗРАБОТКА.md](docs/РАЗРАБОТКА.md)
- Установка для пользователя: [local/УСТАНОВКА.md](local/УСТАНОВКА.md)
- Общий сервер: [hub/README.md](hub/README.md)
- История решений и ТЗ: [docs/history/](docs/history/)

Быстрый старт: `cd backend && uv sync && uv run pytest -q`, `cd frontend && npm ci && npm run dev`.
Сборка пакета обновления: `python3 scripts/build_package.py <версия> <папка>`.
