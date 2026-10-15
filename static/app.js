/* SolarClear single-page UI. Vanilla JS, no build step. Talks to the REST API with a bearer token. */
"use strict";

const state = { token: null, user: null, chat: [], agent: null };
const $ = (sel, root = document) => root.querySelector(sel);
const main = () => $("#main");

// ------------------------------------------------------------------ helpers
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const num = (v, d = 1) => (v === null || v === undefined ? "–" : Number(v).toLocaleString(undefined, { maximumFractionDigits: d }));
// Internal mode codes -> display names shown in the UI.
const modeName = (m) => (m === "azure" ? "D360 AI" : "Rule engine");
const statusChip = (s, label) => `<span class="status ${esc(s)}">${esc(label || s)}</span>`;

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
    headers: { "Content-Type": "application/json", ...(state.token ? { Authorization: `Bearer ${state.token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 && state.token) {
    logout();
    throw new Error("Session expired, please sign in again");
  }
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((d) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join("; ")
      : data.detail;
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return data;
}

async function withBusy(button, fn) {
  const label = button?.textContent;
  if (button) { button.disabled = true; button.textContent = "Working…"; }
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
    document.querySelectorAll("[data-auth-tab]").forEach((t) => t.classList.toggle("active", t === tab));
    $("#login-form").hidden = tab.dataset.authTab !== "login";
    $("#register-form").hidden = tab.dataset.authTab !== "register";
    $("#auth-error").textContent = "";
  }));

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try { setSession(await api("/api/auth/login", { method: "POST", body: Object.fromEntries(f) })); }
  catch (err) { $("#auth-error").textContent = err.message; }
});

$("#register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try { setSession(await api("/api/auth/register", { method: "POST", body: Object.fromEntries(f) })); }
  catch (err) { $("#auth-error").textContent = err.message; }
});

$("#logout").addEventListener("click", logout);

async function startApp() {
  $("#auth-view").hidden = true;
  $("#app-view").hidden = false;
  $("#user-label").textContent = `${state.user.name} · ${state.user.role}`;
  try {
    state.agent = await api("/api/agent/status");
    $("#agent-mode").innerHTML = state.agent.llm_enabled ? `<span class="ai-badge">● D360 AI engine online</span>` : "D360 AI engine: offline (rule mode)";
  } catch (_) { /* non-fatal */ }
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
  main().innerHTML = `<div class="empty">Loading…</div>`;
  (routes[name] || viewDashboard)(arg).catch((err) => {
    main().innerHTML = `<div class="card error">${esc(err.message)}</div>`;
  });
}
window.addEventListener("hashchange", route);

// ------------------------------------------------------------------ dashboard
async function viewDashboard() {
  const data = await api("/api/analytics/overview");
  const k = data.kpis;
  main().innerHTML = `
    <div class="page-head">
      <div><h1>Network hosting capacity</h1>
        <div class="muted">Limits: voltage ≤ ${data.limits.voltage_upper_pu} pu · reverse flow ≤ ${data.limits.reverse_flow_limit_pct}% of DTR kVA · policy cap ${data.limits.policy_cap_pct}% of kVA</div></div>
      <div class="row">
        <label class="row small" style="display:flex"><input type="checkbox" id="with-brief" ${state.agent?.llm_enabled ? "checked" : "disabled"}> AI shift brief</label>
        <button class="btn primary" id="scan-btn">Run Grid-Watch agent</button>
      </div>
    </div>
    <div class="grid kpis">
      ${kpi("Installed solar", `${num(k.installed_pv_kw, 0)} kW`, `${k.dtrs} DTRs monitored`)}
      ${kpi("Hosting headroom", `${num(k.hosting_headroom_kw, 0)} kW`, "additional PV the network can absorb")}
      ${kpi("Saturated DTRs", k.saturated_dtrs, `${k.watch_dtrs} more on watch`)}
      ${kpi("Open applications", k.open_applications, `${num(k.queued_kw)} kW queued`)}
      ${kpi("Open alerts", k.open_alerts, `${k.critical_alerts} critical`)}
    </div>
    <div id="scan-result"></div>
    <div class="grid two section">
      ${data.feeders.map(feederCard).join("")}
    </div>
    <div class="card section">
      <h2>Distribution transformers</h2>
      <div class="table-wrap"><table>
        <thead><tr><th>DTR</th><th>Feeder</th><th class="num">kVA</th><th class="num">Solar kW</th><th class="num">Headroom kW</th>
          <th>Utilisation</th><th>Binding limit</th><th class="num">Months to saturation</th><th>Status</th></tr></thead>
        <tbody>${data.dtrs.sort((a, b) => b.utilisation_pct - a.utilisation_pct).map(dtrRow).join("")}</tbody>
      </table></div>
    </div>`;
  main().querySelectorAll("tr[data-dtr]").forEach((tr) => tr.addEventListener("click", () => (location.hash = `dtr/${tr.dataset.dtr}`)));
  $("#scan-btn").addEventListener("click", (e) => withBusy(e.target, runScan));
}

const kpi = (label, value, sub) => `<div class="card kpi"><div class="label">${label}</div><div class="value">${value}</div><div class="sub">${sub}</div></div>`;
const LIMIT_NAMES = { reverse_flow: "Reverse flow", voltage: "Voltage rise", policy_cap: "Policy cap", feeder_reverse_flow: "Feeder reverse flow", sum_of_dtrs: "DTR limits" };

function feederCard(f) {
  return `<div class="card">
    <h3>${esc(f.feeder_code)} <span class="muted small">${esc(f.feeder_name)}</span></h3>
    <div class="row small muted" style="gap:18px">
      <span><b class="value">${num(f.existing_pv_kw, 0)}</b> kW solar</span>
      <span><b>${num(f.hosting_kw, 0)}</b> kW headroom</span>
      <span>${f.dtrs} DTRs</span>
    </div>
    <div class="row small" style="margin-top:8px;gap:14px">
      ${statusChip("saturated", `${f.saturated_dtrs} saturated`)} ${statusChip("watch", `${f.watch_dtrs} watch`)}
      <span class="muted">limited by ${LIMIT_NAMES[f.binding_constraint]}</span>
    </div></div>`;
}

function utilBar(pct) {
  const cls = pct >= 90 ? "hi" : pct >= 70 ? "mid" : "";
  return `<div class="util"><div class="bar"><span class="${cls}" style="width:${Math.min(pct, 100)}%"></span></div><span class="small">${num(pct, 0)}%</span></div>`;
}

function dtrRow(d) {
  return `<tr class="click" data-dtr="${d.dtr_id}">
    <td><b>${esc(d.dtr_code)}</b><div class="small muted">${esc(d.area_type)}</div></td><td>${esc(d.feeder_code)}</td>
    <td class="num">${num(d.rating_kva, 0)}</td><td class="num">${num(d.existing_pv_kw)}</td><td class="num">${num(d.hosting_kw)}</td>
    <td>${utilBar(d.utilisation_pct)}</td><td>${LIMIT_NAMES[d.binding_constraint]}</td>
    <td class="num">${d.months_to_saturation === null ? "–" : num(d.months_to_saturation)}</td><td>${statusChip(d.status)}</td></tr>`;
}

async function runScan() {
  const result = await api("/api/agent/scan", { method: "POST", body: { with_brief: $("#with-brief")?.checked || false } });
  const apps = result.applications_evaluated;
  $("#scan-result").innerHTML = `<div class="card scan-result">
    <h2>Grid-Watch agent result</h2>
    <p>${esc(result.summary)}</p>
    ${result.brief ? `<h3>D360 AI shift brief</h3><div class="brief">${md(result.brief)}</div>` : ""}
    ${apps.length ? `<p class="small muted">Applications cleared: ${apps.map((a) => `#${a.id} ${esc(a.dtr)} ${a.kw} kW → ${a.rec} ${a.rec_kw} kW`).join(" · ")}</p>` : ""}
    <p class="small muted">Engine: ${modeName(result.mode)} · tokens: ${result.usage.prompt_tokens} in / ${result.usage.completion_tokens} out${result.webhook_notified ? " · webhook notified" : ""}</p>
    <div class="row"><a href="#alerts">View alerts →</a><a href="#applications">Review applications →</a></div></div>`;
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
      <span class="name">${LIMIT_NAMES[key]}${hc.binding_constraint === key ? " ★" : ""}</span>
      <div class="track"><span class="pv" style="width:${(hc.existing_pv_kw / maxLimit) * 100}%"></span>
        <span class="room" style="left:calc(${(hc.existing_pv_kw / maxLimit) * 100}% + 2px);width:${(room / maxLimit) * 100}%"></span></div>
      <span class="num small">+${num(room)} kW</span></div>`;
  };
  const m = hc.model;
  main().innerHTML = `
    <div class="page-head">
      <div><a href="#dashboard" class="small">← Dashboard</a>
        <h1>${esc(hc.dtr_code)} <span class="muted" style="font-weight:400">${esc(hc.dtr_name)}</span></h1>
        <div class="muted">${esc(hc.feeder_code)} · ${num(hc.rating_kva, 0)} kVA · ${hc.consumers} consumers · ${esc(hc.area_type)}</div></div>
      <div>${statusChip(hc.status)}</div>
    </div>
    <div class="grid kpis">
      ${kpi("Installed solar", `${num(hc.existing_pv_kw)} kW`, `${num(hc.kusum_pv_kw)} kW under KUSUM`)}
      ${kpi("Hosting capacity", `${num(hc.hosting_kw)} kW`, `limited by ${LIMIT_NAMES[hc.binding_constraint]}`)}
      ${kpi("Utilisation", `${num(hc.utilisation_pct, 0)}%`, `${num(hc.pending_kw)} kW in queue`)}
      ${kpi("Worst-case voltage now", `${hc.worst_case_now.voltage_pu} pu`, `export ${num(hc.worst_case_now.export_kw)} kW at peak sun`)}
      ${kpi("Saturation outlook", hc.months_to_saturation === null ? "Stable" : `${num(hc.months_to_saturation)} mo`, `adoption ${num(hc.growth_kw_per_month, 2)} kW/month`)}
    </div>
    <div class="grid two">
      <div class="card"><h2>Hosting limits</h2>
        <div class="legend"><span><i class="box" style="background:var(--series-2)"></i>Installed PV</span><span><i class="box" style="background:var(--series-3)"></i>Additional PV allowed</span></div>
        ${["reverse_flow", "voltage", "policy_cap"].map(limitRow).join("")}
        <p class="hint">Learned from ${m.samples} hourly readings: PR ${m.performance_ratio}, peak ${m.peak_gen_per_kw} kW/kWp, min midday load ${m.min_midday_load_kw} kW,
          voltage = ${m.voltage_intercept_pu} + ${m.voltage_sensitivity_pu_per_kw} × export (R² ${m.voltage_fit_r2}).</p></div>
      <div class="card"><h2>Net-meter feasibility check</h2>
        <form id="feas-form" class="form-row">
          <label>Capacity (kW)<input name="kw" type="number" step="0.5" min="0.5" value="5" required></label>
          <label>Scheme<select name="scheme"><option value="rooftop">Rooftop net-metering</option><option value="kusum">PM-KUSUM</option></select></label>
          <button class="btn primary" type="submit">Check clearance</button>
        </form>
        <div id="feas-result" class="section"></div></div>
    </div>
    <div class="card section">
      <div class="page-head" style="margin-bottom:6px"><h2 style="margin:0">48-hour forecast</h2>
        <span class="small muted">Weather: ${esc(fc.weather_source)} · solar ${num(fc.summary.solar_energy_kwh, 0)} kWh · export ${num(fc.summary.export_energy_kwh, 0)} kWh · ${fc.summary.risk_hours} risk hour(s)</span></div>
      <h3 class="muted" style="font-weight:500">Power (kW)</h3>
      <div id="power-chart" class="chart"></div>
      <h3 class="muted section" style="font-weight:500">Voltage at DTR (pu) · dashed line = ${fc.limits.voltage_upper_pu} pu limit</h3>
      <div id="voltage-chart" class="chart"></div>
      <details><summary>Show forecast table</summary><div class="table-wrap"><table>
        <thead><tr><th>Hour</th><th class="num">GHI W/m²</th><th class="num">Solar kW</th><th class="num">Load kW</th><th class="num">Net export kW</th><th class="num">Voltage pu</th><th>Risk</th></tr></thead>
        <tbody>${fc.points.map((p) => `<tr><td>${esc(p.ts.replace("T", " "))}</td><td class="num">${p.ghi_wm2}</td><td class="num">${p.solar_kw}</td><td class="num">${p.load_kw}</td><td class="num">${p.net_export_kw}</td><td class="num">${p.voltage_pu}</td><td>${p.risks.map((r) => statusChip("critical", r)).join(" ")}</td></tr>`).join("")}</tbody>
      </table></div></details>
    </div>
    <div class="card section"><h2>Consumers with solar</h2><div class="table-wrap"><table>
      <thead><tr><th>Account</th><th>Name</th><th>Category</th><th>Scheme</th><th class="num">PV kW</th><th>Commissioned</th></tr></thead>
      <tbody>${dtr.consumers.filter((c) => c.pv_kw > 0).map((c) => `<tr><td>${esc(c.account_no)}</td><td>${esc(c.name)}</td><td>${esc(c.category)}</td><td>${esc(c.scheme)}</td><td class="num">${c.pv_kw}</td><td>${esc(c.pv_commissioned_on || "")}</td></tr>`).join("") || `<tr><td colspan="6" class="empty">No solar installed yet</td></tr>`}</tbody>
    </table></div></div>`;

  const labels = fc.points.map((p) => p.ts);
  lineChart($("#power-chart"), labels, [
    { name: "Load", color: "var(--series-1)", values: fc.points.map((p) => p.load_kw) },
    { name: "Solar", color: "var(--series-2)", values: fc.points.map((p) => p.solar_kw) },
    { name: "Net export", color: "var(--series-3)", values: fc.points.map((p) => p.net_export_kw) },
  ], { unit: "kW", limit: fc.limits.reverse_flow_kw, limitLabel: `reverse-flow limit ${fc.limits.reverse_flow_kw} kW` });
  lineChart($("#voltage-chart"), labels, [
    { name: "Voltage", color: "var(--series-1)", values: fc.points.map((p) => p.voltage_pu) },
  ], { unit: "pu", limit: fc.limits.voltage_upper_pu, digits: 3, height: 170 });

  $("#feas-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    await withBusy(e.submitter, async () => {
      const r = await api("/api/analytics/feasibility", { method: "POST", body: { dtr_id: Number(id), kw: Number(f.get("kw")), scheme: f.get("scheme") } });
      $("#feas-result").innerHTML = `<div class="row">${statusChip(r.recommendation, r.recommendation.toUpperCase())}<b>${num(r.recommended_kw)} kW clearable</b> of ${num(r.requested_kw)} kW</div><p class="small">${esc(r.reason)}</p>`;
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

  el.innerHTML = `${series.length > 1 ? `<div class="legend">${series.map((s) => `<span><i style="background:${s.color}"></i>${s.name}</span>`).join("")}</div>` : ""}
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(series.map((s) => s.name).join(", "))} forecast">
      ${ticks.map((t) => `<line class="gridline" x1="${pad.l}" x2="${W - pad.r}" y1="${y(t)}" y2="${y(t)}"/><text class="axis-label" x="${pad.l - 6}" y="${y(t) + 4}" text-anchor="end">${fmt(t)}</text>`).join("")}
      ${unit === "kW" && lo < 0 ? `<line class="baseline" x1="${pad.l}" x2="${W - pad.r}" y1="${y(0)}" y2="${y(0)}"/>` : ""}
      ${xTicks.map(([l, i]) => `<text class="axis-label" x="${x(i)}" y="${H - 6}" text-anchor="middle">${l.slice(5, 10)} ${l.slice(11, 16)}</text>`).join("")}
      ${limit !== null && limit <= hi ? `<line class="limit-line" x1="${pad.l}" x2="${W - pad.r}" y1="${y(limit)}" y2="${y(limit)}"/><text class="axis-label" x="${W - pad.r}" y="${y(limit) - 5}" text-anchor="end">${esc(limitLabel || `limit ${limit}`)}</text>` : ""}
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
      series.map((s) => `<div class="r"><span><i style="background:${s.color}"></i>${s.name}</span><b>${Number(s.values[i]).toFixed(digits)} ${unit}</b></div>`).join("");
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
    <div class="page-head"><div><h1>Net-meter &amp; KUSUM applications</h1>
      <div class="muted">The agent recommends a clearance from live hosting capacity (first-come-first-served). An engineer makes the final decision.</div></div></div>
    <div class="card"><h2>New application</h2>
      <form id="app-form" class="form-row">
        <label>DTR<select name="dtr_id" required>${dtrs.map((d) => `<option value="${d.id}">${esc(d.code)} (${num(d.rating_kva, 0)} kVA)</option>`).join("")}</select></label>
        <label>Applicant<input name="applicant_name" required minlength="2" placeholder="Name"></label>
        <label>Scheme<select name="scheme"><option value="rooftop">Rooftop</option><option value="kusum">PM-KUSUM</option></select></label>
        <label>Requested kW<input name="requested_kw" type="number" min="0.5" step="0.5" required></label>
        <button class="btn primary" type="submit">Submit</button>
      </form></div>
    <div class="card section"><div class="table-wrap"><table>
      <thead><tr><th>#</th><th>Applicant</th><th>DTR</th><th>Scheme</th><th class="num">Requested</th><th>Status</th><th>Agent recommendation</th><th></th></tr></thead>
      <tbody>${apps.map(appRow).join("") || `<tr><td colspan="8" class="empty">No applications</td></tr>`}</tbody>
    </table></div></div>`;

  $("#app-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    await withBusy(e.submitter, async () => {
      const created = await api("/api/applications", { method: "POST", body: { ...f, dtr_id: Number(f.dtr_id), requested_kw: Number(f.requested_kw) } });
      await api(`/api/applications/${created.id}/evaluate`, { method: "POST" });
      toast(`Application #${created.id} submitted and evaluated`);
      viewApplications();
    });
  });

  main().querySelectorAll("[data-act]").forEach((btn) => btn.addEventListener("click", () => withBusy(btn, async () => {
    const id = btn.dataset.id, act = btn.dataset.act;
    if (act === "evaluate") await api(`/api/applications/${id}/evaluate`, { method: "POST" });
    if (act === "approve") {
      const kw = prompt("Approve how many kW?", btn.dataset.kw);
      if (!kw) return;
      await api(`/api/applications/${id}/decision`, { method: "POST", body: { decision: "approve", approved_kw: Number(kw) } });
    }
    if (act === "reject") await api(`/api/applications/${id}/decision`, { method: "POST", body: { decision: "reject", note: prompt("Reason (optional)") || null } });
    if (act === "edit") {
      const kw = prompt("New requested kW", btn.dataset.kw);
      if (!kw) return;
      await api(`/api/applications/${id}`, { method: "PUT", body: { requested_kw: Number(kw) } });
    }
    if (act === "delete") {
      if (!confirm(`Delete application #${id}?`)) return;
      await api(`/api/applications/${id}`, { method: "DELETE" });
    }
    toast("Saved");
    viewApplications();
  })));
}

