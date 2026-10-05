"use strict";

const LS_URL = "пульт.hubUrl";
const LS_TOKEN = "пульт.hubToken";

const app = document.getElementById("app");

const SEGMENT_COLOR = {
  new: "#968a79",
  second: "#ab8e53",
  loyal: "#c9a15a",
  vip: "#2f9e5f",
  lost: "#e0564b",
};
const RISK_COLOR = "#d0a03c";

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function rub(v) {
  if (v === null || v === undefined) return "—";
  return new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 0 }).format(v) + " ₽";
}

function pct(v) {
  return v === null || v === undefined ? "—" : `${v}%`;
}

function relTime(iso) {
  if (!iso) return "ещё не было";
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "только что";
  if (diff < 3600) return `${Math.floor(diff / 60)} мин назад`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} ч назад`;
  return `${Math.floor(diff / 86400)} дн назад`;
}

function storedUrl() { return localStorage.getItem(LS_URL) || ""; }
function storedToken() { return localStorage.getItem(LS_TOKEN) || ""; }

async function callDashboard(url, token) {
  const r = await fetch(`${url.replace(/\/+$/, "")}/v1/dashboard`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (r.status === 401) throw new Error("UNAUTHORIZED");
  if (r.status === 404) return null; // ещё не синхронизировалось
  if (!r.ok) throw new Error(`Сервер ответил ${r.status}`);
  return r.json();
}

// ── Экран входа ──────────────────────────────────────────────────────────

function renderLogin(error) {
  app.innerHTML = `
    <div class="login">
      <div class="brand">
        <img src="icons/icon-192.png" alt="">
        <span>Пульт</span>
      </div>
      <p class="hint" style="text-align:center">Витрина владельца — финансы и база клиентов,
        только суммы и счётчики.</p>
      ${error ? `<div class="error">${esc(error)}</div>` : ""}
      <div class="field">
        <label for="f-url">Адрес сервера</label>
        <input id="f-url" type="url" inputmode="url" autocapitalize="none" autocorrect="off"
          placeholder="https://..." value="${esc(storedUrl())}">
      </div>
      <div class="field">
        <label for="f-token">Ключ доступа</label>
        <input id="f-token" type="password" autocapitalize="none" autocorrect="off"
          placeholder="HUB_TOKEN" value="${esc(storedToken())}">
      </div>
      <button class="btn" id="f-go">Войти</button>
    </div>
  `;
  document.getElementById("f-go").addEventListener("click", onLogin);
}

async function onLogin() {
  const url = document.getElementById("f-url").value.trim();
  const token = document.getElementById("f-token").value.trim();
  if (!url || !token) {
    renderLogin("Заполните адрес и ключ");
    return;
  }
  const btn = document.getElementById("f-go");
  btn.disabled = true;
  btn.textContent = "Проверяю…";
  try {
    const data = await callDashboard(url, token);
    localStorage.setItem(LS_URL, url);
    localStorage.setItem(LS_TOKEN, token);
    renderDashboard(url, token, data);
  } catch (e) {
    renderLogin(e.message === "UNAUTHORIZED" ? "Ключ не принят" : "Сервер не отвечает — проверьте адрес");
  }
}

function logout() {
  localStorage.removeItem(LS_URL);
  localStorage.removeItem(LS_TOKEN);
  renderLogin();
}

// ── Дашборд ──────────────────────────────────────────────────────────────

function окРасцвет(ok) {
  if (ok === true) return "var(--profit)";
  if (ok === false) return "var(--loss)";
  return "var(--cream)";
}

// Коротко: 1.2 млн / 650к — как кратко() в OwnerPage.tsx.
function кратко(v) {
  return Math.abs(v) >= 1_000_000
    ? `${(v / 1_000_000).toFixed(1).replace(".", ",")} млн`
    : `${Math.round(v / 1000)}к`;
}

/** Точный порт Спидометра из frontend/src/OwnerPage.tsx — тот же радиус,
 * та же дуга плана и темпа, тот же способ красить заливку по ok. */
function спидометр({ min, max, value, plan, pace, fill, planZone, caption, text }) {
  const R = 118, C = 150, W = 14;
  const f = (v) => (Math.max(min, Math.min(max, v)) - min) / (max - min || 1);
  const pt = (k, r = R) => {
    const a = Math.PI * (1 - k);
    return [C + r * Math.cos(a), C - r * Math.sin(a)];
  };
  const arc = (k1, k2, r = R) => {
    const [x1, y1] = pt(k1, r), [x2, y2] = pt(k2, r);
    return `M${x1} ${y1} A${r} ${r} 0 0 1 ${x2} ${y2}`;
  };
  const zero = f(Math.max(0, min));
  const k = f(value);
  const [a, b] = k >= zero ? [zero, k] : [k, zero];
  const track = "var(--line)", tick = "var(--muted)";

  let svg = `<svg viewBox="0 0 300 200" class="gauge" role="img" aria-label="${esc(caption)}: ${esc(text)}">`;
  svg += `<path d="${arc(0, 1)}" fill="none" stroke="${track}" stroke-width="${W}" stroke-linecap="round"/>`;
  if (plan != null && plan < max) {
    svg += `<path d="${arc(f(plan), 1)}" fill="none" stroke="${planZone}" stroke-opacity="0.28" stroke-width="${W}"/>`;
  }
  if (b - a > 0.002) {
    svg += `<path d="${arc(a, b)}" fill="none" stroke="${fill}" stroke-width="${W}" stroke-linecap="round"/>`;
  }
  if (min < 0) {
    const [x1, y1] = pt(zero, R - W), [x2, y2] = pt(zero, R + W);
    svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${tick}" stroke-width="1.5"/>`;
  }
  if (pace != null) {
    const [x1, y1] = pt(f(pace), R - W / 2 - 5), [x2, y2] = pt(f(pace), R + W / 2 + 5);
    svg += `<line x1="${x1}" y1="${y1}" x2="${x2}" y2="${y2}" stroke="${tick}" stroke-width="1.2" stroke-dasharray="2 2"/>`;
  }
  if (plan != null) {
    const [x, y] = pt(f(plan));
    const [tx, ty] = pt(f(plan), R + 24);
    svg += `<circle cx="${x}" cy="${y}" r="6.5" fill="${track}" stroke="${tick}" stroke-width="2"/>`;
    svg += `<text x="${tx}" y="${ty + 3}" text-anchor="middle" font-size="9.5" fill="${tick}">план</text>`;
  }
  svg += `<text x="${C}" y="${C - 6}" text-anchor="middle" font-size="27" font-weight="600" fill="${fill}">${esc(text)}</text>`;
  svg += `<text x="${C}" y="${C + 14}" text-anchor="middle" font-size="10.5" fill="${tick}">${esc(caption)}</text>`;
  svg += `<text x="${pt(0)[0]}" y="${C + 22}" text-anchor="middle" font-size="9.5" fill="${tick}">${min < 0 ? "−" + кратко(-min) : "0"}</text>`;
  svg += `<text x="${pt(1)[0]}" y="${C + 22}" text-anchor="middle" font-size="9.5" fill="${tick}">${кратко(max)}</text>`;
  svg += `</svg>`;
  return svg;
}

