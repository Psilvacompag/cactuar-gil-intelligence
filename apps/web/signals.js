const view = document.body.dataset.signalView;
const STORAGE = {
  budget: "gil-intelligence.projection-budget",
  watched: "gil-intelligence.watched-signals",
  ledger: "gil-intelligence.signal-ledger",
  notices: "gil-intelligence.notified-signals",
};
const state = {
  items: [], visible: [], search: "", band: "", phase: "", sort: "score",
  budget: positiveNumber(localStorage.getItem(STORAGE.budget)) || 5000000,
  watched: readStoredObject(STORAGE.watched),
};
const elements = {
  grid: document.querySelector("#signal-grid"), count: document.querySelector("#result-count"),
  search: document.querySelector("#search-input"), band: document.querySelector("#band-select"),
  phase: document.querySelector("#phase-select"), sort: document.querySelector("#sort-select"),
  budget: document.querySelector("#budget-input"), empty: document.querySelector("#empty-state"),
  dialog: document.querySelector("#detail-dialog"), dialogContent: document.querySelector("#dialog-content"),
  alerts: document.querySelector("#alert-list"), enableAlerts: document.querySelector("#enable-alerts"),
};
const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const gilFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("es-CL", { style: "percent", maximumFractionDigits: 0 });
const collator = new Intl.Collator("es", { sensitivity: "base", numeric: true });

async function loadSignals() {
  try {
    const [market, history, evidence] = await Promise.all([
      fetchDocument("market-items"), fetchDocument("market-history"),
      fetch("./data/launch-signals.json").then(requireJson),
    ]);
    const historyByKey = new Map(history.series.map((series) => [series.key, series]));
    state.items = view === "snipes"
      ? buildSnipes(market.items, historyByKey)
      : buildProjections(market.items, evidence, historyByKey);
    updateSignalLedger(state.items, market.meta.marketCollectedAt);
    hydrateMeta(market, history);
    applyFilters();
    renderAlerts();
    emitBrowserAlerts();
  } catch (error) {
    elements.count.textContent = "No pudimos preparar las señales";
    elements.empty.hidden = false;
    elements.empty.querySelector("p").textContent = error.message;
  }
}

async function fetchDocument(kind) {
  const apiBaseUrl = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
  const endpoints = apiBaseUrl ? [`${apiBaseUrl}/v1/${kind}`, `./data/${kind}.json`] : [`./data/${kind}.json`];
  let lastError;
  for (const endpoint of endpoints) {
    try { return await fetch(endpoint).then(requireJson); } catch (error) { lastError = error; }
  }
  throw lastError || new Error(`No se pudo cargar ${kind}`);
}

