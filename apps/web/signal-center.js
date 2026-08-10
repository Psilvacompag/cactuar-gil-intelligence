const state = { signals: [], visible: [], search: "", module: "", watchedOnly: false, sort: "score" };
const elements = {
  grid: document.querySelector("#center-grid"), count: document.querySelector("#result-count"),
  search: document.querySelector("#search-input"), module: document.querySelector("#module-select"),
  watched: document.querySelector("#watched-toggle"), sort: document.querySelector("#sort-select"),
  empty: document.querySelector("#empty-state"), moduleSummary: document.querySelector("#module-summary"),
  enableAlerts: document.querySelector("#enable-alerts"),
  todayGrid: document.querySelector("#today-grid"), todayStatus: document.querySelector("#today-status"),
  freshness: document.querySelector("#today-freshness"), solid: document.querySelector("#metric-solid"),
};
const numberFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const compactFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("es-CL", { style: "percent", maximumFractionDigits: 1 });
const collator = new Intl.Collator("es", { sensitivity: "base", numeric: true });
const MODULES = {
  conversion: { label: "Conversiones", icon: "⇄" }, market: { label: "Mercado", icon: "◇" },
  opportunity: { label: "Oportunidades", icon: "↗" }, projection: { label: "Proyecciones", icon: "⌁" },
  snipe: { label: "Snipeos", icon: "◎" },
};

async function loadLedger() {
  try {
    const [payload, opportunityPayload] = await Promise.all([fetchDocument("signals"), fetchDocument("opportunities")]);
    const routes = new Map((opportunityPayload.opportunities || []).map((item) => [`${item.itemId}:${item.quality}:${item.sourceWorldId}`, item]));
    state.signals = (payload.signals || []).map((signal) => {
      const route = routes.get(`${signal.itemId}:${signal.quality}:${signal.context?.sourceWorldId}`);
      return route ? { ...signal, context: { ...signal.context, velocity: route.dailySaleVelocity,
        historySamples: route.historySamples, dataAgeHours: route.dataAgeHours,
        buyPrice: route.averagePurchasePrice ?? route.sourcePrice, sellPrice: route.conservativeSellPrice,
        quantity: route.recommendedQuantity, profit: route.estimatedTripProfit } } : signal;
    });
    document.querySelector("#scope-label").textContent = payload.meta.scope || "Cactuar";
    document.querySelector("#updated-label").textContent = payload.meta.marketCollectedAt ? `Mercado ${relativeTime(payload.meta.marketCollectedAt)}` : "Esperando primer ledger";
    document.querySelector("#metric-total").textContent = integerFormat.format(payload.summary.currentSignals || 0);
    elements.solid.textContent = integerFormat.format(state.signals.filter((signal) => signalQuality(signal).key === "solid").length);
    document.querySelector("#metric-observations").textContent = integerFormat.format(payload.summary.observations || 0);
    document.querySelector("#metric-mature").textContent = integerFormat.format(payload.summary.mature7d || 0);
    elements.freshness.textContent = payload.meta.marketCollectedAt ? `Mercado ${relativeTime(payload.meta.marketCollectedAt)}` : "Esperando snapshot";
    renderModuleSummary(payload.summary.modules || {});
    renderToday();
    applyFilters();
    emitAlerts();
  } catch (error) {
    elements.count.textContent = "No pudimos cargar el ledger";
    elements.empty.hidden = false;
    elements.empty.querySelector("p").textContent = error.message;
  }
}

async function fetchDocument(kind) {
  return GilAuth.data(`/v1/${kind}`);
}

function applyFilters() {
  const query = normalize(state.search);
  state.visible = state.signals.filter((signal) => {
    if (state.module && signal.module !== state.module) return false;
    if (state.watchedOnly && !GilWatchlist.has(signal.key)) return false;
    return !query || normalize([signal.title, signal.subtitle, signal.reason, signal.state, moduleLabel(signal.module), JSON.stringify(signal.context || {})].join(" ")).includes(query);
  });
  state.visible.sort(sorter(state.sort));
  render();
}

function sorter(mode) {
  if (mode === "change") return (a, b) => finite(b.outcome?.change, -Infinity) - finite(a.outcome?.change, -Infinity) || b.score - a.score;
  if (mode === "drawdown") return (a, b) => finite(b.outcome?.maximumDrawdown, -Infinity) - finite(a.outcome?.maximumDrawdown, -Infinity) || b.score - a.score;
  if (mode === "name") return (a, b) => collator.compare(a.title, b.title);
  return (a, b) => b.score - a.score || b.metricValue - a.metricValue;
}

function render() {
  elements.grid.replaceChildren();
  const fragment = document.createDocumentFragment();
  state.visible.slice(0, 120).forEach((signal) => fragment.append(createCard(signal)));
  elements.grid.append(fragment);
  GilIntelligence.hydrateSparklines(elements.grid);
  elements.count.textContent = `${integerFormat.format(state.visible.length)} señales · mostrando hasta 120`;
  elements.empty.hidden = state.visible.length !== 0;
}

