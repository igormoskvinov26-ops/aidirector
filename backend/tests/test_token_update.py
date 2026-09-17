"""Скрипт обновления токена правит .env — файл с паролями владельца.

Здесь проверяется именно правка файла, а не обращение к YCLIENTS: сеть в
тестах не нужна, а вот испорченный .env означает потерянные пароли, которые
человек придумывал руками и восстановить их неоткуда.
"""

import importlib.util
import os
import stat
from pathlib import Path

import pytest

КОРЕНЬ = Path(__file__).resolve().parent.parent.parent
СКРИПТ = КОРЕНЬ / "scripts" / "обновить-токен.py"


def загрузить():
    спец = importlib.util.spec_from_file_location("обновить_токен", СКРИПТ)
    модуль = importlib.util.module_from_spec(спец)
    спец.loader.exec_module(модуль)
    return модуль


@pytest.fixture(scope="module")
def скрипт():
    return загрузить()


ОБРАЗЕЦ = """# Настройки
YCLIENTS_PARTNER_TOKEN=partner-abc
YCLIENTS_COMPANY_ID=2036703
YCLIENTS_USER_TOKEN=старый-токен

# Старый аккаунт — только для сверки
YCLIENTS_OLD_USER_TOKEN=токен-прошлого-аккаунта

OWNER_PASSWORD=nozhnicy-rascheska-fen
MASTER_ACCOUNTS=[]
"""


# --------------------------------------------------------------------------- #
# Чтение
# --------------------------------------------------------------------------- #


def test_читает_значение(скрипт, tmp_path):
    файл = tmp_path / ".env"
    файл.write_text(ОБРАЗЕЦ, encoding="utf-8")
    assert скрипт.прочитать(файл, "YCLIENTS_USER_TOKEN") == "старый-токен"


def test_не_путает_похожие_ключи(скрипт, tmp_path):
    """YCLIENTS_OLD_USER_TOKEN — другая строка, и брать её нельзя."""
    файл = tmp_path / ".env"
    файл.write_text(ОБРАЗЕЦ, encoding="utf-8")
    assert скрипт.прочитать(файл, "YCLIENTS_OLD_USER_TOKEN") == "токен-прошлого-аккаунта"
    assert скрипт.прочитать(файл, "YCLIENTS_USER_TOKEN") == "старый-токен"


def test_отбрасывает_комментарий_после_пробела(скрипт, tmp_path):
    """Так же, как загрузчик настроек приложения. Иначе проверялось бы одно,
    а в дело шло другое."""
    файл = tmp_path / ".env"
    файл.write_text("YCLIENTS_PARTNER_TOKEN=abc123 # выдан в сентябре\n", encoding="utf-8")
    assert скрипт.прочитать(файл, "YCLIENTS_PARTNER_TOKEN") == "abc123"


def test_решётка_без_пробела_остаётся(скрипт, tmp_path):
    файл = tmp_path / ".env"
    файл.write_text("YCLIENTS_PARTNER_TOKEN=abc#123\n", encoding="utf-8")
    assert скрипт.прочитать(файл, "YCLIENTS_PARTNER_TOKEN") == "abc#123"


def test_снимает_кавычки(скрипт, tmp_path):
    файл = tmp_path / ".env"
    файл.write_text('YCLIENTS_USER_TOKEN="в кавычках"\n', encoding="utf-8")
    assert скрипт.прочитать(файл, "YCLIENTS_USER_TOKEN") == "в кавычках"


def test_нет_строки_нет_значения(скрипт, tmp_path):
    файл = tmp_path / ".env"
    файл.write_text("A=1\n", encoding="utf-8")
    assert скрипт.прочитать(файл, "YCLIENTS_USER_TOKEN") == ""


# --------------------------------------------------------------------------- #
# Правка
# --------------------------------------------------------------------------- #


def test_меняет_только_свою_строку(скрипт):
    новый = скрипт.подменить_строку(ОБРАЗЕЦ, "YCLIENTS_USER_TOKEN", "новый-токен")
    assert "YCLIENTS_USER_TOKEN=новый-токен\n" in новый
    assert "старый-токен" not in новый
    # Всё остальное — байт в байт.
    было = [s for s in ОБРАЗЕЦ.splitlines() if not s.startswith("YCLIENTS_USER_TOKEN=")]
    стало = [s for s in новый.splitlines() if not s.startswith("YCLIENTS_USER_TOKEN=")]
    assert было == стало


