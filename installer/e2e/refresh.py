# Пересборка очереди — то же, что делает каждая выгрузка из YCLIENTS.
import asyncio
from app.database import async_session
from app.services import client_base

async def main():
    async with async_session() as s:
        print(await client_base.refresh_tasks(s))

asyncio.run(main())