async function requireJson(response) {
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function buildProjections(items, evidence, historyByKey) {
  return items
    .filter((item) => item.status === "FRESH" && finitePositive(item.averageSalePrice) && finitePositive(item.dailySaleVelocity))
    .flatMap((item) => {
      const match = bestPattern(item, evidence.patterns || []);
      if (!match) return [];
      const trend = item.trend || {};
      const velocityChange = finite(trend.velocityChangeRatio, 0);
      const priceChange = finite(trend.priceChangeRatio, 0);
      const volatility = Number.isFinite(trend.priceVolatility) ? trend.priceVolatility : null;
      const historyPoints = finite(trend.historyPoints, 0);
      const recentRecipeUses = finite(item.recipeDemand?.recentRecipeUses, 0);
      const score = Math.round(clamp(
        finite(match.historicalWeight, 0) + finite(match.currentFitWeight, 0)
        + clamp(Math.log2(recentRecipeUses + 1) / 6, 0, 1) * 8
        + clamp(velocityChange / .60, 0, 1) * 10 + clamp(priceChange / .30, 0, 1) * 5
        + clamp(Math.log10(item.dailySaleVelocity + 1) / 4, 0, 1) * 15
        + (trend.stability === "HIGH" ? 8 : trend.stability === "MEDIUM" ? 5 : 2)
        + clamp(historyPoints / 8, 0, 1) * 5 + 3
        - (velocityChange < -.10 ? 10 : 0)
        - (volatility === null ? 4 : volatility > .45 ? 10 : volatility > .25 ? 4 : 0), 0, 100,
      ));
      const series = historyByKey.get(`${item.itemId}:${item.quality}`);
      const referencePrice = conservativeReference(series?.points || [], item);
      const currentPrice = positiveNumber(item.listingDepth?.floorPrice) || positiveNumber(item.minListingPrice) || item.averageSalePrice;
      const maximumEntryPrice = Math.max(1, Math.floor(referencePrice * (1 - finite(match.entryDiscount, .20))));
      const depth = item.listingDepth;
      const depthUnits = unitsAtOrBelow(depth, maximumEntryPrice);
      const capitalShare = finite(match.capitalShare, match.confidence === "HIGH" ? .08 : .04);
      const capitalLimit = state.budget * capitalShare;
      const liquidityLimit = Math.max(1, Math.min(99, Math.floor(item.dailySaleVelocity * .35)));
      const targetQuantity = Math.max(1, Math.min(99, Math.floor(capitalLimit / maximumEntryPrice), liquidityLimit));
      const buyQuantity = currentPrice <= maximumEntryPrice && depth?.verified
        ? Math.min(targetQuantity, depthUnits) : 0;
      const purchase = weightedPurchase(depth, buyQuantity, maximumEntryPrice);
      const cooling = velocityChange < -.10 || trend.signal === "COOLING";
      const action = cooling ? "VIGILAR"
        : currentPrice <= maximumEntryPrice && buyQuantity >= 2 ? "COMPRAR AHORA"
        : currentPrice <= maximumEntryPrice ? "VERIFICAR STOCK"
        : currentPrice <= referencePrice * 1.05 ? "ESPERAR PRECIO" : "SÓLO VIGILAR";
      const reasons = [match.currentRationale, `Patrón histórico: ${match.evidence}`];
      if (recentRecipeUses > 0) reasons.push(`Aparece como ingrediente en ${integerFormat.format(recentRecipeUses)} recetas de los dos parches más recientes.`);
      if (velocityChange >= .20) reasons.push(`La velocidad subió ${percentFormat.format(velocityChange)} en la ventana disponible.`);
      if (item.dailySaleVelocity >= 10) reasons.push(`${decimalFormat.format(item.dailySaleVelocity)} ventas/día aportan liquidez.`);
      const risk = match.confidence === "LOW" || (volatility !== null && volatility > .35) ? "ALTO"
        : volatility === null || volatility > .15 || match.confidence === "MEDIUM" ? "MEDIO" : "BAJO";
      return [{ ...item, signalKind: "projection", score, band: score >= 72 ? "ALCISTA" : score >= 60 ? "VIGILAR" : "TEMPRANA",
        risk, reasons, pattern: match, phases: match.phases || [], velocityChange, priceChange,
        referencePrice, currentPrice, maximumEntryPrice, action, targetQuantity, buyQuantity,
        capitalAtRisk: purchase.total || targetQuantity * maximumEntryPrice, weightedEntryPrice: purchase.average,
        backtest: backtestStats(series?.points || []), }];
    })
    .filter((item) => item.score >= 45)
    .sort((a, b) => b.score - a.score || b.dailySaleVelocity - a.dailySaleVelocity)
    .slice(0, 60);
}

function buildSnipes(items, historyByKey) {
  return items.flatMap((item) => {
    const depth = item.listingDepth;
    if (item.status !== "FRESH" || !depth?.verified || !finitePositive(depth.floorPrice) || !finitePositive(item.dailySaleVelocity)) return [];
    if (depth.nearFloorUnits < 2 || depth.unitsObserved < 2) return [];
    const series = historyByKey.get(`${item.itemId}:${item.quality}`);
    const points = series?.points || [];
    if (points.length < 3) return [];
    const previous = points.slice(0, -1);
    const listingBaseline = median(previous.map((point) => point.minListingPrice).filter(finitePositive));
    const saleBaseline = median(points.map((point) => point.averageSalePrice).filter(finitePositive));
    const references = [listingBaseline, saleBaseline].filter(finitePositive);
    if (!references.length) return [];
    const referencePrice = Math.min(...references);
    const currentPrice = depth.floorPrice;
    const discount = 1 - currentPrice / referencePrice;
    const volatility = finite(series.trend?.priceVolatility, 1);
    const discountThreshold = volatility > .45 ? .50 : .25;
    if (discount < discountThreshold) return [];
    const recommendedQuantity = Math.min(20, depth.nearFloorUnits, Math.max(2, Math.floor(item.dailySaleVelocity * .25)));
    const purchase = weightedPurchase(depth, recommendedQuantity, referencePrice * (1 - discountThreshold / 2));
    if (purchase.units < 2) return [];
    const conservativeExitPrice = referencePrice * .90;
    const potentialProfit = conservativeExitPrice * .95 * purchase.units - purchase.total;
    const potentialRoi = purchase.total > 0 ? potentialProfit / purchase.total : 0;
    if (potentialProfit < Math.max(200, purchase.total * .20)) return [];
    const persistentSnapshots = consecutiveDiscountSnapshots(points, referencePrice, discountThreshold);
    const score = Math.round(clamp(
      clamp(discount / .65, 0, 1) * 45 + clamp(Math.log10(item.dailySaleVelocity + 1) / 3, 0, 1) * 18
      + clamp(points.length / 10, 0, 1) * 8 + (volatility <= .10 ? 9 : volatility <= .25 ? 6 : 1)
      + clamp(potentialRoi, 0, 1) * 8 + clamp(purchase.units / 10, 0, 1) * 7
      + clamp(persistentSnapshots / 3, 0, 1) * 5, 0, 100,
    ));
    return [{ ...item, signalKind: "snipe", score, band: score >= 75 ? "URGENTE" : score >= 60 ? "FUERTE" : "REVISAR",
      risk: volatility <= .10 ? "BAJO" : volatility <= .25 ? "MEDIO" : "ALTO", referencePrice,
      listingBaseline, saleBaseline, discount, conservativeExitPrice, recommendedQuantity: purchase.units,
      weightedEntryPrice: purchase.average, estimatedPurchaseCost: purchase.total, potentialProfit,
      potentialUnitProfit: potentialProfit / purchase.units, potentialRoi, historyPoints: points.length,
      persistentSnapshots, stockVerified: true, backtest: backtestStats(points),
      reasons: [`El piso verificado está ${percentFormat.format(discount)} bajo la referencia conservadora.`,
        `${integerFormat.format(depth.nearFloorUnits)} unidades están a no más de 10% del piso; se modelan ${purchase.units}.`,
        `Precio ponderado ${gil(purchase.average)}; beneficio conservador post-fee ${gil(potentialProfit)}.`,
        persistentSnapshots > 1 ? `La anomalía persiste hace ${persistentSnapshots} snapshots.` : "La anomalía apareció en el snapshot actual."], }];
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
  document.querySelector("#metric-coverage").textContent = integerFormat.format(view === "snipes" ? state.items.filter((item) => item.stockVerified).length : state.items.filter((item) => item.listingDepth?.verified).length);
  if (elements.budget) elements.budget.value = state.budget;
}

function applyFilters() {
  const query = normalize(state.search);
  state.visible = state.items.filter((item) => {
    if (state.band && item.band !== state.band) return false;
    if (state.phase && !item.phases?.includes(state.phase)) return false;
    return !query || normalize([item.name, item.itemId, categoryName(item), item.band, item.pattern?.label, item.action].join(" ")).includes(query);
  });
  state.visible.sort(sorter(state.sort));
  render();
}

function sorter(mode) {
  if (mode === "discount") return (a, b) => finite(b.discount, -1) - finite(a.discount, -1) || b.score - a.score;
  if (mode === "velocity") return (a, b) => b.dailySaleVelocity - a.dailySaleVelocity || b.score - a.score;
  if (mode === "price") return (a, b) => b.averageSalePrice - a.averageSalePrice || b.score - a.score;
  if (mode === "entry") return (a, b) => actionRank(a.action) - actionRank(b.action) || b.score - a.score;
  if (mode === "name") return (a, b) => collator.compare(a.name, b.name);
  return (a, b) => b.score - a.score || collator.compare(a.name, b.name);
}

function render() {
  elements.grid.replaceChildren();
  const fragment = document.createDocumentFragment();
  state.visible.slice(0, 60).forEach((item) => fragment.append(createCard(item)));
  elements.grid.append(fragment);
  elements.count.textContent = view === "snipes"
    ? `${integerFormat.format(state.visible.length)} con stock real · mostrando hasta 60`
    : `${integerFormat.format(state.visible.length)} equivalentes actuales`;
  elements.empty.hidden = state.visible.length !== 0;
}

function createCard(item) {
  const card = document.createElement("article");
  card.className = `signal-card ${item.band.toLowerCase()}`;
  card.tabIndex = 0;
  const metric = view === "snipes"
    ? `<small>DESCUENTO</small><strong>${percentFormat.format(item.discount)}</strong>`
    : `<small>ENTRADA MÁX.</small><strong>${gil(item.maximumEntryPrice)}</strong>`;
  const third = view === "snipes"
    ? `<div><small>GANANCIA TOTAL</small><strong>+${gil(item.potentialProfit)}</strong></div>`
    : `<div><small>DECISIÓN</small><strong class="action-text">${escapeHtml(item.action)}</strong></div>`;
  card.innerHTML = `<div class="signal-card-top"><span class="signal-band">${escapeHtml(item.band)}</span><span class="signal-risk">RIESGO ${escapeHtml(item.risk)}</span></div>
    <div class="signal-identity"><span class="item-icon ${view === "snipes" ? "gold" : ""}" aria-hidden="true">${signalIcon()}</span><div><h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3><p>${escapeHtml(categoryName(item) || `Item ${item.itemId}`)}</p></div></div>
    <div class="signal-score"><div><small>PUNTAJE</small><strong>${item.score}<span>/100</span></strong></div><progress max="100" value="${item.score}">${item.score}</progress></div>
    <div class="signal-metrics"><div>${metric}</div><div><small>${view === "snipes" ? "COMPRA PONDERADA" : "PRECIO ACTUAL"}</small><strong>${gil(view === "snipes" ? item.weightedEntryPrice : item.currentPrice)}</strong></div>${third}</div>
    <p class="signal-reason">${escapeHtml(item.reasons[0])}</p><span class="signal-action">Ver estrategia →</span>`;
  card.addEventListener("click", () => showDetail(item));
  card.addEventListener("keydown", (event) => { if (["Enter", " "].includes(event.key)) { event.preventDefault(); showDetail(item); } });
  return card;
}

function showDetail(item) {
  const watched = Boolean(state.watched[signalKey(item)]);
  const phaseMarkup = item.phases?.length ? `<div class="phase-tags">${item.phases.map((phase) => `<span>${escapeHtml(phaseLabel(phase))}</span>`).join("")}</div>` : "";
  const strategyMarkup = view === "projections" ? `<section class="strategy-panel"><small>PLAN DE ENTRADA</small><div class="strategy-grid">
      <div><span>Decisión</span><strong>${escapeHtml(item.action)}</strong></div><div><span>Entrada máxima</span><strong>${gil(item.maximumEntryPrice)}</strong></div>
      <div><span>Cantidad objetivo</span><strong>${integerFormat.format(item.targetQuantity)} u.</strong></div><div><span>Comprar ahora</span><strong>${integerFormat.format(item.buyQuantity)} u.</strong></div>
      <div><span>Capital máximo</span><strong>${gil(item.capitalAtRisk)}</strong></div><div><span>Referencia</span><strong>${gil(item.referencePrice)}</strong></div></div>${phaseMarkup}
      <p><b>Salida:</b> ${escapeHtml(item.pattern.exitWindow)}</p><p><b>Invalidación:</b> ${escapeHtml(item.pattern.invalidation)}</p></section>`
    : `<section class="strategy-panel"><small>COMPRA MODELADA</small><div class="strategy-grid">
      <div><span>Cantidad</span><strong>${integerFormat.format(item.recommendedQuantity)} u.</strong></div><div><span>Precio ponderado</span><strong>${gil(item.weightedEntryPrice)}</strong></div>
      <div><span>Costo total</span><strong>${gil(item.estimatedPurchaseCost)}</strong></div><div><span>Salida conservadora</span><strong>${gil(item.conservativeExitPrice)}</strong></div>
      <div><span>Ganancia post-fee</span><strong>+${gil(item.potentialProfit)}</strong></div><div><span>Persistencia</span><strong>${item.persistentSnapshots} snapshots</strong></div></div></section>`;
  const backtest = item.backtest || {};
  elements.dialogContent.innerHTML = `<div class="detail-body signal-detail"><p class="eyebrow">${view === "snipes" ? "SNIPE VERIFICADO" : "PROYECCIÓN EVERCOLD 8.0"} · ITEM ${item.itemId}</p>
    <h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3><p>${escapeHtml(categoryName(item) || "Sin categoría")} · Riesgo ${escapeHtml(item.risk.toLowerCase())}</p>
    <div class="score-panel"><div class="score-heading"><div><small>SEÑAL</small><strong>${escapeHtml(item.band)}</strong></div><b>${item.score}<span>/100</span></b></div><progress class="signal-detail-progress" max="100" value="${item.score}">${item.score}</progress></div>
    ${strategyMarkup}<section class="reason-panel"><small>POR QUÉ APARECE</small><ul>${item.reasons.map((reason) => `<li>${escapeHtml(reason)}</li>`).join("")}</ul></section>
    <section class="backtest-panel"><small>SEGUIMIENTO DE LA TESIS</small><div><span>Desde primer snapshot</span><strong>${signedPercent(backtest.change)}</strong></div><div><span>Máximo observado</span><strong>${signedPercent(backtest.maxGain)}</strong></div><div><span>Drawdown máximo</span><strong>${signedPercent(backtest.maxDrawdown)}</strong></div><div><span>7 / 30 / 90 días</span><strong>${horizonText(backtest)}</strong></div></section>
    ${item.pattern ? `<section class="reason-panel"><small>MATCH HISTÓRICO → ACTUAL</small><p><strong>${escapeHtml(item.pattern.label)}</strong> · confianza ${escapeHtml(item.pattern.confidence.toLowerCase())}</p><p>Ejemplos pasados: ${escapeHtml((item.pattern.historicalExamples || []).join(", "))}.</p></section><a class="source-link" href="${escapeHtml(item.pattern.sourceUrl)}" target="_blank" rel="noopener">Ver evidencia histórica ↗</a>` : ""}
    <button id="watch-signal" class="watch-button" type="button">${watched ? "Dejar de vigilar" : "Vigilar esta señal"}</button>
    <p class="detail-warning"><strong>${view === "snipes" ? "Stock verificado por Universalis:" : "No es una predicción garantizada:"}</strong> ${view === "snipes" ? "la oferta puede cambiar antes de que llegues; confirma retainer, HQ y cantidad dentro del juego." : "el tamaño usa el capital configurado, liquidez y profundidad actual; no obliga a gastar el máximo."}</p></div>`;
  document.querySelector("#watch-signal").addEventListener("click", () => toggleWatch(item));
  elements.dialog.showModal();
}

function toggleWatch(item) {
  const key = signalKey(item);
  if (state.watched[key]) delete state.watched[key];
  else state.watched[key] = { itemId: item.itemId, quality: item.quality, name: item.name,
    targetPrice: view === "projections" ? item.maximumEntryPrice : item.weightedEntryPrice, addedAt: new Date().toISOString() };
  localStorage.setItem(STORAGE.watched, JSON.stringify(state.watched));
  renderAlerts();
  elements.dialog.close();
}

function renderAlerts() {
  if (!elements.alerts) return;
  const alerts = state.items.filter((item) => {
    const watch = state.watched[signalKey(item)];
    if (!watch) return false;
    const price = view === "snipes" ? item.weightedEntryPrice : item.currentPrice;
    return price <= watch.targetPrice || item.action === "COMPRAR AHORA" || item.band === "URGENTE";
  });
  elements.alerts.innerHTML = alerts.length ? alerts.slice(0, 6).map((item) => `<button type="button" data-key="${signalKey(item)}"><strong>${escapeHtml(item.name)}</strong><span>${view === "snipes" ? `${percentFormat.format(item.discount)} bajo referencia` : `${escapeHtml(item.action)} · ${gil(item.currentPrice)}`}</span></button>`).join("") : "<p>No hay alertas activas en tu lista de vigilancia.</p>";
  elements.alerts.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
    const item = state.items.find((candidate) => signalKey(candidate) === button.dataset.key); if (item) showDetail(item);
  }));
}

