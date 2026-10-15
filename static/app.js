/* D360 AI SolarClear single-page UI. Vanilla JS, no build step. Talks to the REST API with a bearer token.
   Bilingual: English / Telugu. UI strings live in /static/locales/{en,te}.json; server-generated text
   (reasons, alerts) arrives in both languages as `field` and `field_te`. */
"use strict";

const state = { token: null, user: null, chat: [], agent: null, lang: "en" };
const I18N = { en: {}, te: {} };
const $ = (sel, root = document) => root.querySelector(sel);
const main = () => $("#main");

// ------------------------------------------------------------------ i18n
function t(key, vars = {}) {
  const text = I18N[state.lang][key] ?? I18N.en[key] ?? key;
  return text.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? `{${k}}`));
}
// Server text: use the Telugu copy when the UI is in Telugu and one exists.
const pick = (obj, field) => (state.lang === "te" && obj[`${field}_te`]) || obj[field] || "";
const modeName = (m) => (m === "azure" ? t("engine.azure") : t("engine.offlineName"));

async function loadLocales() {
  const [en, te] = await Promise.all(["en", "te"].map((l) => fetch(`/static/locales/${l}.json`).then((r) => r.json())));
  I18N.en = en;
  I18N.te = te;
}

function applyStaticText() {
  document.documentElement.lang = state.lang;
  document.title = t("app.title");
  document.querySelectorAll("[data-i18n]").forEach((el) => (el.textContent = t(el.dataset.i18n)));
  document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => (el.placeholder = t(el.dataset.i18nPlaceholder)));
  document.querySelectorAll("[data-lang]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.lang === state.lang)));
  if (state.user) {
    $("#user-label").textContent = `${state.user.name} · ${t(`role.${state.user.role}`)}`;
    renderAgentMode();
  }
}

function setLang(lang) {
  state.lang = lang === "te" ? "te" : "en";
  store("sc_lang", state.lang);
  applyStaticText();
  if (state.token && !$("#app-view").hidden) route();
}
document.querySelectorAll("[data-lang]").forEach((b) => b.addEventListener("click", () => setLang(b.dataset.lang)));

// ------------------------------------------------------------------ helpers
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 1) => (v === null || v === undefined ? t("ui.na") : Number(v).toLocaleString("en-IN", { maximumFractionDigits: d }));
const statusChip = (s, label) => `<span class="status ${esc(s)}">${esc(label || t(`status.${s}`))}</span>`;
const limitName = (k) => t(`limit.${k}`);

function store(key, value) {
  try { value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value); } catch (_) { /* storage blocked */ }
}
function load(key) {
  try { return localStorage.getItem(key); } catch (_) { return null; }
}

function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (isError ? " err" : "");
  el.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (el.hidden = true), 4000);
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-Lang": state.lang,
      ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && state.token) {
    logout();
    throw new Error(t("err.sessionExpired"));
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    if (Array.isArray(data.detail)) {
      throw new Error(t("err.validation", { fields: data.detail.map((d) => d.loc?.slice(-1)[0]).join(", ") }));
    }
    // Known server messages have a Telugu translation keyed by the English text.
    throw new Error(data.detail ? t(data.detail) : t("err.generic", { s: res.status }));
  }
  return data;
}

async function withBusy(button, fn) {
  const label = button?.textContent;
  if (button) { button.disabled = true; button.textContent = t("ui.working"); }
  try { return await fn(); }
  catch (err) { toast(err.message, true); }
  finally { if (button) { button.disabled = false; button.textContent = label; } }
}

// ------------------------------------------------------------------ auth
function showAuth() {
  $("#auth-view").hidden = false;
  $("#app-view").hidden = true;
}

function setSession(data) {
  state.token = data.token;
  state.user = data.user;
  store("sc_token", data.token);
  startApp();
}

function logout() {
  state.token = null; state.user = null; state.chat = [];
  store("sc_token", null);
  showAuth();
}

document.querySelectorAll("[data-auth-tab]").forEach((tab) =>
  tab.addEventListener("click", () => {
    document.querySelectorAll("[data-auth-tab]").forEach((x) => x.classList.toggle("active", x === tab));
    $("#login-form").hidden = tab.dataset.authTab !== "login";
    $("#register-form").hidden = tab.dataset.authTab !== "register";
    $("#auth-error").textContent = "";
  }));

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { setSession(await api("/api/auth/login", { method: "POST", body: Object.fromEntries(new FormData(e.target)) })); }
  catch (err) { $("#auth-error").textContent = err.message; }
});

$("#register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  try { setSession(await api("/api/auth/register", { method: "POST", body: Object.fromEntries(new FormData(e.target)) })); }
  catch (err) { $("#auth-error").textContent = err.message; }
});

$("#logout").addEventListener("click", logout);

function renderAgentMode() {
  if (!state.agent) return;
  $("#agent-mode").innerHTML = state.agent.llm_enabled
    ? `<span class="ai-badge">● ${esc(t("engine.online"))}</span>`
    : esc(t("engine.offline"));
}

async function startApp() {
  $("#auth-view").hidden = true;
  $("#app-view").hidden = false;
  try { state.agent = await api("/api/agent/status"); } catch (_) { /* non-fatal */ }
  applyStaticText();
  refreshAlertCount();
  route();
}