function appRow(a) {
  const open = a.status === "pending" || a.status === "evaluated";
  const actions = [
    open ? `<button class="btn small" data-act="evaluate" data-id="${a.id}">Evaluate</button>` : "",
    a.status === "evaluated" && a.recommended_kw > 0 ? `<button class="btn small" data-act="approve" data-id="${a.id}" data-kw="${a.recommended_kw}">Approve</button>` : "",
    a.status === "evaluated" ? `<button class="btn small" data-act="reject" data-id="${a.id}">Reject</button>` : "",
    open ? `<button class="btn small ghost" data-act="edit" data-id="${a.id}" data-kw="${a.requested_kw}">Edit</button>` : "",
    `<button class="btn small ghost danger" data-act="delete" data-id="${a.id}">Delete</button>`,
  ].join(" ");
  const rec = a.recommendation
    ? `${statusChip(a.recommendation, `${a.recommendation} · ${num(a.recommended_kw)} kW`)}<div class="small muted" style="max-width:380px">${esc(a.decision_reason)}</div>`
    : `<span class="muted small">Not evaluated</span>`;
  return `<tr><td>${a.id}</td><td>${esc(a.applicant_name)}</td><td><a href="#dtr/${a.dtr_id}">${esc(a.dtr_code)}</a></td><td>${esc(a.scheme)}</td>
    <td class="num">${num(a.requested_kw)} kW</td>
    <td>${statusChip(a.status)}${a.approved_kw ? `<div class="small muted">${num(a.approved_kw)} kW by ${esc(a.decided_by_name)}</div>` : ""}</td>
    <td>${rec}</td><td><div class="row" style="gap:4px;flex-wrap:nowrap">${actions}</div></td></tr>`;
}