function createCard(signal) {
  const card = document.createElement("article");
  card.className = `center-card module-${signal.module}`;
  const outcome = signal.outcome || {};
  card.innerHTML = `<div class="center-card-heading">${GilItemIcons.markup(signal.iconId, { fallback: "signal", tone: signal.module === "snipe" ? "gold" : "" })}<div><small>${escapeHtml(moduleLabel(signal.module))} · ${escapeHtml(signal.state)}</small><h3>${escapeHtml(signal.title)}</h3><p>${escapeHtml(signal.subtitle || "")}</p>${GilIntelligence.qualityMarkup(signalQualityInput(signal))}</div><button class="watch-button ${GilWatchlist.has(signal.key) ? "active" : ""}" type="button" aria-label="Vigilar">★</button></div>
    <div class="center-score"><strong>${signal.score}<span>/100</span></strong><progress max="100" value="${signal.score}">${signal.score}</progress></div>
    <div class="center-metrics"><div><small>${escapeHtml(metricLabel(signal.metricName))}</small><strong>${metricValue(signal)}</strong></div><div><small>Desde señal</small><strong>${ratio(outcome.change)}</strong></div><div><small>Drawdown</small><strong>${ratio(outcome.maximumDrawdown)}</strong></div></div>
    <p class="center-reason">${escapeHtml(signal.reason)}</p>
    <div class="horizon-strip"><span>7d <b>${ratio(outcome.return7d)}</b></span><span>30d <b>${ratio(outcome.return30d)}</b></span><span>90d <b>${ratio(outcome.return90d)}</b></span><small>${integerFormat.format(outcome.observations || 0)} obs.</small></div>
    <div class="center-card-actions"><button class="center-intel-button" type="button">Ficha completa</button><a href="${escapeHtml(signal.url)}">Abrir módulo →</a></div><div class="tiny-sparkline" data-spark-key="${signal.itemId}:${signal.quality}"><span class="spark-empty">Cargando…</span></div>`;
  card.querySelector(".watch-button").addEventListener("click", () => {
    GilWatchlist.toggle(signal.key, { module: signal.module, itemId: signal.itemId, quality: signal.quality, name: signal.title, iconId: signal.iconId, targetValue: signal.metricValue });
    applyFilters();
  });
  card.querySelector(".center-intel-button").addEventListener("click", () => openSignal(signal));
  return card;
}

function renderToday() {
  const definitions = [
    { key: "conversion", label: "Conversión líquida", filter: (signal) => signal.module === "conversion" && finite(signal.context?.velocity, 0) > 0 },
    { key: "gathering", label: "Recolectar", filter: (signal) => signal.module === "market" && signal.context?.gatherable },
    { key: "crafting", label: "Craftear", filter: (signal) => signal.module === "market" && signal.context?.craftable && signal.state === "PROFITABLE" },
    { key: "opportunity", label: "Compra regional", filter: (signal) => signal.module === "opportunity" },
    { key: "snipe", label: "Snipeo urgente", filter: (signal) => signal.module === "snipe" },
    { key: "projection", label: "Preparar 8.0", filter: (signal) => signal.module === "projection" },
  ];
  const picks = definitions.map((definition) => ({ definition, signal: state.signals.filter(definition.filter).sort(todaySorter)[0] })).filter((pick) => pick.signal);
  elements.todayGrid.innerHTML = picks.map(({ definition, signal }) => `<article class="today-card module-${signal.module}">
    <div class="today-card-top"><span>${escapeHtml(definition.label)}</span>${GilIntelligence.qualityMarkup(signalQualityInput(signal))}</div>
    <div class="today-card-title">${GilItemIcons.markup(signal.iconId, { fallback: "signal", tone: signal.module === "snipe" ? "gold" : "" })}<div><h3>${escapeHtml(signal.title)}</h3><p>${escapeHtml(signal.subtitle || moduleLabel(signal.module))}</p></div></div>
    <div class="today-card-score"><strong>${signal.score}<small>/100</small></strong><div><span>${escapeHtml(metricLabel(signal.metricName))}</span><b>${metricValue(signal)}</b></div><div class="tiny-sparkline" data-spark-key="${signal.itemId}:${signal.quality}"><span class="spark-empty">Cargando…</span></div></div>
    <p class="today-card-plan">${escapeHtml(todayPlan(signal))}</p>
    <div class="today-card-actions"><button type="button" data-key="${escapeHtml(signal.key)}">Ver ficha</button><a href="${escapeHtml(signal.url)}">Abrir módulo →</a></div>
  </article>`).join("");
  elements.todayStatus.textContent = `${picks.length} decisiones priorizadas · actualizadas automáticamente`;
  elements.todayGrid.querySelectorAll("button[data-key]").forEach((button) => button.addEventListener("click", () => {
    const signal = state.signals.find((candidate) => candidate.key === button.dataset.key); if (signal) openSignal(signal);
  }));
  GilIntelligence.hydrateSparklines(elements.todayGrid);
}

function todaySorter(a, b) {
  const qualityDifference = qualityRank(signalQuality(a)) - qualityRank(signalQuality(b));
  return qualityDifference || b.score - a.score || finite(b.metricValue, 0) - finite(a.metricValue, 0);
}