async function refreshAlertCount() {
  try {
    const alerts = await api("/api/alerts");
    const critical = alerts.filter((a) => a.severity === "critical").length;
    const pill = $("#alert-count");
    pill.textContent = critical;
    pill.hidden = critical === 0;
  } catch (_) { /* ignore */ }
}

// ------------------------------------------------------------------ router
const routes = { dashboard: viewDashboard, dtr: viewDtr, applications: viewApplications, alerts: viewAlerts, copilot: viewCopilot, assets: viewAssets, runs: viewRuns };

function route() {
  if (!state.token) return showAuth();
  const [name, arg] = (location.hash.slice(1) || "dashboard").split("/");
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name || (name === "dtr" && a.dataset.nav === "dashboard")));
  main().innerHTML = `<div class="empty">${esc(t("ui.loading"))}</div>`;
  (routes[name] || viewDashboard)(arg).catch((err) => {
    main().innerHTML = `<div class="card error">${esc(err.message)}</div>`;
  });
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ dashboard
const kpi = (label, value, sub) => `<div class="card kpi"><div class="label">${esc(label)}</div><div class="value">${value}</div><div class="sub">${esc(sub)}</div></div>`;

async function viewDashboard() {
  const data = await api("/api/analytics/overview");
  const k = data.kpis;
  main().innerHTML = `
    <div class="page-head">
      <div><h1>${esc(t("dash.title"))}</h1>
        <div class="muted">${esc(t("dash.limits", { v: data.limits.voltage_upper_pu, r: data.limits.reverse_flow_limit_pct, p: data.limits.policy_cap_pct }))}</div></div>
      <div class="row">
        <label class="row small" style="display:flex"><input type="checkbox" id="with-brief" ${state.agent?.llm_enabled ? "checked" : "disabled"}> ${esc(t("dash.brief"))}</label>
        <button class="btn primary" id="scan-btn">${esc(t("dash.scan"))}</button>
      </div>
    </div>
    <div class="grid kpis">
      ${kpi(t("kpi.installed"), `${num(k.installed_pv_kw, 0)} kW`, t("kpi.installedSub", { n: k.dtrs }))}
      ${kpi(t("kpi.headroom"), `${num(k.hosting_headroom_kw, 0)} kW`, t("kpi.headroomSub"))}
      ${kpi(t("kpi.saturated"), k.saturated_dtrs, t("kpi.saturatedSub", { n: k.watch_dtrs }))}
      ${kpi(t("kpi.apps"), k.open_applications, t("kpi.appsSub", { kw: num(k.queued_kw) }))}
      ${kpi(t("kpi.alerts"), k.open_alerts, t("kpi.alertsSub", { n: k.critical_alerts }))}
    </div>
    <div id="scan-result"></div>
    <div class="grid two section">${data.feeders.map(feederCard).join("")}</div>
    <div class="card section">
      <h2>${esc(t("table.dtrs"))}</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>${t("th.dtr")}</th><th>${t("th.feeder")}</th><th class="num">${t("th.kva")}</th><th class="num">${t("th.solarKw")}</th><th class="num">${t("th.headroomKw")}</th>
          <th>${t("th.util")}</th><th>${t("th.binding")}</th><th class="num">${t("th.months")}</th><th>${t("th.status")}</th></tr></thead>
        <tbody>${data.dtrs.sort((a, b) => b.utilisation_pct - a.utilisation_pct).map(dtrRow).join("")}</tbody>
      </table></div>
    </div>`;
  main().querySelectorAll("tr[data-dtr]").forEach((tr) => tr.addEventListener("click", () => (location.hash = `dtr/${tr.dataset.dtr}`)));
  $("#scan-btn").addEventListener("click", (e) => withBusy(e.target, runScan));
}

function feederCard(f) {
  return `<div class="card">
    <h3>${esc(pick(f, "feeder_name"))} <span class="muted small">${esc(f.feeder_code)}</span></h3>
    <div class="small muted" style="margin:-4px 0 8px">${esc(pick(f, "substation_name"))}</div>
    <div class="row small muted" style="gap:18px">
      <span>${esc(t("feeder.solar", { kw: num(f.existing_pv_kw, 0) }))}</span>
      <span>${esc(t("feeder.headroom", { kw: num(f.hosting_kw, 0) }))}</span>
      <span>${esc(t("feeder.dtrs", { n: f.dtrs }))}</span>
    </div>
    <div class="row small" style="margin-top:8px;gap:14px">
      ${statusChip("saturated", t("feeder.saturated", { n: f.saturated_dtrs }))} ${statusChip("watch", t("feeder.watch", { n: f.watch_dtrs }))}
      <span class="muted">${esc(t("feeder.limitedBy", { x: limitName(f.binding_constraint) }))}</span>
    </div></div>`;
}

function utilBar(pct) {
  const cls = pct >= 90 ? "hi" : pct >= 70 ? "mid" : "";
  return `<div class="util"><div class="bar"><span class="${cls}" style="width:${Math.min(pct, 100)}%"></span></div><span class="small">${num(pct, 0)}%</span></div>`;
}

