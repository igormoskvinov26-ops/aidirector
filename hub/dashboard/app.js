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

function barColor(ok) {
  if (ok === true) return "var(--profit)";
  if (ok === false) return "var(--loss)";
  return "var(--gold)";
}

function financeCard(f) {
  if (!f) {
    return `<div class="card"><h2>Финансы месяца</h2>
      <div class="empty-state">YCLIENTS ещё не настроен или сервер не ответил</div></div>`;
  }
  const profitColor = f.profit.value >= 0 ? "var(--profit)" : "var(--loss)";
  const incomePct = Math.min(100, f.income.pct_of_plan ?? 0);
  const expPct = Math.min(100, f.expenses.pct_of_budget ?? 0);
  const hist = f.history.slice(-6);
  const maxAbs = Math.max(1, ...hist.map((m) => Math.abs(m.profit)));
  return `
    <div class="card">
      <h2>Финансы месяца</h2>
      <div class="profit-row">
        <div>
          <div class="value" style="color:${profitColor}">${rub(f.profit.value)}</div>
          <div class="margin">прибыль${f.profit.margin_pct !== null ? ` · маржа ${pct(f.profit.margin_pct)}` : ""}</div>
        </div>
        <div class="margin">темп месяца: ${pct(f.elapsed_pct)}</div>
      </div>
      <div class="kpi-grid">
        <div class="kpi">
          <div class="label">Доход</div>
          <div class="val">${rub(f.income.value)}</div>
          <div class="sub">${f.income.plan !== null ? `план ${rub(f.income.plan)} · ${pct(f.income.pct_of_plan)}` : "план не задан"}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${incomePct}%;background:${barColor(f.income.ok)}"></div></div>
        </div>
        <div class="kpi">
          <div class="label">Расходы</div>
          <div class="val">${rub(f.expenses.value)}</div>
          <div class="sub">${f.expenses.budget !== null ? `бюджет ${rub(f.expenses.budget)} · ${pct(f.expenses.pct_of_budget)}` : "бюджет не посчитан"}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${expPct}%;background:${barColor(f.expenses.ok)}"></div></div>
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
