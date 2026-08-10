const view = document.body.dataset.signalView;
const state = {
  items: [],
  visible: [],
  search: "",
  band: "",
  sort: view === "snipes" ? "score" : "score",
};

const elements = {
  grid: document.querySelector("#signal-grid"),
  count: document.querySelector("#result-count"),
  search: document.querySelector("#search-input"),
  band: document.querySelector("#band-select"),
  sort: document.querySelector("#sort-select"),
  empty: document.querySelector("#empty-state"),
  dialog: document.querySelector("#detail-dialog"),
  dialogContent: document.querySelector("#dialog-content"),
};

const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const gilFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("es-CL", { style: "percent", maximumFractionDigits: 0 });
const collator = new Intl.Collator("es", { sensitivity: "base", numeric: true });

async function loadSignals() {
  try {
    const [market, history, evidence] = await Promise.all([
      fetchDocument("market-items"),
      fetchDocument("market-history"),
      fetch("./data/launch-signals.json").then(requireJson),
    ]);
    const historyByKey = new Map(history.series.map((series) => [series.key, series]));
    state.items = view === "snipes"
      ? buildSnipes(market.items, historyByKey)
      : buildProjections(market.items, evidence);
    hydrateMeta(market, history);
    applyFilters();
  } catch (error) {
    elements.count.textContent = "No pudimos preparar las señales";
    elements.empty.hidden = false;
    elements.empty.querySelector("p").textContent = error.message;
  }
}

async function fetchDocument(kind) {
  const apiBaseUrl = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
  const endpoints = apiBaseUrl
    ? [`${apiBaseUrl}/v1/${kind}`, `./data/${kind}.json`]
    : [`./data/${kind}.json`];
  let lastError;
  for (const endpoint of endpoints) {
    try { return await fetch(endpoint).then(requireJson); }
    catch (error) { lastError = error; }
  }
  throw lastError || new Error(`No se pudo cargar ${kind}`);
}