function dtrRow(d) {
  return `<tr class="click" data-dtr="${d.dtr_id}">
    <td><b>${esc(pick(d, "dtr_name"))}</b><div class="small muted">${esc(d.dtr_code)} · ${esc(t(`area.${d.area_type}`))}</div></td><td>${esc(d.feeder_code)}</td>
    <td class="num">${num(d.rating_kva, 0)}</td><td class="num">${num(d.existing_pv_kw)}</td><td class="num">${num(d.hosting_kw)}</td>
    <td>${utilBar(d.utilisation_pct)}</td><td>${esc(limitName(d.binding_constraint))}</td>
    <td class="num">${d.months_to_saturation === null ? t("ui.na") : num(d.months_to_saturation)}</td><td>${statusChip(d.status)}</td></tr>`;
}

async function runScan() {
  const result = await api("/api/agent/scan", { method: "POST", body: { with_brief: $("#with-brief")?.checked || false } });
  const apps = result.applications_evaluated;
  $("#scan-result").innerHTML = `<div class="card scan-result">
    <h2>${esc(t("scan.title"))}</h2>
    <p>${esc(result.summary)}</p>
    ${result.brief ? `<h3>${esc(t("scan.brief"))}</h3><div class="brief">${md(result.brief)}</div>` : ""}
    ${apps.length ? `<p class="small muted">${esc(t("scan.cleared"))}: ${apps.map((a) => `#${a.id} ${esc(a.dtr)} ${a.kw} kW → ${esc(t(`status.${a.rec}`))} ${a.rec_kw} kW`).join(" · ")}</p>` : ""}
    <p class="small muted">${esc(t("scan.meta", { engine: modeName(result.mode), i: result.usage.prompt_tokens, o: result.usage.completion_tokens }))}${result.webhook_notified ? esc(t("scan.webhook")) : ""}</p>
    <div class="row"><a href="#alerts">${esc(t("scan.viewAlerts"))}</a><a href="#applications">${esc(t("scan.reviewApps"))}</a></div></div>`;
  refreshAlertCount();
}