function qualityRank(result) { return ({ solid: 0, limited: 1, volatile: 2, "no-velocity": 3, stale: 4 })[result.key] ?? 5; }
function signalQualityInput(signal) { return { ...signal.context, outcome: signal.outcome, status: signal.state === "STALE" ? "STALE" : "FRESH" }; }
function signalQuality(signal) { return GilIntelligence.quality(signalQualityInput(signal)); }

function todayPlan(signal) {
  const context = signal.context || {};
  if (["opportunity", "snipe"].includes(signal.module)) return `Comprar hasta ${integerFormat.format(context.quantity || 1)} u. en ${context.sourceWorldName || "el World indicado"} por ≤ ${gil(context.buyPrice)} y salir cerca de ${gil(context.sellPrice)}.`;
  if (signal.module === "conversion") return `Convertir en lotes pequeños; retorno actual ${metricValue(signal)} y velocidad ${velocity(context.velocity)}.`;
  if (signal.module === "projection") return `Acumular por tramos sin perseguir el precio; revisar la tesis en cada nuevo snapshot antes de 8.0.`;
  if (context.craftable) return `Fabricar un lote corto, venderlo completo y reponer sólo si el margen y la velocidad se mantienen.`;
  return `Recolectar cerca de un cuarto de la demanda diaria y dividir listings para no presionar el precio.`;
}

function openSignal(signal) {
  GilIntelligence.openItem({ itemId: signal.itemId, quality: signal.quality, name: signal.title,
    iconId: signal.iconId, modules: new Set([signal.module]), context: signal.context,
    outcome: signal.outcome, aliases: new Set([signal.subtitle]) });
}

function renderModuleSummary(counts) {
  elements.moduleSummary.innerHTML = Object.entries(MODULES).map(([key, module]) => `<button type="button" data-module="${key}"><span>${module.icon}</span><strong>${integerFormat.format(counts[key] || 0)}</strong><small>${module.label}</small></button>`).join("");
  elements.moduleSummary.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
    state.module = state.module === button.dataset.module ? "" : button.dataset.module;
    elements.module.value = state.module;
    applyFilters();
  }));
}

function emitAlerts() {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const notifiedKey = "gil-intelligence.unified-notices.v1";
  let notified = {};
  try { notified = JSON.parse(localStorage.getItem(notifiedKey) || "{}"); } catch { notified = {}; }
  state.signals.filter((signal) => GilWatchlist.has(signal.key) && signal.score >= 75).forEach((signal) => {
    const id = `${signal.key}:${signal.state}:${Math.round(signal.metricValue)}`;
    if (notified[id]) return;
    new Notification(`${moduleLabel(signal.module)}: ${signal.title}`, { body: `${signal.state} · ${metricLabel(signal.metricName)} ${metricValue(signal)}` });
    notified[id] = new Date().toISOString();
  });
  localStorage.setItem(notifiedKey, JSON.stringify(notified));
}

function moduleLabel(value) { return MODULES[value]?.label || value; }
function metricLabel(value) { return ({ netGilPerCurrency: "Gil / moneda", estimatedDailyProfit: "Ganancia / día", averageSalePrice: "Precio medio", estimatedTripProfit: "Ganancia de ruta" })[value] || value; }
function metricValue(signal) { return signal.metricName === "netGilPerCurrency" ? `${numberFormat.format(signal.metricValue)} gil` : `${compactFormat.format(signal.metricValue)} gil`; }
function gil(value) { return value !== null && value !== undefined && Number.isFinite(Number(value)) ? `${compactFormat.format(Number(value))} gil` : "sin datos"; }
function velocity(value) { return value !== null && value !== undefined && Number.isFinite(Number(value)) ? `${numberFormat.format(Number(value))} / día` : "sin velocidad Cactuar"; }
function ratio(value) { return Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${percentFormat.format(value)}` : "Acumulando"; }
function finite(value, fallback) { return Number.isFinite(value) ? value : fallback; }
function normalize(value) { return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase(); }
function relativeTime(value) { const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000)); if (minutes < 60) return `hace ${Math.max(1, minutes)} min`; const hours = Math.round(minutes / 60); return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`; }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }

elements.search.addEventListener("input", (event) => { state.search = event.target.value; applyFilters(); });
elements.module.addEventListener("change", (event) => { state.module = event.target.value; applyFilters(); });
elements.watched.addEventListener("change", (event) => { state.watchedOnly = event.target.checked; applyFilters(); });
elements.sort.addEventListener("change", (event) => { state.sort = event.target.value; applyFilters(); });
elements.enableAlerts.addEventListener("click", async () => { if (!("Notification" in window)) { elements.enableAlerts.textContent = "No compatible"; return; } const permission = await Notification.requestPermission(); elements.enableAlerts.textContent = permission === "granted" ? "Alertas activadas" : "Alertas bloqueadas"; emitAlerts(); });
document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); elements.search.focus(); } });
GilWatchlist.subscribe(() => applyFilters());
loadLedger();