// ------------------------------------------------------------------ alerts
async function viewAlerts() {
  const alerts = await api("/api/alerts?include_acknowledged=true");
  const open = alerts.filter((a) => !a.acknowledged);
  main().innerHTML = `
    <div class="page-head"><div><h1>Alerts</h1><div class="muted">Raised by the Grid-Watch agent from 48-hour forecasts and hosting capacity.</div></div>
      <button class="btn primary" id="rescan">Re-run scan</button></div>
    <div class="card">${alerts.length ? alerts.map((a) => `
      <div class="alert-row" style="${a.acknowledged ? "opacity:.55" : ""}">
        <div>${statusChip(a.severity)}</div>
        <div>${esc(a.message)}<span class="tag">${esc(a.alert_type.replace("_", " "))}</span>
          <div class="small muted"><a href="#dtr/${a.dtr_id}">${esc(a.dtr_code)}</a> · raised ${esc(a.created_at)} UTC</div></div>
        <div>${a.acknowledged ? `<span class="small muted">Acknowledged</span>` : `<button class="btn small" data-ack="${a.id}">Acknowledge</button>`}</div>
      </div>`).join("") : `<div class="empty">No alerts. Run the Grid-Watch agent from the dashboard.</div>`}</div>
    <p class="hint section">${open.length} open alert(s).</p>`;
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
const SUGGESTIONS = [
  "Which DTRs are saturated or close to saturation?",
  "Can DTR-S1-04 take an 8 kW rooftop system?",
  "Forecast tomorrow's net export for DTR-N1-03",
  "Any overvoltage or reverse-flow risk in the next 48 hours?",
  "How much more KUSUM solar can feeder S2 absorb?",
];

async function viewCopilot() {
  main().innerHTML = `
    <div class="page-head"><div><h1>D360 AI Copilot</h1>
      <div class="muted">${state.agent?.llm_enabled ? "D360 AI agent with live tool access to the grid analytics engine" : "D360 AI engine is offline - answering with the rule-based router"}</div></div>
      <button class="btn ghost small" id="clear-chat">Clear</button></div>
    <div class="chat card">
      <div class="messages" id="messages"></div>
      <div><div class="suggestions">${SUGGESTIONS.map((s) => `<button class="btn small" data-q="${esc(s)}">${esc(s)}</button>`).join("")}</div>
        <form id="chat-form"><input name="q" autocomplete="off" placeholder="Ask about hosting capacity, forecasts, risks or a net-meter request…" required maxlength="1000">
        <button class="btn primary" type="submit">Ask</button></form></div>
    </div>`;
  renderMessages();
  const ask = async (q, btn) => {
    state.chat.push({ role: "user", content: q });
    renderMessages(true);
    await withBusy(btn, async () => {
      const history = state.chat.slice(0, -1).map(({ role, content }) => ({ role, content })).slice(-6);
      const r = await api("/api/agent/chat", { method: "POST", body: { message: q, history } });
      state.chat.push({ role: "assistant", content: r.answer, meta: `${modeName(r.mode)} · tools: ${r.tools_used.join(", ") || "none"} · tokens ${r.usage.prompt_tokens}/${r.usage.completion_tokens}` });
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
  box.innerHTML = state.chat.map((m) => m.role === "user"
    ? `<div class="msg user">${esc(m.content)}</div>`
    : `<div class="msg bot">${md(m.content)}<div class="meta">${esc(m.meta || "")}</div></div>`).join("")
    + (thinking ? `<div class="msg bot muted">Agent is calling tools…</div>` : "")
    + (state.chat.length ? "" : `<div class="empty">Ask a question or pick a suggestion below.</div>`);
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
  main().innerHTML = `
    <div class="page-head"><div><h1>Network assets</h1><div class="muted">${admin ? "Admin: create, edit and delete feeders and DTRs." : "Read-only. Sign in as admin to edit."}</div></div></div>
    <div class="card"><h2>Feeders</h2>
      ${admin ? `<form id="feeder-form" class="form-row">
        <label>Substation<select name="substation_id">${subs.map((s) => `<option value="${s.id}">${esc(s.code)}</option>`).join("")}</select></label>
        <label>Code<input name="code" required placeholder="FDR-N3"></label><label>Name<input name="name" required></label>
        <label>Rating kVA<input name="rating_kva" type="number" min="1" required value="4000"></label>
        <button class="btn primary">Add feeder</button></form>` : ""}
      <div class="table-wrap section"><table><thead><tr><th>Code</th><th>Name</th><th>Substation</th><th class="num">kV</th><th class="num">kVA</th><th class="num">DTRs</th><th></th></tr></thead>
      <tbody>${feeders.map((f) => `<tr><td><b>${esc(f.code)}</b></td><td>${esc(f.name)}</td><td>${esc(f.substation_code)}</td><td class="num">${f.voltage_kv}</td><td class="num">${num(f.rating_kva, 0)}</td><td class="num">${f.dtr_count}</td>
        <td>${admin ? `<button class="btn small ghost danger" data-del-feeder="${f.id}">Delete</button>` : ""}</td></tr>`).join("")}</tbody></table></div></div>
    <div class="card section"><h2>Distribution transformers</h2>
      ${admin ? `<form id="dtr-form" class="form-row">
        <label>Feeder<select name="feeder_id">${feeders.map((f) => `<option value="${f.id}">${esc(f.code)}</option>`).join("")}</select></label>
        <label>Code<input name="code" required placeholder="DTR-N1-05"></label><label>Name<input name="name" required></label>
        <label>Rating kVA<input name="rating_kva" type="number" min="1" required value="100"></label>
        <label>Area<select name="area_type"><option>urban</option><option>rural</option><option>agri</option></select></label>
        <button class="btn primary">Add DTR</button></form>` : ""}
      <div class="table-wrap section"><table><thead><tr><th>Code</th><th>Name</th><th>Feeder</th><th>Area</th><th class="num">kVA</th><th class="num">Consumers</th><th class="num">Solar kW</th><th></th></tr></thead>
      <tbody>${dtrs.map((d) => `<tr><td><a href="#dtr/${d.id}"><b>${esc(d.code)}</b></a></td><td>${esc(d.name)}</td><td>${esc(d.feeder_code)}</td><td>${esc(d.area_type)}</td>
        <td class="num">${num(d.rating_kva, 0)}</td><td class="num">${d.consumer_count}</td><td class="num">${num(d.pv_kw)}</td>
        <td>${admin ? `<div class="row" style="gap:4px;flex-wrap:nowrap"><button class="btn small ghost" data-edit-dtr="${d.id}" data-kva="${d.rating_kva}">Upgrade kVA</button><button class="btn small ghost danger" data-del-dtr="${d.id}">Delete</button></div>` : ""}</td></tr>`).join("")}</tbody></table></div></div>`;
  if (!admin) return;

  const submit = (formId, path, numeric) => $(formId).addEventListener("submit", async (e) => {
    e.preventDefault();
    const body = Object.fromEntries(new FormData(e.target));
    numeric.forEach((k) => (body[k] = Number(body[k])));
    await withBusy(e.submitter, async () => { await api(path, { method: "POST", body }); toast("Created"); viewAssets(); });
  });
  submit("#feeder-form", "/api/feeders", ["substation_id", "rating_kva"]);
  submit("#dtr-form", "/api/dtrs", ["feeder_id", "rating_kva"]);
  main().querySelectorAll("[data-del-feeder],[data-del-dtr]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const isFeeder = !!b.dataset.delFeeder;
    if (!confirm(`Delete this ${isFeeder ? "feeder and all its DTRs" : "DTR and its data"}?`)) return;
    await api(isFeeder ? `/api/feeders/${b.dataset.delFeeder}` : `/api/dtrs/${b.dataset.delDtr}`, { method: "DELETE" });
    toast("Deleted"); viewAssets();
  })));
  main().querySelectorAll("[data-edit-dtr]").forEach((b) => b.addEventListener("click", () => withBusy(b, async () => {
    const kva = prompt("New DTR rating (kVA) - e.g. after augmentation", b.dataset.kva);
    if (!kva) return;
    await api(`/api/dtrs/${b.dataset.editDtr}`, { method: "PUT", body: { rating_kva: Number(kva) } });
    toast("DTR updated - hosting capacity recalculated"); viewAssets();
  })));
}

// ------------------------------------------------------------------ agent log
async function viewRuns() {
  const { runs, totals } = await api("/api/agent/runs");
  main().innerHTML = `
    <div class="page-head"><div><h1>Agent log</h1><div class="muted">Every agent run with its tools and token usage.</div></div>
      <div class="muted">Total tokens: ${num(totals.prompt_tokens, 0)} in / ${num(totals.completion_tokens, 0)} out</div></div>
    <div class="card"><div class="table-wrap"><table>
      <thead><tr><th>When (UTC)</th><th>User</th><th>Kind</th><th>Engine</th><th>Question</th><th>Tools</th><th class="num">Tokens in/out</th></tr></thead>
      <tbody>${runs.map((r) => `<tr><td class="small">${esc(r.created_at)}</td><td>${esc(r.user_name || "")}</td><td>${esc(r.kind)}</td><td>${esc(modeName(r.mode))}</td>
        <td>${esc(r.question)}</td><td class="small">${esc(r.tools_used)}</td><td class="num">${r.prompt_tokens}/${r.completion_tokens}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">No runs yet</td></tr>`}</tbody>
    </table></div></div>`;
}

// ------------------------------------------------------------------ boot
(async function boot() {
  state.token = load("sc_token");
  if (!state.token) return showAuth();
  try {
    state.user = await api("/api/auth/me");
    startApp();
  } catch (_) {
    logout();
  }
})();