// ------------------------------------------------------------------ DTR detail
async function viewDtr(id) {
  const [hc, fc, dtr] = await Promise.all([
    api(`/api/analytics/hosting/dtr/${id}`), api(`/api/analytics/forecast/dtr/${id}?hours=48`), api(`/api/dtrs/${id}`),
  ]);
  const maxLimit = Math.max(...Object.values(hc.limits_kw).map((v) => v + hc.existing_pv_kw), 1);
  const limitRow = (key) => {
    const room = hc.limits_kw[key];
    return `<div class="limit ${hc.binding_constraint === key ? "binding" : ""}">
      <span class="name">${esc(limitName(key))}${hc.binding_constraint === key ? " ★" : ""}</span>
      <div class="track"><span class="pv" style="width:${(hc.existing_pv_kw / maxLimit) * 100}%"></span>
        <span class="room" style="left:calc(${(hc.existing_pv_kw / maxLimit) * 100}% + 2px);width:${(room / maxLimit) * 100}%"></span></div>
      <span class="num small">+${num(room)} kW</span></div>`;
  };
  const m = hc.model;
  const weather = t(`weather.${fc.weather_source}`);
  main().innerHTML = `
    <div class="page-head">
      <div><a href="#dashboard" class="small">${esc(t("dtr.back"))}</a>
        <h1>${esc(pick(hc, "dtr_name"))} <span class="muted" style="font-weight:400">${esc(hc.dtr_code)}</span></h1>
        <div class="muted">${esc(t("dtr.meta", { feeder: pick(hc, "feeder_name"), kva: num(hc.rating_kva, 0), n: hc.consumers, area: t(`area.${hc.area_type}`) }))}</div></div>
      <div>${statusChip(hc.status)}</div>
    </div>
    <div class="grid kpis">
      ${kpi(t("kpi.installed"), `${num(hc.existing_pv_kw)} kW`, t("kpi.kusumSub", { kw: num(hc.kusum_pv_kw) }))}
      ${kpi(t("kpi.hosting"), `${num(hc.hosting_kw)} kW`, t("kpi.hostingSub", { x: limitName(hc.binding_constraint) }))}
      ${kpi(t("kpi.util"), `${num(hc.utilisation_pct, 0)}%`, t("kpi.queueSub", { kw: num(hc.pending_kw) }))}
      ${kpi(t("kpi.worstV"), `${hc.worst_case_now.voltage_pu} pu`, t("kpi.worstVSub", { kw: num(hc.worst_case_now.export_kw) }))}
      ${kpi(t("kpi.outlook"), hc.months_to_saturation === null ? esc(t("kpi.stable")) : esc(t("kpi.months", { n: num(hc.months_to_saturation) })), t("kpi.outlookSub", { r: num(hc.growth_kw_per_month, 2) }))}
    </div>
    <div class="grid two">
      <div class="card"><h2>${esc(t("dtr.limits"))}</h2>
        <div class="legend"><span><i class="box" style="background:var(--series-2)"></i>${esc(t("legend.installed"))}</span><span><i class="box" style="background:var(--series-3)"></i>${esc(t("legend.allowed"))}</span></div>
        ${["reverse_flow", "voltage", "policy_cap"].map(limitRow).join("")}
        <p class="hint">${esc(t("dtr.modelNote", { n: m.samples, pr: m.performance_ratio, g: m.peak_gen_per_kw, l: m.min_midday_load_kw, a: m.voltage_intercept_pu, b: m.voltage_sensitivity_pu_per_kw, r2: m.voltage_fit_r2 }))}</p></div>
      <div class="card"><h2>${esc(t("feas.title"))}</h2>
        <form id="feas-form" class="form-row">
          <label>${esc(t("feas.kw"))}<input name="kw" type="number" step="0.5" min="0.5" value="5" required></label>
          <label>${esc(t("feas.scheme"))}<select name="scheme"><option value="rooftop">${esc(t("feas.rooftop"))}</option><option value="kusum">${esc(t("scheme.kusum"))}</option></select></label>
          <button class="btn primary" type="submit">${esc(t("feas.check"))}</button>
        </form>
        <div id="feas-result" class="section"></div></div>
    </div>
    <div class="card section">
      <div class="page-head" style="margin-bottom:6px"><h2 style="margin:0">${esc(t("fc.title"))}</h2>
        <span class="small muted">${esc(t("fc.meta", { src: weather, s: num(fc.summary.solar_energy_kwh, 0), e: num(fc.summary.export_energy_kwh, 0), h: fc.summary.risk_hours }))}</span></div>
      <h3 class="muted" style="font-weight:500">${esc(t("fc.power"))}</h3>
      <div id="power-chart" class="chart"></div>
      <h3 class="muted section" style="font-weight:500">${esc(t("fc.voltage", { v: fc.limits.voltage_upper_pu }))}</h3>
      <div id="voltage-chart" class="chart"></div>
      <details><summary>${esc(t("fc.table"))}</summary><div class="table-wrap"><table>
        <thead><tr><th>${t("th.hour")}</th><th class="num">${t("th.ghi")}</th><th class="num">${t("th.solar")}</th><th class="num">${t("th.load")}</th><th class="num">${t("th.export")}</th><th class="num">${t("th.voltage")}</th><th>${t("th.risk")}</th></tr></thead>
        <tbody>${fc.points.map((p) => `<tr><td>${esc(p.ts.replace("T", " "))}</td><td class="num">${p.ghi_wm2}</td><td class="num">${p.solar_kw}</td><td class="num">${p.load_kw}</td><td class="num">${p.net_export_kw}</td><td class="num">${p.voltage_pu}</td><td>${p.risks.map((r) => statusChip("critical", t(`risk.${r}`))).join(" ")}</td></tr>`).join("")}</tbody>
      </table></div></details>
    </div>
    <div class="card section"><h2>${esc(t("cons.title"))}</h2><div class="table-wrap"><table>
      <thead><tr><th>${t("th.account")}</th><th>${t("th.name")}</th><th>${t("th.category")}</th><th>${t("th.scheme")}</th><th class="num">${t("th.pvKw")}</th><th>${t("th.commissioned")}</th></tr></thead>
      <tbody>${dtr.consumers.filter((c) => c.pv_kw > 0).map((c) => `<tr><td>${esc(c.account_no)}</td><td>${esc(c.name)}</td><td>${esc(t(`category.${c.category}`))}</td><td>${esc(c.scheme === "none" ? "" : t(`scheme.${c.scheme}`))}</td><td class="num">${c.pv_kw}</td><td>${esc(c.pv_commissioned_on || "")}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">${esc(t("cons.none"))}</td></tr>`}</tbody>
    </table></div></div>`;

  const labels = fc.points.map((p) => p.ts);
  lineChart($("#power-chart"), labels, [
    { name: t("series.load"), color: "var(--series-1)", values: fc.points.map((p) => p.load_kw) },
    { name: t("series.solar"), color: "var(--series-2)", values: fc.points.map((p) => p.solar_kw) },
    { name: t("series.export"), color: "var(--series-3)", values: fc.points.map((p) => p.net_export_kw) },
  ], { unit: "kW", limit: fc.limits.reverse_flow_kw, limitLabel: t("chart.rfLimit", { kw: fc.limits.reverse_flow_kw }) });
  lineChart($("#voltage-chart"), labels, [
    { name: t("series.voltage"), color: "var(--series-1)", values: fc.points.map((p) => p.voltage_pu) },
  ], { unit: "pu", limit: fc.limits.voltage_upper_pu, digits: 3, height: 170 });

  $("#feas-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    await withBusy(e.submitter, async () => {
      const r = await api("/api/analytics/feasibility", { method: "POST", body: { dtr_id: Number(id), kw: Number(f.get("kw")), scheme: f.get("scheme") } });
      $("#feas-result").innerHTML = `<div class="row">${statusChip(r.recommendation)}<b>${esc(t("feas.result", { kw: num(r.recommended_kw), req: num(r.requested_kw) }))}</b></div><p class="small">${esc(pick(r, "reason"))}</p>`;
    });
  });
}

// Line chart: single y-axis, 2px lines, crosshair + tooltip, optional dashed limit line.
function lineChart(el, labels, series, { unit = "", limit = null, limitLabel = "", digits = 1, height = 240 } = {}) {
  const W = 900, H = height, pad = { l: 48, r: 12, t: 10, b: 26 };
  const all = series.flatMap((s) => s.values).concat(limit !== null ? [limit] : []);
  let lo = Math.min(...all), hi = Math.max(...all);
  if (unit === "kW") lo = Math.min(lo, 0);
  const span = hi - lo || 1;
  lo -= span * 0.05; hi += span * 0.08;
  const x = (i) => pad.l + (i / Math.max(labels.length - 1, 1)) * (W - pad.l - pad.r);
  const y = (v) => pad.t + (1 - (v - lo) / (hi - lo)) * (H - pad.t - pad.b);
  const ticks = Array.from({ length: 5 }, (_, i) => lo + ((hi - lo) * i) / 4);
  const fmt = (v) => Number(v).toFixed(unit === "pu" ? 2 : 0);
  const xTicks = labels.map((l, i) => [l, i]).filter(([l]) => l.endsWith("T00:00") || l.endsWith("T12:00"));
  const path = (vals) => vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");

  el.innerHTML = `${series.length > 1 ? `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${esc(s.name)}</span>`).join("")}</div>` : ""}
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map((s) => s.name).join(", "))} ${esc(t("chart.forecast"))}">
      ${ticks.map((v) => `<line class="gridline" x1="${pad.l}" x2="${W - pad.r}" y1="${y(v)}" y2="${y(v)}"/><text class="axis-label" x="${pad.l - 6}" y="${y(v) + 4}" text-anchor="end">${fmt(v)}</text>`).join("")}
      ${unit === "kW" && lo < 0 ? `<line class="baseline" x1="${pad.l}" x2="${W - pad.r}" y1="${y(0)}" y2="${y(0)}"/>` : ""}
      ${xTicks.map(([l, i]) => `<text class="axis-label" x="${x(i)}" y="${H - 6}" text-anchor="middle">${l.slice(5, 10)} ${l.slice(11, 16)}</text>`).join("")}
      ${limit !== null && limit <= hi ? `<line class="limit-line" x1="${pad.l}" x2="${W - pad.r}" y1="${y(limit)}" y2="${y(limit)}"/><text class="axis-label" x="${W - pad.r}" y="${y(limit) - 5}" text-anchor="end">${esc(limitLabel || String(limit))}</text>` : ""}
      ${series.map((s) => `<path class="series" d="${path(s.values)}" stroke="${s.color}"/>`).join("")}
      <g class="hover" style="display:none"><line class="crosshair" y1="${pad.t}" y2="${H - pad.b}"/>
        ${series.map((s) => `<circle class="dot" r="4.5" fill="${s.color}"/>`).join("")}</g>
      <rect x="${pad.l}" y="0" width="${W - pad.l - pad.r}" height="${H}" fill="transparent"/>
    </svg><div class="tooltip" hidden></div>`;

  const svg = $("svg", el), hover = $(".hover", el), tip = $(".tooltip", el);
  const showAt = (clientX) => {
    const box = svg.getBoundingClientRect();
    const px = ((clientX - box.left) / box.width) * W;
    const i = Math.max(0, Math.min(labels.length - 1, Math.round(((px - pad.l) / (W - pad.l - pad.r)) * (labels.length - 1))));
    hover.style.display = "";
    $("line", hover).setAttribute("x1", x(i)); $("line", hover).setAttribute("x2", x(i));
    hover.querySelectorAll("circle").forEach((c, k) => { c.setAttribute("cx", x(i)); c.setAttribute("cy", y(series[k].values[i])); });
    tip.hidden = false;
    tip.innerHTML = `<div class="t">${esc(labels[i].replace("T", " "))}</div>` +
      series.map((s) => `<div class="r"><span><i style="background:${s.color}"></i>${esc(s.name)}</span><b>${Number(s.values[i]).toFixed(digits)} ${unit}</b></div>`).join("");
    const left = (x(i) / W) * box.width;
    tip.style.left = `${left > box.width / 2 ? left - tip.offsetWidth - 12 : left + 12}px`;
    tip.style.top = `${series.length > 1 ? 30 : 4}px`;
  };
  svg.addEventListener("mousemove", (e) => showAt(e.clientX));
  svg.addEventListener("touchmove", (e) => showAt(e.touches[0].clientX), { passive: true });
  svg.addEventListener("mouseleave", () => { hover.style.display = "none"; tip.hidden = true; });
}