def test_не_трогает_соседний_похожий_ключ(скрипт):
    новый = скрипт.подменить_строку(ОБРАЗЕЦ, "YCLIENTS_USER_TOKEN", "новый-токен")
    assert "YCLIENTS_OLD_USER_TOKEN=токен-прошлого-аккаунта" in новый


def test_сохраняет_комментарии_и_порядок(скрипт):
    новый = скрипт.подменить_строку(ОБРАЗЕЦ, "YCLIENTS_USER_TOKEN", "новый-токен")
    assert новый.startswith("# Настройки\n")
    assert "# Старый аккаунт — только для сверки" in новый
    assert len(новый.splitlines()) == len(ОБРАЗЕЦ.splitlines())


def test_дописывает_когда_строки_нет(скрипт):
    новый = скрипт.подменить_строку("A=1\n", "YCLIENTS_USER_TOKEN", "новый")
    assert новый == "A=1\nYCLIENTS_USER_TOKEN=новый\n"


def test_дописывает_когда_файл_без_перевода_в_конце(скрипт):
    новый = скрипт.подменить_строку("A=1", "YCLIENTS_USER_TOKEN", "новый")
    assert новый == "A=1\nYCLIENTS_USER_TOKEN=новый\n"


def test_сохраняет_переводы_строк_windows(скрипт):
    """Файл мог быть отредактирован на Windows. Смешивать переводы нельзя."""
    исходник = "A=1\r\nYCLIENTS_USER_TOKEN=старый\r\nB=2\r\n"
    новый = скрипт.подменить_строку(исходник, "YCLIENTS_USER_TOKEN", "новый")
    assert новый == "A=1\r\nYCLIENTS_USER_TOKEN=новый\r\nB=2\r\n"


def test_комментарий_с_таким_же_именем_не_считается_строкой(скрипт):
    исходник = "#YCLIENTS_USER_TOKEN=это комментарий\nYCLIENTS_USER_TOKEN=живой\n"
    новый = скрипт.подменить_строку(исходник, "YCLIENTS_USER_TOKEN", "новый")
    assert "#YCLIENTS_USER_TOKEN=это комментарий" in новый
    assert "YCLIENTS_USER_TOKEN=новый\n" in новый


def test_меняет_только_первое_вхождение(скрипт):
    исходник = "YCLIENTS_USER_TOKEN=первый\nYCLIENTS_USER_TOKEN=второй\n"
    новый = скрипт.подменить_строку(исходник, "YCLIENTS_USER_TOKEN", "новый")
    assert новый == "YCLIENTS_USER_TOKEN=новый\nYCLIENTS_USER_TOKEN=второй\n"


# --------------------------------------------------------------------------- #
# Запись
# --------------------------------------------------------------------------- #


def test_копия_совпадает_с_прежним_файлом(скрипт, tmp_path):
    файл = tmp_path / ".env"
    файл.write_text(ОБРАЗЕЦ, encoding="utf-8")
    было = файл.read_bytes()

    копия = скрипт.сохранить(файл, скрипт.подменить_строку(ОБРАЗЕЦ, "YCLIENTS_USER_TOKEN", "н"))

    assert копия.read_bytes() == было
    assert файл.read_text(encoding="utf-8") != ОБРАЗЕЦ


def test_права_после_записи_только_владельцу(скрипт, tmp_path):
    """В файле пароли. Читать его не должен никто, кроме хозяина компьютера."""
    файл = tmp_path / ".env"
    файл.write_text(ОБРАЗЕЦ, encoding="utf-8")
    os.chmod(файл, 0o644)

    копия = скрипт.сохранить(файл, ОБРАЗЕЦ)

    assert stat.S_IMODE(файл.stat().st_mode) == 0o600
    assert stat.S_IMODE(копия.stat().st_mode) == 0o600