function emitBrowserAlerts() {
  if (!("Notification" in window) || Notification.permission !== "granted") return;
  const notified = readStoredObject(STORAGE.notices);
  state.items.filter((item) => state.watched[signalKey(item)] && (item.action === "COMPRAR AHORA" || item.band === "URGENTE")).forEach((item) => {
    const id = `${signalKey(item)}:${item.band}:${Math.round(item.currentPrice || item.weightedEntryPrice)}`;
    if (notified[id]) return;
    new Notification(`${item.name}: ${item.action || item.band}`, { body: view === "snipes" ? `${percentFormat.format(item.discount)} bajo referencia; stock verificado.` : `Precio ${gil(item.currentPrice)}; entrada máxima ${gil(item.maximumEntryPrice)}.` });
    notified[id] = new Date().toISOString();
  });
  localStorage.setItem(STORAGE.notices, JSON.stringify(notified));
}

function updateSignalLedger(items, collectedAt) {
  const ledger = readStoredObject(STORAGE.ledger);
  items.forEach((item) => {
    const key = signalKey(item); const price = positiveNumber(item.currentPrice) || positiveNumber(item.weightedEntryPrice) || positiveNumber(item.minListingPrice);
    if (!price) return;
    const entry = ledger[key] || { firstSeenAt: collectedAt, initialPrice: price, maxPrice: price, minPrice: price };
    ledger[key] = { ...entry, name: item.name, lastSeenAt: collectedAt, lastPrice: price, maxPrice: Math.max(entry.maxPrice, price), minPrice: Math.min(entry.minPrice, price), lastScore: item.score, lastBand: item.band };
  });
  localStorage.setItem(STORAGE.ledger, JSON.stringify(ledger));
}