// ------------------------------------------------------------------ applications
async function viewApplications() {
  const [apps, dtrs] = await Promise.all([api("/api/applications"), api("/api/dtrs")]);
  main().innerHTML = `
    <div class="page-head"><div><h1>${esc(t("apps.title"))}</h1>
      <div class="muted">${esc(t("apps.sub"))}</div></div></div>
    <div class="card"><h2>${esc(t("apps.new"))}</h2>
      <form id="app-form" class="form-row">
        <label>${esc(t("th.dtr"))}<select name="dtr_id" required>${dtrs.map((d) => `<option value="${d.id}">${esc(d.code)} · ${esc(pick(d, "name"))} (${num(d.rating_kva, 0)} kVA)</option>`).join("")}</select></label>
        <label>${esc(t("apps.applicant"))}<input name="applicant_name" required minlength="2" placeholder="${esc(t("apps.namePh"))}"></label>
        <label>${esc(t("feas.scheme"))}<select name="scheme"><option value="rooftop">${esc(t("scheme.rooftop"))}</option><option value="kusum">${esc(t("scheme.kusum"))}</option></select></label>
        <label>${esc(t("apps.kw"))}<input name="requested_kw" type="number" min="0.5" step="0.5" required></label>
        <button class="btn primary" type="submit">${esc(t("apps.submit"))}</button>
      </form></div>
    <div class="card section"><div class="table-wrap"><table>
      <thead><tr><th>${t("th.id")}</th><th>${t("apps.applicant")}</th><th>${t("th.dtr")}</th><th>${t("th.scheme")}</th><th class="num">${t("th.requested")}</th><th>${t("th.status")}</th><th>${t("th.rec")}</th><th></th></tr></thead>
      <tbody>${apps.map(appRow).join("") || `<tr><td colspan="8" class="empty">${esc(t("apps.none"))}</td></tr>`}</tbody>
    </table></div></div>`;

  $("#app-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    await withBusy(e.submitter, async () => {
      const created = await api("/api/applications", { method: "POST", body: { ...f, dtr_id: Number(f.dtr_id), requested_kw: Number(f.requested_kw) } });
      await api(`/api/applications/${created.id}/evaluate`, { method: "POST" });
      toast(t("toast.submitted", { id: created.id }));
      viewApplications();
    });
  });

  main().querySelectorAll("[data-act]").forEach((btn) => btn.addEventListener("click", () => withBusy(btn, async () => {
    const id = btn.dataset.id, act = btn.dataset.act;
    if (act === "evaluate") await api(`/api/applications/${id}/evaluate`, { method: "POST" });
    if (act === "approve") {
      const kw = prompt(t("prompt.approveKw"), btn.dataset.kw);
      if (!kw) return;
      await api(`/api/applications/${id}/decision`, { method: "POST", body: { decision: "approve", approved_kw: Number(kw) } });
    }
    if (act === "reject") await api(`/api/applications/${id}/decision`, { method: "POST", body: { decision: "reject", note: prompt(t("prompt.rejectReason")) || null } });
    if (act === "edit") {
      const kw = prompt(t("prompt.newKw"), btn.dataset.kw);
      if (!kw) return;
      await api(`/api/applications/${id}`, { method: "PUT", body: { requested_kw: Number(kw) } });
    }
    if (act === "delete") {
      if (!confirm(t("confirm.deleteApp", { id }))) return;
      await api(`/api/applications/${id}`, { method: "DELETE" });
    }
    toast(t("toast.saved"));
    viewApplications();
  })));
}