async function requireJson(response) {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function buildProjections(items, evidence) {
  const patterns = evidence.patterns || [];
  return items
    .filter((item) => item.status === "FRESH" && finitePositive(item.averageSalePrice) && finitePositive(item.dailySaleVelocity))
    .flatMap((item) => {
      const match = bestPattern(item, patterns);
      // Historical winners define roles; they are never candidates unless a
      // curated rule identifies the item as a valid present-day equivalent.
      if (!match) return [];
      const trend = item.trend || {};
      const velocityChange = finite(trend.velocityChangeRatio, 0);
      const priceChange = finite(trend.priceChangeRatio, 0);
      const volatility = Number.isFinite(trend.priceVolatility) ? trend.priceVolatility : null;
      const historyPoints = finite(trend.historyPoints, 0);
      const recentRecipeUses = finite(item.recipeDemand?.recentRecipeUses, 0);
      const historyScore = finite(match.historicalWeight, 0);
      const currentFitScore = finite(match.currentFitWeight, 0);
      const recipeCentralityScore = clamp(Math.log2(recentRecipeUses + 1) / 6, 0, 1) * 8;
      const momentumScore = clamp(velocityChange / 0.60, 0, 1) * 10;
      const priceScore = clamp(priceChange / 0.30, 0, 1) * 5;
      const liquidityScore = clamp(Math.log10(item.dailySaleVelocity + 1) / 4, 0, 1) * 15;
      const stabilityScore = trend.stability === "HIGH" ? 8 : trend.stability === "MEDIUM" ? 5 : 2;
      const sampleScore = clamp(historyPoints / 8, 0, 1) * 5;
      const freshnessScore = 3;
      const coolingPenalty = velocityChange < -0.10 ? 10 : 0;
      const volatilityPenalty = volatility === null ? 4 : volatility > 0.45 ? 10 : volatility > 0.25 ? 4 : 0;
      const score = Math.round(clamp(
        historyScore + currentFitScore + recipeCentralityScore + momentumScore + priceScore
          + liquidityScore + stabilityScore + sampleScore + freshnessScore
          - coolingPenalty - volatilityPenalty,
        0,
        100,
      ));
      const reasons = [match.currentRationale, `Patrón histórico: ${match.evidence}`];
      if (recentRecipeUses > 0) reasons.push(`Aparece como ingrediente en ${integerFormat.format(recentRecipeUses)} recetas de los dos parches más recientes.`);
      if (velocityChange >= 0.20) reasons.push(`La velocidad subió ${percentFormat.format(velocityChange)} en la ventana disponible.`);
      if (priceChange >= 0.10) reasons.push(`El precio medio avanzó ${percentFormat.format(priceChange)}.`);
      if (item.dailySaleVelocity >= 10) reasons.push(`${decimalFormat.format(item.dailySaleVelocity)} ventas/día aportan liquidez.`);
      const risk = match.confidence === "LOW" || (volatility !== null && volatility > 0.35)
        ? "ALTO"
        : volatility === null || volatility > 0.15 || match.confidence === "MEDIUM" ? "MEDIO" : "BAJO";
      return [{
        ...item,
        signalKind: "projection",
        score,
        band: score >= 72 ? "ALCISTA" : score >= 60 ? "VIGILAR" : "TEMPRANA",
        risk,
        reasons,
        pattern: match,
        velocityChange,
        priceChange,
      }];
    })
    .filter((item) => item.score >= 45)
    .sort((a, b) => b.score - a.score || b.dailySaleVelocity - a.dailySaleVelocity)
    .slice(0, 60);
}

function buildSnipes(items, historyByKey) {
  return items.flatMap((item) => {
    if (item.status !== "FRESH" || !finitePositive(item.minListingPrice) || !finitePositive(item.dailySaleVelocity)) return [];
    const series = historyByKey.get(`${item.itemId}:${item.quality}`);
    const points = series?.points || [];
    if (points.length < 3) return [];
    const previous = points.slice(0, -1);
    const listingBaseline = median(previous.map((point) => point.minListingPrice).filter(finitePositive));
    const saleBaseline = median(points.map((point) => point.averageSalePrice).filter(finitePositive));
    const references = [listingBaseline, saleBaseline].filter(finitePositive);
    if (!references.length) return [];
    const referencePrice = Math.min(...references);
    const discount = 1 - item.minListingPrice / referencePrice;
    const volatility = finite(series.trend?.priceVolatility, 1);
    const profit = referencePrice * 0.95 - item.minListingPrice;
    const roi = profit / item.minListingPrice;
    if (discount < (volatility > 0.45 ? 0.50 : 0.25) || profit < Math.max(100, item.minListingPrice * 0.20)) return [];
    const discountScore = clamp(discount / 0.65, 0, 1) * 55;
    const liquidityScore = clamp(Math.log10(item.dailySaleVelocity + 1) / 3, 0, 1) * 20;
    const historyScore = clamp(points.length / 10, 0, 1) * 10;
    const stabilityScore = volatility <= 0.10 ? 10 : volatility <= 0.25 ? 7 : 2;
    const roiScore = clamp(roi / 1.0, 0, 1) * 5;
    const score = Math.round(clamp(discountScore + liquidityScore + historyScore + stabilityScore + roiScore, 0, 100));
    return [{
      ...item,
      signalKind: "snipe",
      score,
      band: score >= 75 ? "URGENTE" : score >= 60 ? "FUERTE" : "REVISAR",
      risk: volatility <= 0.10 ? "BAJO" : volatility <= 0.25 ? "MEDIO" : "ALTO",
      referencePrice,
      listingBaseline,
      saleBaseline,
      discount,
      potentialUnitProfit: profit,
      potentialRoi: roi,
      historyPoints: points.length,
      stockVerified: false,
      reasons: [
        `El listing mínimo está ${percentFormat.format(discount)} bajo la referencia conservadora.`,
        `Referencia: menor entre mediana histórica de listings y ventas (${gil(referencePrice)}).`,
        `Margen teórico después de fee: ${gil(profit)} por unidad.`,
      ],
    }];
  }).sort((a, b) => b.score - a.score || b.discount - a.discount).slice(0, 150);
}

function bestPattern(item, patterns) {
  let best = null;
  patterns.forEach((pattern) => {
    if (!pattern.currentItemIds?.includes(item.itemId)) return;
    const weight = finite(pattern.historicalWeight, 0) + finite(pattern.currentFitWeight, 0);
    if (!best || weight > best.weight) best = { ...pattern, weight };
  });
  return best;
}

function hydrateMeta(market, history) {
  document.querySelector("#scope-label").textContent = market.meta.scope;
  document.querySelector("#updated-label").textContent = `Mercado ${relativeTime(market.meta.marketCollectedAt)}`;
  document.querySelector("#metric-signals").textContent = integerFormat.format(state.items.length);
  document.querySelector("#metric-strong").textContent = integerFormat.format(state.items.filter((item) => item.score >= (view === "snipes" ? 75 : 72)).length);
  document.querySelector("#metric-history").textContent = integerFormat.format(history.summary.snapshots);
  document.querySelector("#metric-coverage").textContent = view === "snipes"
    ? integerFormat.format(state.items.filter((item) => item.stockVerified).length)
    : integerFormat.format(state.items.filter((item) => item.pattern).length);
}

function applyFilters() {
  const query = normalize(state.search);
  state.visible = state.items.filter((item) => {
    if (state.band && item.band !== state.band) return false;
    return !query || normalize([item.name, item.itemId, categoryName(item), item.band, item.pattern?.label, item.pattern?.confidence].join(" ")).includes(query);
  });
  state.visible.sort(sorter(state.sort));
  render();
}

function sorter(mode) {
  if (mode === "discount") return (a, b) => finite(b.discount, -1) - finite(a.discount, -1) || b.score - a.score;
  if (mode === "velocity") return (a, b) => b.dailySaleVelocity - a.dailySaleVelocity || b.score - a.score;
  if (mode === "price") return (a, b) => b.averageSalePrice - a.averageSalePrice || b.score - a.score;
  if (mode === "name") return (a, b) => collator.compare(a.name, b.name);
  return (a, b) => b.score - a.score || collator.compare(a.name, b.name);
}

function render() {
  elements.grid.replaceChildren();
  const fragment = document.createDocumentFragment();
  state.visible.slice(0, 60).forEach((item) => fragment.append(createCard(item)));
  elements.grid.append(fragment);
  elements.count.textContent = view === "snipes"
    ? `${integerFormat.format(state.visible.length)} señales · mostrando hasta 60`
    : `${integerFormat.format(state.visible.length)} equivalentes actuales`;
  elements.empty.hidden = state.visible.length !== 0;
}

function createCard(item) {
  const card = document.createElement("article");
  card.className = `signal-card ${item.band.toLowerCase()}`;
  card.tabIndex = 0;
  const metric = view === "snipes"
    ? `<small>DESCUENTO</small><strong>${percentFormat.format(item.discount)}</strong>`
    : `<small>VENTAS / DÍA</small><strong>${decimalFormat.format(item.dailySaleVelocity)}</strong>`;
  card.innerHTML = `
    <div class="signal-card-top"><span class="signal-band">${escapeHtml(item.band)}</span><span class="signal-risk">RIESGO ${escapeHtml(item.risk)}</span></div>
    <div class="signal-identity"><span class="item-icon ${view === "snipes" ? "gold" : ""}" aria-hidden="true">${signalIcon()}</span><div><h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3><p>${escapeHtml(categoryName(item) || `Item ${item.itemId}`)}</p></div></div>
    <div class="signal-score"><div><small>PUNTAJE</small><strong>${item.score}<span>/100</span></strong></div><progress max="100" value="${item.score}">${item.score}</progress></div>
    <div class="signal-metrics"><div>${metric}</div><div><small>PRECIO ACTUAL</small><strong>${gil(item.minListingPrice ?? item.averageSalePrice)}</strong></div>${view === "snipes" ? `<div><small>MARGEN TEÓRICO</small><strong>+${gil(item.potentialUnitProfit)}</strong></div>` : `<div><small>CAMBIO DEMANDA</small><strong>${signedPercent(item.velocityChange)}</strong></div>`}</div>
    <p class="signal-reason">${escapeHtml(item.reasons[0])}</p>
    <span class="signal-action">Ver razonamiento →</span>`;
  card.addEventListener("click", () => showDetail(item));
  card.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showDetail(item); }
  });
  return card;
}