function conservativeReference(points, item) {
  const previous = points.slice(0, -1);
  const values = [median(previous.map((p) => p.minListingPrice).filter(finitePositive)), median(points.map((p) => p.averageSalePrice).filter(finitePositive)), item.averageSalePrice].filter(finitePositive);
  return values.length ? Math.min(...values) : positiveNumber(item.minListingPrice) || item.averageSalePrice;
}

function weightedPurchase(depth, requestedUnits, ceiling = Infinity) {
  if (!depth?.tiers || requestedUnits <= 0) return { units: 0, total: 0, average: null };
  let remaining = requestedUnits; let total = 0; let units = 0;
  for (const tier of depth.tiers) {
    if (tier.pricePerUnit > ceiling) break;
    const take = Math.min(remaining, tier.quantity); total += take * tier.pricePerUnit; units += take; remaining -= take;
    if (!remaining) break;
  }
  return { units, total, average: units ? total / units : null };
}

function unitsAtOrBelow(depth, price) { return depth?.tiers?.reduce((sum, tier) => sum + (tier.pricePerUnit <= price ? tier.quantity : 0), 0) || 0; }
function consecutiveDiscountSnapshots(points, reference, threshold) { let count = 0; for (const point of [...points].reverse()) { if (!finitePositive(point.minListingPrice) || point.minListingPrice > reference * (1 - threshold)) break; count += 1; } return count; }
function backtestStats(points) {
  const prices = points.map((point) => positiveNumber(point.minListingPrice) || positiveNumber(point.averageSalePrice)).filter(finitePositive);
  if (!prices.length) return {};
  const first = prices[0]; const current = prices.at(-1); let peak = prices[0]; let maxDrawdown = 0;
  prices.forEach((price) => { peak = Math.max(peak, price); maxDrawdown = Math.min(maxDrawdown, price / peak - 1); });
  const start = new Date(points[0]?.collectedAt).getTime();
  const horizon = (days) => { const point = points.find((p) => new Date(p.collectedAt).getTime() - start >= days * 86400000); const price = point && (positiveNumber(point.minListingPrice) || positiveNumber(point.averageSalePrice)); return price ? price / first - 1 : null; };
  return { change: current / first - 1, maxGain: Math.max(...prices) / first - 1, maxDrawdown, return7: horizon(7), return30: horizon(30), return90: horizon(90) };
}

