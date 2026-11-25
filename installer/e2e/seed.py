# Запускается внутри контейнера rubl_director: 30 «потерянных» клиентов в очереди.
import asyncio, datetime, sys
from app.database import async_session
from app.models.models import Client, Employee, Visit
from app.services import client_base

ПРЕФИКС = sys.argv[1] if len(sys.argv) > 1 else "Клиент"
СМЕЩЕНИЕ = int(sys.argv[2]) if len(sys.argv) > 2 else 0

async def main():
    async with async_session() as s:
        e = Employee(yclients_id=900000 + СМЕЩЕНИЕ, name=f"Мастер {СМЕЩЕНИЕ}")
        s.add(e)
        await s.flush()
        for i in range(1, 31):
            c = Client(yclients_id=500000 + СМЕЩЕНИЕ + i, name=f"{ПРЕФИКС} {i:02d}",
                       phone=f"+7999{СМЕЩЕНИЕ + i:07d}")
            s.add(c)
            await s.flush()
            когда = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=100 + i)
            s.add(Visit(yclients_id=2_100_000_000 + СМЕЩЕНИЕ + i, client_id=c.id, employee_id=e.id,
                        datetime=когда, status="completed", total_amount=2000, paid_amount=2000))
        await s.commit()
        print(await client_base.refresh_tasks(s))

asyncio.run(main())