function showDetail(item) {
  const title = view === "snipes" ? "CANDIDATO A SNIPE" : "PROYECCIÓN EVERCOLD 8.0";
  elements.dialogContent.innerHTML = `<div class="detail-body signal-detail">
    <p class="eyebrow">${title} · ITEM ${item.itemId}</p>
    <h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3>
    <p>${escapeHtml(categoryName(item) || "Sin categoría")} · Riesgo ${escapeHtml(item.risk.toLowerCase())}</p>
    <div class="score-panel"><div class="score-heading"><div><small>SEÑAL</small><strong>${escapeHtml(item.band)}</strong></div><b>${item.score}<span>/100</span></b></div><progress class="signal-detail-progress" max="100" value="${item.score}">${item.score}</progress></div>
    <div class="detail-stats">
      <div><small>Listing mínimo</small><strong>${gil(item.minListingPrice)}</strong></div>
      <div><small>Ventas / día Cactuar</small><strong>${velocity(item.dailySaleVelocity)}</strong></div>
      ${view === "snipes" ? `<div><small>Referencia conservadora</small><strong>${gil(item.referencePrice)}</strong></div><div><small>ROI teórico</small><strong>${percentFormat.format(item.potentialRoi)}</strong></div>` : `<div><small>Cambio demanda</small><strong>${signedPercent(item.velocityChange)}</strong></div><div><small>Cambio precio</small><strong>${signedPercent(item.priceChange)}</strong></div>`}
    </div>
    <section class="reason-panel"><small>POR QUÉ APARECE</small><ul>${item.reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></section>
    ${item.pattern ? `<section class="reason-panel"><small>MATCH HISTÓRICO → ACTUAL</small><p><strong>${escapeHtml(item.pattern.label)}</strong> · confianza ${escapeHtml(item.pattern.confidence.toLowerCase())}</p><p>Ejemplos pasados: ${escapeHtml((item.pattern.historicalExamples || []).join(", "))}.</p></section><a class="source-link" href="${escapeHtml(item.pattern.sourceUrl)}" target="_blank" rel="noopener">Ver evidencia histórica ↗</a>` : ""}
    <p class="detail-warning"><strong>${view === "snipes" ? "Stock sin verificar:" : "No es una predicción garantizada:"}</strong> ${view === "snipes" ? "confirma en el juego el precio, cantidad, HQ y retainer antes de comprar." : "el puntaje ordena señales observables y puede cambiar en el siguiente snapshot."}</p>
  </div>`;
  elements.dialog.showModal();
}