function appRow(a) {
  const open = a.status === "pending" || a.status === "evaluated";
  const button = (act, label, extra = "", cls = "btn small") => `<button class="${cls}" data-act="${act}" data-id="${a.id}" ${extra}>${esc(t(label))}</button>`;
  const actions = [
    open ? button("evaluate", "btn.evaluate") : "",
    a.status === "evaluated" && a.recommended_kw > 0 ? button("approve", "btn.approve", `data-kw="${a.recommended_kw}"`) : "",
    a.status === "evaluated" ? button("reject", "btn.reject") : "",
    open ? button("edit", "btn.edit", `data-kw="${a.requested_kw}"`, "btn small ghost") : "",
    button("delete", "btn.delete", "", "btn small ghost danger"),
  ].join(" ");
  const rec = a.recommendation
    ? `${statusChip(a.recommendation, `${t(`status.${a.recommendation}`)} · ${num(a.recommended_kw)} kW`)}<div class="small muted" style="max-width:380px">${esc(pick(a, "decision_reason"))}</div>`
    : `<span class="muted small">${esc(t("apps.notEval"))}</span>`;
  return `<tr><td>${a.id}</td><td>${esc(a.applicant_name)}</td><td><a href="#dtr/${a.dtr_id}">${esc(a.dtr_code)}</a><div class="small muted">${esc(pick(a, "dtr_name"))}</div></td><td>${esc(t(`scheme.${a.scheme}`))}</td>
    <td class="num">${num(a.requested_kw)} kW</td>
    <td>${statusChip(a.status)}${a.approved_kw ? `<div class="small muted">${esc(t("apps.by", { kw: num(a.approved_kw), name: a.decided_by_name }))}</div>` : ""}</td>
    <td>${rec}</td><td><div class="row" style="gap:4px;flex-wrap:nowrap">${actions}</div></td></tr>`;
}

// ------------------------------------------------------------------ alerts
async function viewAlerts() {
  const alerts = await api("/api/alerts?include_acknowledged=true");
  const open = alerts.filter((a) => !a.acknowledged);
  main().innerHTML = `
    <div class="page-head"><div><h1>${esc(t("alerts.title"))}</h1><div class="muted">${esc(t("alerts.sub"))}</div></div>
      <button class="btn primary" id="rescan">${esc(t("alerts.rescan"))}</button></div>
    <div class="card">${alerts.length ? alerts.map((a) => `
      <div class="alert-row" style="${a.acknowledged ? "opacity:.55" : ""}">
        <div>${statusChip(a.severity)}</div>
        <div>${esc(pick(a, "message"))}<span class="tag">${esc(t(`alertType.${a.alert_type}`))}</span>
          <div class="small muted"><a href="#dtr/${a.dtr_id}">${esc(a.dtr_code)} · ${esc(pick(a, "dtr_name"))}</a> · ${esc(t("alerts.raised", { t: a.created_at }))}</div></div>
        <div>${a.acknowledged ? `<span class="small muted">${esc(t("alerts.acked"))}</span>` : `<button class="btn small" data-ack="${a.id}">${esc(t("btn.ack"))}</button>`}</div>
      </div>`).join("") : `<div class="empty">${esc(t("alerts.none"))}</div>`}</div>
    <p class="hint section">${esc(t("alerts.open", { n: open.length }))}</p>`;
  main().querySelectorAll("[data-ack]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    await api(`/api/alerts/${b.dataset.ack}/ack`, { method: "POST" });
    refreshAlertCount();
    viewAlerts();
  })));
  $("#rescan").addEventListener("click", (e) => withBusy(e.target, async () => {
    await api("/api/agent/scan", { method: "POST", body: { with_brief: false } });
    refreshAlertCount();
    viewAlerts();
  }));
}

