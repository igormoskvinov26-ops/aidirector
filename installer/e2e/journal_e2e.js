// Журнал обзвона в живом Пульте: результат должен попасть ровно тому, кому
// нажали, даже если между открытием карточки и нажатием очередь пересобралась.
// node journal_e2e.js <логин> <пароль> <префикс имён> <отчёт.json>
const { chromium } = require('playwright');
const { execFileSync } = require('child_process');
const fs = require('fs');
const [ЛОГИН, ПАРОЛЬ, ПРЕФИКС, ОТЧЁТ] = process.argv.slice(2, 6);
const ЖЁСТКО = process.argv[6] === 'hard';
const ЦЕЛИ = ЖЁСТКО ? [
  [`${ПРЕФИКС} 02`, 'Записан', 'delete'],
  [`${ПРЕФИКС} 05`, 'Без записи', 'delete'],
  [`${ПРЕФИКС} 08`, 'Не дозвонились', 'delete+refresh'],
  [`${ПРЕФИКС} 13`, 'Записан', 'refresh'],
  [`${ПРЕФИКС} 17`, 'Без записи', 'delete'],
] : [
  [`${ПРЕФИКС} 03`, 'Без записи', 'refresh'],
  [`${ПРЕФИКС} 07`, 'Не дозвонились', 'refresh'],
  [`${ПРЕФИКС} 11`, 'Записан', 'refresh'],
  [`${ПРЕФИКС} 15`, 'Без записи', 'refresh2'],
  [`${ПРЕФИКС} 19`, 'Записан', 'none'],
  [`${ПРЕФИКС} 23`, 'Не дозвонились', 'refresh'],
  [`${ПРЕФИКС} 27`, 'Без записи', 'refresh'],
];
const ИСХОД = { 'Без записи': 'no_booking', 'Не дозвонились': 'no_answer', 'Записан': 'booked' };
const вКонтейнере = (f) => execFileSync('docker', ['exec', '-e', 'PYTHONPATH=/app', 'rubl_director', 'python', `/tmp/${f}`], { timeout: 60000 }).toString().trim();
const изБазы = (sql) => execFileSync('docker', ['exec', 'rubl_db', 'psql', '-U', 'rubl', '-d', 'rubl_director', '-At', '-F', '|', '-c', sql], { timeout: 30000 })
  .toString().trim().split('\n').filter(Boolean).map((l) => l.split('|'));

(async () => {
  const итог = { шаги: [], ошибки_на_экране: {}, ошибки_страницы: [] };
  const b = await chromium.launch();
  const ctx = await b.newContext({ viewport: { width: 1500, height: 1000 }, httpCredentials: { username: ЛОГИН, password: ПАРОЛЬ } });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => итог.ошибки_страницы.push(String(e).slice(0, 200)));
  await p.goto('http://127.0.0.1:8000/#admin');
  await p.waitForTimeout(2500);
  const раздел = p.getByRole('button', { name: 'Клиентская база' });
  if (await раздел.count()) { await раздел.first().click(); await p.waitForTimeout(2500); }
  for (const [имя, кнопка, помеха] of ЦЕЛИ) {
    const строка = p.locator('tr', { hasText: имя }).first();
    await строка.scrollIntoViewIfNeeded();
    await строка.click();
    const карточка = p.locator('tr').filter({ has: p.getByRole('button', { name: 'Без записи' }) }).first();
    await карточка.waitFor({ timeout: 10000 });
    // Убедиться, что открыта карточка именно этого клиента.
    const текст = await карточка.innerText();
    if (!текст.includes(имя)) итог.шаги.push({ [имя]: 'ОТКРЫЛАСЬ ЧУЖАЯ КАРТОЧКА' });
    await p.waitForTimeout(500);
    if (помеха.startsWith('delete')) {
      изБазы(`delete from contact_tasks where status='open' and client_id=(select id from clients where name='${имя}')`);
      итог.шаги.push({ [имя]: 'задача удалена под открытой карточкой' });
    }
    if (помеха.endsWith('refresh')) итог.шаги.push({ [имя]: вКонтейнере('refresh.py') });
    if (помеха === 'refresh2') итог.шаги.push({ [имя]: вКонтейнере('refresh.py') });
    await карточка.getByRole('button', { name: кнопка }).first().click();
    await p.waitForTimeout(1800);
    const ошибки = (await p.locator('.text-loss').allInnerTexts())
      .filter((t) => !/^\d+\s*дн\.?$/i.test(t.trim()) && t.trim() !== 'Не звонить');
    if (ошибки.length) итог.ошибки_на_экране[имя] = ошибки;
    await p.screenshot({ path: ОТЧЁТ.replace('.json', `-${имя.slice(-2)}.png`) });
  }
  await p.getByRole('button', { name: 'Журнал обзвона' }).first().click();
  await p.waitForTimeout(2500);
  await p.screenshot({ path: ОТЧЁТ.replace('.json', '-журнал.png'), fullPage: true });
  итог.журнал_на_экране = [...new Set((await p.locator('tbody tr:visible').allInnerTexts()).map((t) => (t.match(new RegExp(`${ПРЕФИКС} \\d\\d`)) || [''])[0]).filter(Boolean))].sort();
  await b.close();

  const ожидаем = Object.fromEntries(ЦЕЛИ.map(([и, к]) => [и, ИСХОД[к]]));
  const вБазе = изБазы(`select c.name, a.outcome from contact_attempts a join contact_tasks t on t.id=a.task_id join clients c on c.id=t.client_id where c.name like '${ПРЕФИКС} %' order by a.id`);
  итог.ожидаем = ожидаем; итог.в_базе = вБазе;
  итог.лишние_в_журнале = вБазе.filter((r) => !(r[0] in ожидаем));
  итог.пропали_из_журнала = Object.keys(ожидаем).filter((n) => !вБазе.some((r) => r[0] === n));
  итог.неверный_исход = вБазе.filter((r) => r[0] in ожидаем && ожидаем[r[0]] !== r[1]);
  итог.журнал_совпадает = JSON.stringify(итог.журнал_на_экране) === JSON.stringify(Object.keys(ожидаем).sort());
  итог.ПРОЙДЕН = !итог.лишние_в_журнале.length && !итог.пропали_из_журнала.length && !итог.неверный_исход.length
    && вБазе.length === ЦЕЛИ.length && итог.журнал_совпадает && !итог.шаги.some((s) => Object.values(s)[0] === 'ОТКРЫЛАСЬ ЧУЖАЯ КАРТОЧКА');
  fs.writeFileSync(ОТЧЁТ, JSON.stringify(итог, null, 1));
  const { ПРОЙДЕН, лишние_в_журнале, пропали_из_журнала, неверный_исход, ошибки_на_экране, ошибки_страницы, журнал_на_экране } = итог;
  console.log(JSON.stringify({ ПРОЙДЕН, лишние_в_журнале, пропали_из_журнала, неверный_исход, ошибки_на_экране, ошибки_страницы, журнал_на_экране }, null, 1));
})().catch((e) => { console.error(e); process.exit(2); });