function signalIcon() {
  return view === "snipes"
    ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>'
    : '<svg viewBox="0 0 24 24"><path d="m4 17 5-5 4 3 7-8"/><path d="M15 7h5v5"/></svg>';
}

function categoryName(item) { return item.searchCategoryName || item.uiCategoryName || ""; }
function finite(value, fallback) { return Number.isFinite(value) ? value : fallback; }
function finitePositive(value) { return Number.isFinite(value) && value > 0; }
function clamp(value, minimum, maximum) { return Math.max(minimum, Math.min(maximum, value)); }
function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}
function normalize(value) { return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim(); }
function gil(value) { return value === null || value === undefined ? "Sin dato" : `${gilFormat.format(value)} gil`; }
function velocity(value) { return value === null || value === undefined ? "Sin datos Cactuar" : `${decimalFormat.format(value)} /d`; }
function signedPercent(value) { return !Number.isFinite(value) ? "Sin comparación" : `${value >= 0 ? "+" : ""}${percentFormat.format(value)}`; }
function relativeTime(value) {
  if (!value) return "sin fecha";
  const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (minutes < 60) return `hace ${Math.max(1, minutes)} min`;
  const hours = Math.round(minutes / 60);
  return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`;
}
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }

elements.search.addEventListener("input", (event) => { state.search = event.target.value; applyFilters(); });
elements.band.addEventListener("change", (event) => { state.band = event.target.value; applyFilters(); });
elements.sort.addEventListener("change", (event) => { state.sort = event.target.value; applyFilters(); });
document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => { if (event.target === elements.dialog) elements.dialog.close(); });
document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); elements.search.focus(); } });

loadSignals();