// ------------------------------------------------------------------ copilot
async function viewCopilot() {
  const suggestions = ["copilot.s1", "copilot.s2", "copilot.s3", "copilot.s4", "copilot.s5"].map((k) => t(k));
  main().innerHTML = `
    <div class="page-head"><div><h1>${esc(t("copilot.title"))}</h1>
      <div class="muted">${esc(t(state.agent?.llm_enabled ? "copilot.online" : "copilot.offline"))}</div></div>
      <button class="btn ghost small" id="clear-chat">${esc(t("copilot.clear"))}</button></div>
    <div class="chat card">
      <div class="messages" id="messages"></div>
      <div><div class="suggestions">${suggestions.map((s) => `<button class="btn small" data-q="${esc(s)}">${esc(s)}</button>`).join("")}</div>
        <form id="chat-form"><input name="q" autocomplete="off" placeholder="${esc(t("copilot.placeholder"))}" required maxlength="1000">
        <button class="btn primary" type="submit">${esc(t("copilot.ask"))}</button></form></div>
    </div>`;
  renderMessages();
  const ask = async (q, btn) => {
    state.chat.push({ role: "user", content: q });
    renderMessages(true);
    await withBusy(btn, async () => {
      const history = state.chat.slice(0, -1).map(({ role, content }) => ({ role, content })).slice(-6);
      const r = await api("/api/agent/chat", { method: "POST", body: { message: q, history } });
      state.chat.push({ role: "assistant", content: r.answer, mode: r.mode, tools: r.tools_used, usage: r.usage });
    });
    renderMessages();
  };
  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = e.target.q;
    const q = input.value.trim();
    input.value = "";
    if (q) ask(q, e.submitter);
  });
  main().querySelectorAll("[data-q]").forEach((b) => b.addEventListener("click", () => ask(b.dataset.q, $("#chat-form button"))));
  $("#clear-chat").addEventListener("click", () => { state.chat = []; renderMessages(); });
}

function renderMessages(thinking = false) {
  const box = $("#messages");
  if (!box) return;
  const meta = (m) => t("copilot.meta", { engine: modeName(m.mode), tools: m.tools?.join(", ") || t("copilot.noTools"), i: m.usage?.prompt_tokens ?? 0, o: m.usage?.completion_tokens ?? 0 });
  box.innerHTML = state.chat.map((m) => m.role === "user"
    ? `<div class="msg user">${esc(m.content)}</div>`
    : `<div class="msg bot">${md(m.content)}<div class="meta">${esc(meta(m))}</div></div>`).join("")
    + (thinking ? `<div class="msg bot muted">${esc(t("copilot.thinking"))}</div>` : "")
    + (state.chat.length ? "" : `<div class="empty">${esc(t("copilot.empty"))}</div>`);
  box.scrollTop = box.scrollHeight;
}

// Minimal, safe markdown: escape first, then bold and bullet lists.
function md(text) {
  const lines = esc(text).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").split("\n");
  let html = "", inList = false;
  for (const line of lines) {
    const item = line.match(/^\s*[-*•]\s+(.*)/);
    if (item) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${item[1]}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    html += line.trim() ? `<div>${line}</div>` : "";
  }
  return html + (inList ? "</ul>" : "");
}