function financeCard(f) {
  if (!f) {
    return `<div class="card"><h2>Финансы месяца</h2>
      <div class="empty-state">YCLIENTS ещё не настроен или сервер не ответил</div></div>`;
  }
  // Те же формулы шкал, что в OwnerPage.tsx: план не в конце, после него
  // запас на перевыполнение/перерасход.
  const шкалаДохода = Math.max((f.income.plan ?? 0) * 1.2, (f.income.value ?? 0) * 1.1, 1);
  const шкалаРасхода = Math.max((f.expenses.budget ?? 0) * 1.2, (f.expenses.value ?? 0) * 1.1, 1);
  const размахПрибыли = Math.max(Math.abs(f.profit.value ?? 0) * 1.15, (f.profit.plan ?? 0) * 1.2, 1);
  const темпДохода = f.income.plan != null ? (f.income.plan * f.elapsed_pct) / 100 : null;
  const темпРасхода = f.expenses.budget != null ? (f.expenses.budget * f.elapsed_pct) / 100 : null;

  const hist = f.history.slice(-6);
  const maxAbs = Math.max(1, ...hist.map((m) => Math.abs(m.profit)));

  return `
    <div class="card">
      <h2>Финансы месяца — темп ${pct(Math.round(f.elapsed_pct))}</h2>
      <div class="gauges">
        <div class="gauge-cell">
          ${спидометр({
            min: 0, max: шкалаДохода, value: f.income.value ?? 0, plan: f.income.plan, pace: темпДохода,
            fill: окРасцвет(f.income.ok), planZone: "var(--profit)", caption: "доход", text: rub(f.income.value),
          })}
          <div class="gauge-sub">${f.income.plan != null ? `план ${rub(f.income.plan)} · ${pct(f.income.pct_of_plan)}` : "план не задан"}</div>
        </div>
        <div class="gauge-cell">
          ${спидометр({
            min: 0, max: шкалаРасхода, value: f.expenses.value ?? 0, plan: f.expenses.budget, pace: темпРасхода,
            fill: окРасцвет(f.expenses.ok), planZone: "var(--loss)", caption: "расходы", text: rub(f.expenses.value),
          })}
          <div class="gauge-sub">${f.expenses.budget != null ? `бюджет ${rub(f.expenses.budget)} · ${pct(f.expenses.pct_of_budget)}` : "бюджет не посчитан"}</div>
        </div>
        <div class="gauge-cell">
          ${спидометр({
            min: -размахПрибыли, max: размахПрибыли, value: f.profit.value ?? 0, plan: f.profit.plan, pace: f.profit.pace,
            fill: окРасцвет(f.profit.ok), planZone: "var(--profit)", caption: "прибыль", text: rub(f.profit.value),
          })}
          <div class="gauge-sub">${f.profit.plan != null ? `план ${rub(f.profit.plan)}${f.profit.margin_pct != null ? ` · рент. ${pct(f.profit.margin_pct)}` : ""}` : "план не задан"}</div>
        </div>
      </div>
      <div class="hist">
        ${hist.map((m) => `
          <div class="col">
            <div class="bars">
              <div style="height:${Math.max(4, Math.abs(m.profit) / maxAbs * 56)}px;
                background:${m.profit >= 0 ? "var(--profit)" : "var(--loss)"};
                opacity:${m.partial ? 0.55 : 1}"></div>
            </div>
            <div class="m">${esc(m.month.slice(5))}${m.partial ? "…" : ""}</div>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function pulseCard(p) {
  if (!p) {
    return `<div class="card"><h2>База клиентов</h2>
      <div class="empty-state">Пока нет данных</div></div>`;
  }
  const max = Math.max(1, ...p.segments.map((s) => s.total), p.risk_zone.total);
  const row = (code, label, total, color) => `
    <div class="pulse-row">
      <div class="seg-label">${esc(label)}</div>
      <div class="seg-track"><div class="seg-fill" style="width:${Math.max(3, total / max * 100)}%;background:${color}"></div></div>
      <div class="seg-count">${total}</div>
    </div>
  `;
  return `
    <div class="card">
      <h2>База клиентов — ${p.base_total} всего</h2>
      ${p.segments.map((s) => row(s.code, s.label, s.total, SEGMENT_COLOR[s.code] || "var(--gold)")).join("")}
      ${row(p.risk_zone.code, p.risk_zone.label, p.risk_zone.total, RISK_COLOR)}
    </div>
  `;
}

function sparkline(days) {
  const w = 300, h = 44;
  if (days.length < 2) return "";
  const vals = days.map((d) => d.total);
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = Math.max(1, max - min);
  const pts = days.map((d, i) => {
    const x = (i / (days.length - 1)) * w;
    const y = h - ((d.total - min) / span) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return `<svg class="sparkline" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polyline points="${pts}" fill="none" stroke="var(--gold)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  </svg>`;
}

function flowCard(fl) {
  if (!fl || !fl.start) {
    return `<div class="card"><h2>Приток и отток базы</h2>
      <div class="empty-state">Точка отсчёта пульса ещё не задана в настройках</div></div>`;
  }
  const recent = fl.days.slice(-60);
  return `
    <div class="card">
      <h2>Приток и отток базы — с ${esc(fl.start)}</h2>
      <div class="flow-summary">
        <div class="fs"><div class="n" style="color:var(--profit)">+${fl.new}</div><div class="l">новые</div></div>
        <div class="fs"><div class="n" style="color:var(--gold)">+${fl.returned}</div><div class="l">вернулись</div></div>
        <div class="fs"><div class="n" style="color:var(--loss)">−${fl.lost}</div><div class="l">потеряно</div></div>
        <div class="fs"><div class="n">${fl.total >= 0 ? "+" : ""}${fl.total}</div><div class="l">итого</div></div>
      </div>
      ${sparkline(recent)}
    </div>
  `;
}

function renderDashboard(url, token, data) {
  app.innerHTML = `
    <div class="topbar">
      <div class="title">
        <img src="icons/icon-192.png" alt="">
        <span>Пульт</span>
      </div>
      <div class="actions">
        <span class="updated" id="updated"></span>
        <button class="icon-btn" id="refresh" aria-label="Обновить">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 12a9 9 0 11-3-6.7"/><path d="M21 3v6h-6"/></svg>
        </button>
      </div>
    </div>
    <div id="cards"></div>
    <div class="footer-link"><button id="logout">сменить сервер</button></div>
  `;
  document.getElementById("logout").addEventListener("click", logout);
  document.getElementById("refresh").addEventListener("click", () => refresh(url, token));
  paint(data);
}

function paint(data) {
  document.getElementById("updated").textContent = data ? relTime(data.updated_at) : "";
  document.getElementById("cards").innerHTML = data
    ? financeCard(data.finance) + pulseCard(data.base_pulse) + flowCard(data.base_flow)
    : `<div class="card"><div class="empty-state">Сервер ещё не получил данные от установки.
        Откройте Пульт на компьютере — синхронизация подхватит их в течение пары минут.</div></div>`;
}

async function refresh(url, token) {
  const btn = document.getElementById("refresh");
  const icon = btn.querySelector("svg");
  icon.classList.add("spin");
  try {
    const data = await callDashboard(url, token);
    paint(data);
  } catch (e) {
    if (e.message === "UNAUTHORIZED") { logout(); return; }
  } finally {
    icon.classList.remove("spin");
  }
}

// ── Запуск ───────────────────────────────────────────────────────────────

async function boot() {
  const url = storedUrl(), token = storedToken();
  if (!url || !token) { renderLogin(); return; }
  try {
    const data = await callDashboard(url, token);
    renderDashboard(url, token, data);
    setInterval(() => refresh(url, token), 60000);
  } catch (e) {
    if (e.message === "UNAUTHORIZED") { renderLogin("Ключ не принят"); return; }
    renderLogin("Сервер не отвечает — проверьте адрес");
  }
}

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}

boot();