def test_пароли_владельца_переживают_правку(скрипт, tmp_path):
    файл = tmp_path / ".env"
    файл.write_text(ОБРАЗЕЦ, encoding="utf-8")
    скрипт.сохранить(файл, скрипт.подменить_строку(ОБРАЗЕЦ, "YCLIENTS_USER_TOKEN", "н"))
    assert "OWNER_PASSWORD=nozhnicy-rascheska-fen" in файл.read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Решение: записывать или нет
#
# Здесь проверяется не сеть, а поведение при разных ответах YCLIENTS. Токен
# без доступа к филиалу так же бесполезен, как прежний, и подменять одно на
# другое молча — значит спрятать причину от человека.
# --------------------------------------------------------------------------- #


def _подготовить(скрипт, tmp_path, monkeypatch, ответы):
    файл = tmp_path / ".env"
    файл.write_text(ОБРАЗЕЦ, encoding="utf-8")
    monkeypatch.setattr("builtins.input", lambda *_: "79990000000")
    monkeypatch.setattr(скрипт.getpass, "getpass", lambda *_: "пароль-от-yclients")
    monkeypatch.setattr(скрипт.sys, "argv", ["обновить-токен.py", str(файл)])

    def подделка(путь, партнёр, пользователь="", тело=None):
        for образец, ответ in ответы:
            if образец in путь:
                return ответ
        raise AssertionError(f"неожиданный запрос {путь}")

    monkeypatch.setattr(скрипт, "запрос", подделка)
    return файл


ВЫДАН = (200, {"success": True, "data": {"user_token": "свежий-токен", "name": "Игорь"}})


def test_записывает_когда_всё_сошлось(скрипт, tmp_path, monkeypatch):
    файл = _подготовить(скрипт, tmp_path, monkeypatch, [
        ("/auth", ВЫДАН),
        ("/companies", (200, {"data": [{"id": 2036703}]})),
        ("/staff", (200, {"data": [{"id": 1}, {"id": 2}]})),
    ])
    скрипт.main()
    assert "YCLIENTS_USER_TOKEN=свежий-токен" in файл.read_text(encoding="utf-8")


def test_не_записывает_когда_филиалов_нет_вовсе(скрипт, tmp_path, monkeypatch):
    """Ровно тот случай, что нашёлся на живой установке: success, но data пуст."""
    файл = _подготовить(скрипт, tmp_path, monkeypatch, [
        ("/auth", ВЫДАН),
        ("/companies", (200, {"success": True, "data": [], "meta": []})),
    ])
    with pytest.raises(SystemExit) as выход:
        скрипт.main()
    assert выход.value.code == 1
    assert файл.read_text(encoding="utf-8") == ОБРАЗЕЦ


def test_записывает_но_предупреждает_о_чужом_филиале(скрипт, tmp_path, monkeypatch):
    """Токен рабочий, а номер филиала не тот — править надо COMPANY_ID."""
    файл = _подготовить(скрипт, tmp_path, monkeypatch, [
        ("/auth", ВЫДАН),
        ("/companies", (200, {"data": [{"id": 999999}]})),
    ])
    with pytest.raises(SystemExit) as выход:
        скрипт.main()
    assert выход.value.code == 2
    assert "YCLIENTS_USER_TOKEN=свежий-токен" in файл.read_text(encoding="utf-8")


def test_не_записывает_когда_токен_не_выдан(скрипт, tmp_path, monkeypatch):
    файл = _подготовить(скрипт, tmp_path, monkeypatch, [
        ("/auth", (401, {"success": False, "data": None,
                         "meta": {"message": "Неверный логин или пароль"}})),
    ])
    with pytest.raises(SystemExit) as выход:
        скрипт.main()
    assert выход.value.code == 1
    assert файл.read_text(encoding="utf-8") == ОБРАЗЕЦ


def test_токен_не_попадает_на_экран(скрипт, tmp_path, monkeypatch, capsys):
    """Токен — такой же секрет, как пароль."""
    _подготовить(скрипт, tmp_path, monkeypatch, [
        ("/auth", ВЫДАН),
        ("/companies", (200, {"data": [{"id": 2036703}]})),
        ("/staff", (200, {"data": [{"id": 1}]})),
    ])
    скрипт.main()
    assert "свежий-токен" not in capsys.readouterr().out