// ------------------------------------------------------------------ assets (admin CRUD)
async function viewAssets() {
  const [feeders, dtrs, subs] = await Promise.all([api("/api/feeders"), api("/api/dtrs"), api("/api/substations")]);
  const admin = state.user.role === "admin";
  const L = (k) => esc(t(k));
  main().innerHTML = `
    <div class="page-head"><div><h1>${L("assets.title")}</h1><div class="muted">${L(admin ? "assets.admin" : "assets.readonly")}</div></div></div>
    <div class="card"><h2>${L("assets.feeders")}</h2>
      ${admin ? `<form id="feeder-form" class="form-row">
        <label>${L("assets.substation")}<select name="substation_id">${subs.map((s) => `<option value="${s.id}">${esc(pick(s, "name"))}</option>`).join("")}</select></label>
        <label>${L("assets.code")}<input name="code" required placeholder="FDR-N3"></label><label>${L("assets.name")}<input name="name" required></label>
        <label>${L("assets.rating")}<input name="rating_kva" type="number" min="1" required value="4000"></label>
        <button class="btn primary">${L("assets.addFeeder")}</button></form>` : ""}
      <div class="table-wrap section"><table><thead><tr><th>${L("th.code")}</th><th>${L("th.name")}</th><th>${L("th.substation")}</th><th class="num">${L("th.kv")}</th><th class="num">${L("th.kva")}</th><th class="num">${L("th.dtrs")}</th><th></th></tr></thead>
      <tbody>${feeders.map((f) => `<tr><td><b>${esc(f.code)}</b></td><td>${esc(pick(f, "name"))}</td><td>${esc(pick(f, "substation_name"))}</td><td class="num">${f.voltage_kv}</td><td class="num">${num(f.rating_kva, 0)}</td><td class="num">${f.dtr_count}</td>
        <td>${admin ? `<button class="btn small ghost danger" data-del-feeder="${f.id}">${L("btn.delete")}</button>` : ""}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card section"><h2>${L("table.dtrs")}</h2>
      ${admin ? `<form id="dtr-form" class="form-row">
        <label>${L("th.feeder")}<select name="feeder_id">${feeders.map((f) => `<option value="${f.id}">${esc(f.code)} · ${esc(pick(f, "name"))}</option>`).join("")}</select></label>
        <label>${L("assets.code")}<input name="code" required placeholder="DTR-N1-05"></label><label>${L("assets.name")}<input name="name" required></label>
        <label>${L("assets.rating")}<input name="rating_kva" type="number" min="1" required value="100"></label>
        <label>${L("assets.area")}<select name="area_type">${["urban", "rural", "agri"].map((a) => `<option value="${a}">${L(`area.${a}`)}</option>`).join("")}</select></label>
        <button class="btn primary">${L("assets.addDtr")}</button></form>` : ""}
      <div class="table-wrap section"><table><thead><tr><th>${L("th.code")}</th><th>${L("th.name")}</th><th>${L("th.feeder")}</th><th>${L("th.area")}</th><th class="num">${L("th.kva")}</th><th class="num">${L("th.consumers")}</th><th class="num">${L("th.solarKw")}</th><th></th></tr></thead>
      <tbody>${dtrs.map((d) => `<tr><td><a href="#dtr/${d.id}"><b>${esc(d.code)}</b></a></td><td>${esc(pick(d, "name"))}</td><td>${esc(d.feeder_code)}</td><td>${L(`area.${d.area_type}`)}</td>
        <td class="num">${num(d.rating_kva, 0)}</td><td class="num">${d.consumer_count}</td><td class="num">${num(d.pv_kw)}</td>
        <td>${admin ? `<div class="row" style="gap:4px;flex-wrap:nowrap"><button class="btn small ghost" data-edit-dtr="${d.id}" data-kva="${d.rating_kva}">${L("assets.upgrade")}</button><button class="btn small ghost danger" data-del-dtr="${d.id}">${L("btn.delete")}</button></div>` : ""}</td></tr>`).join("")}</tbody></table></div></div>`;
  if (!admin) return;

  const submit = (formId, path, numeric) => $(formId).addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    numeric.forEach((k) => (body[k] = Number(body[k])));
    await withBusy(e.submitter, async () => { await api(path, { method: "POST", body }); toast(t("toast.created")); viewAssets(); });
  });
  submit("#feeder-form", "/api/feeders", ["substation_id", "rating_kva"]);
  submit("#dtr-form", "/api/dtrs", ["feeder_id", "rating_kva"]);
  main().querySelectorAll("[data-del-feeder],[data-del-dtr]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const isFeeder = !!b.dataset.delFeeder;
    if (!confirm(t(isFeeder ? "confirm.delFeeder" : "confirm.delDtr"))) return;
    await api(isFeeder ? `/api/feeders/${b.dataset.delFeeder}` : `/api/dtrs/${b.dataset.delDtr}`, { method: "DELETE" });
    toast(t("toast.deleted")); viewAssets();
  })));
  main().querySelectorAll("[data-edit-dtr]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const kva = prompt(t("prompt.newKva"), b.dataset.kva);
    if (!kva) return;
    await api(`/api/dtrs/${b.dataset.editDtr}`, { method: "PUT", body: { rating_kva: Number(kva) } });
    toast(t("toast.dtrUpdated")); viewAssets();
  })));
}

// ------------------------------------------------------------------ agent log
async function viewRuns() {
  const { runs, totals } = await api("/api/agent/runs");
  main().innerHTML = `
    <div class="page-head"><div><h1>${esc(t("runs.title"))}</h1><div class="muted">${esc(t("runs.sub"))}</div></div>
      <div class="muted">${esc(t("runs.total", { i: num(totals.prompt_tokens, 0), o: num(totals.completion_tokens, 0) }))}</div></div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>${t("th.when")}</th><th>${t("th.user")}</th><th>${t("th.kind")}</th><th>${t("th.engine")}</th><th>${t("th.question")}</th><th>${t("th.tools")}</th><th class="num">${t("th.tokens")}</th></tr></thead>
      <tbody>${runs.map((r) => `<tr><td class="small">${esc(r.created_at)}</td><td>${esc(r.user_name || "")}</td><td>${esc(t(`kind.${r.kind}`))}</td><td>${esc(modeName(r.mode))}</td>
        <td>${esc(r.question)}</td><td class="small">${esc(r.tools_used)}</td><td class="num">${r.prompt_tokens}/${r.completion_tokens}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">${esc(t("runs.none"))}</td></tr>`}</tbody>
    </table></div></div>`;
}

// ------------------------------------------------------------------ boot
(async function boot() {
  state.lang = load("sc_lang") === "te" ? "te" : "en";
  try { await loadLocales(); } catch (_) { /* fall back to keys; English markup stays */ }
  applyStaticText();
  state.token = load("sc_token");
  if (!state.token) return showAuth();
  try {
    state.user = await api("/api/auth/me");
    startApp();
  } catch (_) {
    logout();
  }
})();