function horizonText(stats) { const values = [stats.return7, stats.return30, stats.return90]; return values.every((v) => !Number.isFinite(v)) ? "Acumulando datos" : values.map((v) => Number.isFinite(v) ? signedPercent(v) : "—").join(" / "); }
function phaseLabel(value) { return ({ ACUMULAR_AHORA: "Acumular ahora", ULTIMO_MES: "Último mes", LANZAMIENTO_72H: "Lanzamiento 0–72h", LEVELING_SEMANA_1: "Leveling semana 1", PRE_SAVAGE: "Pre-Savage", SAVAGE_SEMANA_1: "Savage semana 1" })[value] || value; }
function actionRank(value) { return ({ "COMPRAR AHORA": 0, "VERIFICAR STOCK": 1, "ESPERAR PRECIO": 2, "VIGILAR": 3, "SÓLO VIGILAR": 4 })[value] ?? 5; }
function signalKey(item) { return `${view}:${item.itemId}:${item.quality}`; }
function signalIcon() { return view === "snipes" ? '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>' : '<svg viewBox="0 0 24 24"><path d="m4 17 5-5 4 3 7-8"/><path d="M15 7h5v5"/></svg>'; }
function categoryName(item) { return item.searchCategoryName || item.uiCategoryName || ""; }
function finite(value, fallback) { return Number.isFinite(value) ? value : fallback; }
function finitePositive(value) { return Number.isFinite(value) && value > 0; }
function positiveNumber(value) { const number = Number(value); return Number.isFinite(number) && number > 0 ? number : null; }
function clamp(value, minimum, maximum) { return Math.max(minimum, Math.min(maximum, value)); }
function median(values) { if (!values.length) return null; const sorted = [...values].sort((a, b) => a - b); const middle = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2; }
function normalize(value) { return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim(); }
function gil(value) { return value === null || value === undefined ? "Sin dato" : `${gilFormat.format(value)} gil`; }
function signedPercent(value) { return !Number.isFinite(value) ? "Sin comparación" : `${value >= 0 ? "+" : ""}${percentFormat.format(value)}`; }
function relativeTime(value) { if (!value) return "sin fecha"; const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000)); if (minutes < 60) return `hace ${Math.max(1, minutes)} min`; const hours = Math.round(minutes / 60); return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`; }
function readStoredObject(key) { try { const value = JSON.parse(localStorage.getItem(key) || "{}"); return value && typeof value === "object" ? value : {}; } catch { return {}; } }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }

elements.search.addEventListener("input", (event) => { state.search = event.target.value; applyFilters(); });
elements.band.addEventListener("change", (event) => { state.band = event.target.value; applyFilters(); });
elements.phase?.addEventListener("change", (event) => { state.phase = event.target.value; applyFilters(); });
elements.sort.addEventListener("change", (event) => { state.sort = event.target.value; applyFilters(); });
elements.budget?.addEventListener("change", (event) => { const value = positiveNumber(event.target.value); if (!value) return; state.budget = value; localStorage.setItem(STORAGE.budget, value); loadSignals(); });
elements.enableAlerts?.addEventListener("click", async () => { if (!("Notification" in window)) { elements.enableAlerts.textContent = "No compatible"; return; } const permission = await Notification.requestPermission(); elements.enableAlerts.textContent = permission === "granted" ? "Alertas activadas" : "Alertas bloqueadas"; emitBrowserAlerts(); });
document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => { if (event.target === elements.dialog) elements.dialog.close(); });
document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); elements.search.focus(); } });

loadSignals();
