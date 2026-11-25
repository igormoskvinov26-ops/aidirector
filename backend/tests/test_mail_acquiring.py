"""Отчёты банка из почты: что Пульт забирает и что запоминает."""

import email.message
import json
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.models import AppSetting
from app.services import acquiring, configuration, mail_acquiring


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


def _письмо(имя: str | None, тело: bytes = b"col;sum") -> bytes:
    msg = email.message.EmailMessage()
    msg["Subject"] = "Отчёт за вчера"
    msg.set_content("Отчёт во вложении")
    if имя:
        msg.add_attachment(тело, maintype="application", subtype="octet-stream", filename=имя)
    return msg.as_bytes()


def test_берём_только_таблицы_и_читаем_русские_имена():
    """Картинка подписи во вложении — не отчёт, её брать нельзя."""
    vl = mail_acquiring.вложения(_письмо("Отчёт за 05.10.xlsx"))
    assert vl and vl[0][0] == "Отчёт за 05.10.xlsx"
    assert mail_acquiring.вложения(_письмо("logo.png")) == []
    assert mail_acquiring.вложения(_письмо(None)) == []


def test_имена_папок_ходят_туда_и_обратно():
    for имя in ("INBOX", "Банк", "Отчёты/Эквайринг", "A&B"):
        assert mail_acquiring.из_utf7(mail_acquiring.в_utf7(имя)) == имя
    assert mail_acquiring.в_utf7("Банк") == "&BBEEMAQ9BDo-"


class ФейковыйIMAP:
    """Ровно то, чем пользуется собрать(): select, response, uid, list."""

    def __init__(self, письма: dict[int, bytes], валидность: int = 7, папка: str = "&BBEEMAQ9BDo-"):
        self.письма, self.валидность, self.папка = письма, валидность, папка
        self.readonly = None

    def select(self, папка, readonly=False):
        self.readonly = readonly
        return ("OK", [b"3"]) if папка == self.папка else ("NO", [b"no such folder"])

    def response(self, _):
        return ("UIDVALIDITY", [str(self.валидность).encode()])

    def uid(self, команда, *аргументы):
        if команда == "search":
            # как настоящий сервер: на «UID n:*» отдаём и последнее письмо тоже
            return "OK", [" ".join(str(u) for u in sorted(self.письма)).encode()]
        номер = int(аргументы[0])
        return "OK", [(b"1 (RFC822 {})", self.письма[номер])]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "|" "&BBEEMAQ9BDo-"']


def test_собираем_только_новые_письма():
    связь = ФейковыйIMAP({10: _письмо("a.csv"), 11: _письмо("b.csv"), 12: _письмо("c.csv")})
    письма, новое = mail_acquiring.собрать(связь, "Банк", {"uidvalidity": 7, "last_uid": 11})
    assert len(письма) == 1 and новое == {"uidvalidity": 7, "last_uid": 12}
    assert связь.readonly is True  # письма в ящике не трогаем

    # Ничего нового: номер последнего письма не откатывается назад.
    письма, новое = mail_acquiring.собрать(связь, "Банк", {"uidvalidity": 7, "last_uid": 12})
    assert письма == [] and новое["last_uid"] == 12


def test_папку_пересоздали_читаем_заново():
    связь = ФейковыйIMAP({1: _письмо("a.csv")}, валидность=9)
    письма, новое = mail_acquiring.собрать(связь, "Банк", {"uidvalidity": 7, "last_uid": 99})
    assert len(письма) == 1 and новое == {"uidvalidity": 9, "last_uid": 1}


def test_чужая_папка_объясняет_какие_есть():
    связь = ФейковыйIMAP({1: _письмо("a.csv")})
    with pytest.raises(RuntimeError, match="Банк"):
        mail_acquiring.собрать(связь, "Эквайринг", {})


@pytest.mark.asyncio
async def test_забрать_грузит_отчёт_и_запоминает_просмотр(session, monkeypatch):
    monkeypatch.setattr(configuration, "_управляемые", {
        "MAIL_LOGIN": "rubl@yandex.ru", "MAIL_PASSWORD": "app-pass", "MAIL_FOLDER": "Банк",
    })
    monkeypatch.setattr(configuration, "изолирован", False)
    связь = ФейковыйIMAP({5: _письмо("Отчёт.csv")})
    monkeypatch.setattr(mail_acquiring, "_подключиться", lambda *a: связь)
    monkeypatch.setattr(связь, "logout", lambda: None, raising=False)

    async def сохранить(_s, содержимое, имя):
        assert имя == "Отчёт.csv"
        return {"days": 1, "rows": 3}

    monkeypatch.setattr(acquiring, "сохранить", сохранить)

    итог = await mail_acquiring.забрать(session)
    assert итог["ok"] and "Загружено отчётов: 1" in итог["message"]
    assert итог["last_uid"] == 5 and итог["configured"]
    строка = await session.get(AppSetting, mail_acquiring.СОСТОЯНИЕ)
    assert json.loads(строка.value)["last_uid"] == 5


@pytest.mark.asyncio
async def test_нечитаемое_вложение_не_крутится_по_кругу(session, monkeypatch):
    """Письмо считается просмотренным даже когда файл не разобрался."""
    monkeypatch.setattr(configuration, "_управляемые", {
        "MAIL_LOGIN": "rubl@yandex.ru", "MAIL_PASSWORD": "app-pass", "MAIL_FOLDER": "Банк",
    })
    связь = ФейковыйIMAP({5: _письмо("Отчёт.csv")})
    monkeypatch.setattr(mail_acquiring, "_подключиться", lambda *a: связь)
    monkeypatch.setattr(связь, "logout", lambda: None, raising=False)

    async def сохранить(*_a):
        raise ValueError("Не нашёл строку с заголовками")

    monkeypatch.setattr(acquiring, "сохранить", сохранить)
    итог = await mail_acquiring.забрать(session)
    assert итог["ok"] is False and "загрузите кнопкой" in итог["message"]
    assert итог["last_uid"] == 5


@pytest.mark.asyncio
async def test_почта_не_настроена_молчит(session, monkeypatch):
    monkeypatch.setattr(configuration, "_управляемые", {})
    monkeypatch.setattr(configuration, "изолирован", True)  # и .env не подставляется
    итог = await mail_acquiring.забрать(session)
    assert итог["configured"] is False and "checked_at" not in итог


def test_отказ_входа_объясняет_что_делать():
    """Сервер отвечает байтами, и прежде в интерфейс попадало b'[AUTH...]'."""
    сбой = Exception(b"[AUTHENTICATIONFAILED] LOGIN invalid credentials or IMAP is disabled")
    текст = mail_acquiring._текст_сбоя(сбой)
    assert not текст.startswith("b'")
    assert "пароль приложения" in текст and "Почтовые программы" in текст
    # Прочие ошибки пересказывать не надо — сервер объясняет лучше.
    assert mail_acquiring._текст_сбоя(Exception(b"NO such folder")) == "NO such folder"
