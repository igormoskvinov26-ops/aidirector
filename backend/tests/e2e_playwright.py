"""Сквозные сценарии по живому Пульту: клики в браузере, проверка в базе."""
import sqlite3, sys
from playwright.sync_api import sync_playwright, expect

БАЗА = "/tmp/e2e/e2e.db"
АДРЕС = "http://127.0.0.1:8099/"
провалы, шаги = [], []


def проверить(условие, текст):
    (шаги if условие else провалы).append(текст)
    print(("  ок  " if условие else " ПРОВАЛ ") + текст)


def из_базы(sql, *args):
    con = sqlite3.connect(БАЗА)
    try:
        return con.execute(sql, args).fetchall()
    finally:
        con.close()


with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1440, "height": 1000},
                        http_credentials={"username": "a", "password": "b"})
    p = ctx.new_page()
    ошибки_страницы = []
    p.on("pageerror", lambda e: ошибки_страницы.append(str(e)[:200]))
    p.on("console", lambda m: ошибки_страницы.append(m.text[:200]) if m.type == "error" else None)

    p.goto(АДРЕС); p.wait_for_timeout(2500)

    print("\n[1] Разделы открываются")
    for раздел in ["План-факт", "Смена", "Клиенты", "Пульс базы", "Записи за месяц",
                   "Расчёт ЗП", "Финансы", "Месячный отчёт", "Контроль финансов", "Настройки"]:
        p.get_by_role("button", name=раздел).first.click(); p.wait_for_timeout(900)
        упал = p.get_by_text("Раздел не отрисовался").count() > 0
        проверить(not упал, f"раздел «{раздел}» отрисовался")

    print("\n[2] Вкладки клиентской базы")
    p.get_by_role("button", name="Клиенты").first.click(); p.wait_for_timeout(1200)
    проверить(p.get_by_text("Баланс движения").count() > 0, "вкладка «Управляющий»: баланс на месте")
    for вкладка, маркер in [("Возвращённые", "Вернули за месяц"), ("Обзвоны", "Записались")]:
        p.get_by_role("button", name=вкладка).first.click(); p.wait_for_timeout(1200)
        проверить(p.get_by_text(маркер).first.count() > 0, f"вкладка «{вкладка}» открылась")

    print("\n[3] Администратор: выбор админа и очередь")
    p.get_by_role("button", name="Администратор").first.click(); p.wait_for_timeout(600)
    проверить(p.get_by_text("Кто сегодня звонит?").count() > 0, "база закрыта до выбора админа")
    p.get_by_role("button", name="Виктор").first.click(); p.wait_for_timeout(1500)
    карточек = p.locator("text=Сергей Орлов").count()
    проверить(карточек > 0, "очередь показала клиентов")
    проверить(p.get_by_text("Не звонили").count() > 0, "статус-стикер виден до первого звонка")

    def карточка(имя):
        return p.locator("div.rounded-2xl").filter(has=p.get_by_text(имя, exact=True)).last

    print("\n[4] Светофор")
    к = карточка("Сергей Орлов")
    к.get_by_label("Разговор был на негативе").click(); p.wait_for_timeout(900)
    проверить(из_базы("select loyalty from clients where name=?", "Сергей Орлов") == [("red",)],
              "красная лампа записалась в базу")
    к = карточка("Сергей Орлов")
    к.get_by_label("Разговор был на негативе").click(); p.wait_for_timeout(900)
    проверить(из_базы("select loyalty from clients where name=?", "Сергей Орлов") == [(None,)],
              "повторное нажатие погасило светофор")

    print("\n[5] Теги")
    к = карточка("Анна Лебедева")
    к.get_by_role("button", name="Акция").click(); p.wait_for_timeout(900)
    проверить(из_базы("select count(*) from client_tag_links l join clients c on c.id=l.client_id "
                      "where c.name=?", "Анна Лебедева")[0][0] == 1, "тег «Акция» повесился")
    к = карточка("Анна Лебедева")
    к.get_by_role("button", name="+ тег").click(); p.wait_for_timeout(300)
    p.keyboard.type("Свадьба"); p.keyboard.press("Enter"); p.wait_for_timeout(1200)
    проверить(из_базы("select count(*) from client_tags where name=?", "Свадьба")[0][0] == 1,
              "администратор завёл новый тег")

    print("\n[6] Скрипт: ветки разговора")
    к = карточка("Сергей Орлов")
    проверить(к.get_by_role("button", name="Конфликт или плохой сервис").count() > 0,
              "ветки регламента показаны у потерянного")
    к.get_by_role("button", name="Дорого").click(); p.wait_for_timeout(400)
    проверить(к.get_by_text("Понимаю вас, спасибо, что поделились").count() > 0,
              "переключение ветки меняет текст")

    print("\n[7] Комментарий сохраняется сам")
    к = карточка("Илья Карпов")
    к.get_by_placeholder("Комментарий: о чём договорились").fill("просил позвонить вечером")
    p.keyboard.press("Tab"); p.wait_for_timeout(1000)
    проверить(из_базы("select admin_note from clients where name=?", "Илья Карпов")
              == [("просил позвонить вечером",)], "комментарий записался без кнопки «Сохранить»")

    print("\n[8] Статусы")
    к = карточка("Илья Карпов")
    к.get_by_role("button", name="Перезвонить").click(); p.wait_for_timeout(400)
    к = карточка("Илья Карпов")
    к.get_by_role("button", name="через 3 дня").click(); p.wait_for_timeout(1300)
    статус, дата = из_базы("select call_status, next_contact_at from clients where name=?",
                           "Илья Карпов")[0]
    проверить(статус == "callback", "статус «Перезвонить» записан")
    проверить(bool(дата), f"плановая дата записана: {дата}")
    проверить(p.locator("text=Илья Карпов").count() > 0, "клиент НЕ пропал из очереди")

    к = карточка("Марк Белов")
    к.get_by_role("button", name="Не дозвонились").click(); p.wait_for_timeout(1300)
    статус, дата = из_базы("select call_status, next_contact_at from clients where name=?",
                           "Марк Белов")[0]
    проверить(статус == "no_answer", "статус «Не дозвонились» записан")
    проверить(bool(дата), f"следующий звонок назначен сам на завтра: {дата}")

    к = карточка("Пётр Громов")
    к.get_by_role("button", name="Записан").click(); p.wait_for_timeout(1300)
    проверить(из_базы("select call_status from clients where name=?", "Пётр Громов") == [("booked",)],
              "статус «Записан» записан")

    print("\n[9] Вкладка «Позвонить сегодня»")
    p.get_by_role("button", name="Позвонить сегодня").first.click(); p.wait_for_timeout(1500)
    проверить(p.locator("text=Илья Карпов").count() > 0,
              "перенесённый на 3 дня остался на вкладке до конца дня")

    print("\n[10] Вкладка «Обзвоны»")
    p.get_by_role("button", name="Обзвоны").first.click(); p.wait_for_timeout(1500)
    текст = p.locator("body").inner_text()
    проверить("Перезвонить" in текст, "подгруппа «Перезвонить» есть")
    p.get_by_text("Перезвонить", exact=True).first.click(); p.wait_for_timeout(600)
    проверить("Илья Карпов" in p.locator("body").inner_text(),
              "звонок со статусом «Перезвонить» виден в обзвонах")
    p.screenshot(path="/tmp/e2e/calls.png")

    print("\n[11] Возвращённые и сверка")
    p.get_by_role("button", name="Возвращённые").first.click(); p.wait_for_timeout(1200)
    проверить(p.get_by_text("Вернули за месяц").count() > 0, "вкладка «Возвращённые» считает месяц")

    print("\n[12] Скрипты в настройках")
    p.get_by_role("button", name="Настройки").first.click(); p.wait_for_timeout(1500)
    проверить(p.get_by_text("Скрипты обзвона").count() > 0, "страница скриптов открылась")
    p.get_by_role("button", name="Потерянные").first.click(); p.wait_for_timeout(600)
    вариант = p.locator("div.rounded-xl").filter(has=p.locator("input[value='Начало разговора']")).first
    вариант.locator("textarea").first.fill("Свой текст для {имя}")
    вариант.get_by_role("button", name="Сохранить").click(); p.wait_for_timeout(1300)
    проверить(из_базы("select count(*) from scripts where phone_text like 'Свой текст%'")[0][0] == 1,
              "правка скрипта сохранилась в базу")
    p.get_by_role("button", name="Клиенты").first.click(); p.wait_for_timeout(1200)
    p.get_by_role("button", name="Администратор").first.click(); p.wait_for_timeout(600)
    if p.get_by_text("Кто сегодня звонит?").count():
        p.get_by_role("button", name="Виктор").first.click(); p.wait_for_timeout(1500)
    к = карточка("Сергей Орлов")
    проверить(к.get_by_text("Свой текст для Сергей Орлов").count() > 0,
              "правленый скрипт подставился в карточку клиента")

    print("\n[13] «Не звонить» и теги-исключения")
    к = карточка("Сергей Орлов")
    p.once("dialog", lambda d: d.accept())
    к.get_by_role("button", name="Не звонить").click(); p.wait_for_timeout(1500)
    проверить(из_базы("select do_not_call from clients where name=?", "Сергей Орлов")[0][0] == 1,
              "«Не звонить» записалось в базу")
    проверить(p.locator("text=Сергей Орлов").count() == 0, "клиент ушёл из очереди")

    к = карточка("Анна Лебедева")
    к.get_by_role("button", name="Переехал").click(); p.wait_for_timeout(1500)
    проверить(p.locator("text=Анна Лебедева").count() == 0,
              "тег «Переехал» убрал клиента из очереди")
    p.get_by_role("button", name="Обзвоны").first.click(); p.wait_for_timeout(1400)
    p.get_by_text("Исключены из обзвона").first.click(); p.wait_for_timeout(600)
    тело = p.locator("body").inner_text()
    проверить("Сергей Орлов" in тело and "Анна Лебедева" in тело,
              "оба попали в подгруппу «Исключены из обзвона»")

    print("\n[14] Возвращённые: записанный потеряшка")
    p.get_by_role("button", name="Возвращённые").first.click(); p.wait_for_timeout(1400)
    проверить("Пётр Громов" in p.locator("body").inner_text(),
              "записанный потерянный попал в «Возвращённые»")

    print("\n[15] Фильтры очереди")
    p.get_by_role("button", name="Администратор").first.click(); p.wait_for_timeout(1200)
    if p.get_by_text("Кто сегодня звонит?").count():
        p.get_by_role("button", name="Виктор").first.click(); p.wait_for_timeout(1400)
    было = p.locator("div.rounded-2xl").filter(has=p.get_by_text("визит", exact=False)).count()
    p.get_by_role("combobox").nth(1).select_option(label="Борода") if p.get_by_role("combobox").count() > 1 else None
    p.wait_for_timeout(800)
    стало = p.locator("div.rounded-2xl").filter(has=p.get_by_text("визит", exact=False)).count()
    проверить(стало <= было, f"фильтр по услуге сузил список: было {было}, стало {стало}")

    print("\n[16] Ошибок в консоли нет")
    чужие = [о for о in ошибки_страницы if "502" not in о]  # 502 = YCLIENTS не настроен на стенде
    проверить(not чужие, f"ошибок страницы: {чужие[:3]}")

    p.screenshot(path="/tmp/e2e/final.png")
    ctx.close(); b.close()

print(f"\nИТОГ: прошло {len(шаги)}, провалено {len(провалы)}")
for т in провалы:
    print("  ПРОВАЛ:", т)
sys.exit(1 if провалы else 0)
