const OPPORTUNITY_WATCHLIST_KEY = "gil-intelligence.opportunity-watchlist";

const state = {
  data: null,
  dataSource: "",
  filtered: [],
  search: "",
  confidence: "recommended",
  world: "",
  sort: "confidence",
  sortDirection: "desc",
  watchOnly: false,
  watchlist: loadWatchlist(),
  page: 1,
  pageSize: 25,
};

const elements = {
  rows: document.querySelector("#opportunity-rows"),
  search: document.querySelector("#search-input"),
  confidence: document.querySelector("#confidence-select"),
  world: document.querySelector("#world-select"),
  sort: document.querySelector("#sort-select"),
  watchOnly: document.querySelector("#watchlist-toggle"),
  watchSummary: document.querySelector("#watch-summary"),
  count: document.querySelector("#result-count"),
  empty: document.querySelector("#empty-state"),
  pagination: document.querySelector("#pagination"),
  pagePrevious: document.querySelector("#page-previous"),
  pageNext: document.querySelector("#page-next"),
  pageNumbers: document.querySelector("#page-numbers"),
  pageSize: document.querySelector("#page-size-select"),
  dialog: document.querySelector("#detail-dialog"),
  dialogContent: document.querySelector("#dialog-content"),
  capitalForm: document.querySelector("#capital-form"),
  capitalInput: document.querySelector("#capital-input"),
  capitalShare: document.querySelector("#capital-share"),
  capitalResult: document.querySelector("#capital-result"),
};

const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const gilFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("es-CL", { style: "percent", maximumFractionDigits: 0 });
const nameCollator = new Intl.Collator("es", { sensitivity: "base", numeric: true });

async function loadOpportunities() {
  const apiBaseUrl = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
  const endpoints = apiBaseUrl
    ? [
        { url: `${apiBaseUrl}/v1/opportunities`, source: "Backend Google Cloud" },
        { url: "./data/opportunities.json", source: "respaldo estático" },
      ]
    : [{ url: "./data/opportunities.json", source: "respaldo estático" }];
  const errors = [];
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint.url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (payload.kind !== "market-opportunities" || !Array.isArray(payload.opportunities)) throw new Error("formato inesperado");
      state.data = payload;
      state.dataSource = endpoint.source;
      hydrateMeta();
      renderWorldOptions();
      applyFilters();
      calculateCapitalPlan();
      return;
    } catch (error) { errors.push(`${endpoint.source}: ${error.message}`); }
  }
  elements.count.textContent = "No pudimos cargar los datos";
  elements.empty.hidden = false;
  elements.empty.querySelector("h3").textContent = "Señales sin datos";
  elements.empty.querySelector("p").textContent = errors.join(" · ");
  elements.pagination.hidden = true;
}

function hydrateMeta() {
  const { meta, summary } = state.data;
  document.querySelector("#scope-label").textContent = meta.homeWorldName || meta.scope;
  document.querySelector("#updated-label").textContent = `Mercado ${relativeTime(meta.marketCollectedAt)}`;
  document.querySelector("#metric-total").textContent = integerFormat.format(summary.opportunities);
  document.querySelector("#metric-high").textContent = integerFormat.format(summary.highConfidence);
  document.querySelector("#metric-verified").textContent = integerFormat.format(summary.stockVerified ?? 0);
  document.querySelector("#metric-stress").textContent = percentFormat.format(meta.priceStress);
  document.querySelector("#metric-fee").textContent = `más fee de ${percentFormat.format(meta.feeRate)}`;
  document.querySelector("#footer-source").textContent = `${meta.source} · ${meta.scope} · ${state.dataSource}`;
}

function renderWorldOptions() {
  const worlds = [...new Set(state.data.opportunities.map((item) => item.sourceWorldName))].sort(nameCollator.compare);
  const all = elements.world.firstElementChild;
  elements.world.replaceChildren(all);
  worlds.forEach((world) => {
    const option = document.createElement("option");
    option.value = world;
    option.textContent = world;
    elements.world.append(option);
  });
}

function applyFilters() {
  if (!state.data) return;
  const query = normalize(state.search);
  state.filtered = state.data.opportunities.filter((item) => {
    if (state.confidence === "recommended" && item.confidenceBand === "WATCH") return false;
    if (state.confidence && state.confidence !== "recommended" && item.confidenceBand !== state.confidence) return false;
    if (state.world && item.sourceWorldName !== state.world) return false;
    if (state.watchOnly && !isWatched(item)) return false;
    if (!query) return true;
    return normalize([item.name, item.itemId, item.categoryName, item.sourceWorldName, item.quality, item.stockStatus].join(" ")).includes(query);
  });
  state.filtered.sort(sorter(state.sort));
  updateSortHeaders();
  renderRows();
  renderWatchSummary();
}

function sorter(sort) {
  let compare;
  if (sort === "trip") compare = (a, b) => numberOrLow(a.estimatedTripProfit) - numberOrLow(b.estimatedTripProfit);
  else if (sort === "profit") compare = (a, b) => numberOrLow(a.unitProfit) - numberOrLow(b.unitProfit);
  else if (sort === "velocity") compare = (a, b) => numberOrLow(a.dailySaleVelocity) - numberOrLow(b.dailySaleVelocity);
  else if (sort === "roi") compare = (a, b) => numberOrLow(a.roi) - numberOrLow(b.roi);
  else if (sort === "buy") compare = (a, b) => numberOrLow(a.averagePurchasePrice ?? a.sourcePrice) - numberOrLow(b.averagePurchasePrice ?? b.sourcePrice);
  else if (sort === "sell") compare = (a, b) => numberOrLow(a.conservativeSellPrice) - numberOrLow(b.conservativeSellPrice);
  else if (sort === "stock") compare = (a, b) => numberOrLow(a.availableUnits) - numberOrLow(b.availableUnits);
  else if (sort === "name") compare = (a, b) => nameCollator.compare(a.name, b.name);
  else if (sort === "world") compare = (a, b) => nameCollator.compare(a.sourceWorldName, b.sourceWorldName);
  else compare = (a, b) => numberOrLow(a.confidenceScore) - numberOrLow(b.confidenceScore);
  return state.sortDirection === "asc"
    ? (a, b) => compare(a, b) || nameCollator.compare(a.name, b.name)
    : (a, b) => -compare(a, b) || nameCollator.compare(a.name, b.name);
}

function renderRows() {
  elements.rows.replaceChildren();
  const totalPages = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  const firstIndex = (state.page - 1) * state.pageSize;
  const visible = state.filtered.slice(firstIndex, firstIndex + state.pageSize);
  const fragment = document.createDocumentFragment();
  visible.forEach((item) => fragment.append(createRow(item)));
  elements.rows.append(fragment);
  const lastIndex = Math.min(firstIndex + visible.length, state.filtered.length);
  elements.count.textContent = state.filtered.length
    ? `${integerFormat.format(state.filtered.length)} señales · ${integerFormat.format(firstIndex + 1)}–${integerFormat.format(lastIndex)}`
    : "0 señales";
  elements.empty.hidden = state.filtered.length !== 0;
  renderPagination(totalPages);
}

function createRow(item) {
  const row = document.createElement("tr");
  row.tabIndex = 0;
  row.innerHTML = `
    <td data-label="Item"><div class="entity entity-watch"><button class="watch-button ${isWatched(item) ? "active" : ""}" type="button" aria-label="${isWatched(item) ? "Quitar" : "Guardar"} ${escapeHtml(item.name)}">★</button>${itemIcon()}<span><strong>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</strong><small>${escapeHtml(item.categoryName || `Item ${item.itemId}`)}</small></span></div></td>
    <td data-label="Comprar en"><div class="entity source-world"><strong>${escapeHtml(item.sourceWorldName)}</strong><small>${escapeHtml(item.sourceDataCenterName || "North America")} · World ${item.sourceWorldId}</small></div></td>
    <td data-label="Compra" class="numeric">${gil(item.averagePurchasePrice ?? item.sourcePrice)}</td>
    <td data-label="Venta conservadora" class="numeric">${gil(item.conservativeSellPrice)}</td>
    <td data-label="Ganancia / u." class="numeric net-cell">${gil(item.unitProfit)}</td>
    <td data-label="ROI" class="numeric">${percentFormat.format(item.roi)}</td>
    <td data-label="Ventas / día" class="numeric velocity-cell ${item.dailySaleVelocity === null || item.dailySaleVelocity === undefined ? "missing-data" : ""}" title="${item.dailySaleVelocity === null || item.dailySaleVelocity === undefined ? "Universalis no publicó velocidad diaria para Cactuar. No significa cero ventas." : ""}">${velocity(item.dailySaleVelocity)}</td>
    <td data-label="Stock"><span class="stock-pill ${item.stockVerified ? "verified" : "unverified"}">${item.stockVerified ? `${integerFormat.format(item.availableUnits)} u.` : "SIN VERIFICAR"}</span></td>
    <td data-label="Confianza"><span class="confidence-pill ${item.confidenceBand.toLowerCase()}">${confidenceLabel(item.confidenceBand)} · ${item.confidenceScore}</span></td>
  `;
  row.querySelector(".watch-button").addEventListener("click", (event) => { event.stopPropagation(); toggleWatch(item); });
  row.addEventListener("click", () => showDetail(item));
  row.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target === row) { event.preventDefault(); showDetail(item); }
  });
  return row;
}

function showDetail(item) {
  const components = item.scoreComponents || {};
  const stockText = item.stockVerified
    ? `<strong>Stock comprobado:</strong> ${integerFormat.format(item.availableUnits)} unidades elegibles en ${integerFormat.format(item.verifiedListingCount)} tiers; revisado ${relativeTime(item.stockCheckedAt)}.`
    : `<strong>Stock sin verificar:</strong> el precio proviene del agregado. Confirma listing y cantidad antes de viajar.`;
  const tiers = item.stockVerified && item.purchaseTiers?.length
    ? `<div class="purchase-tiers">${item.purchaseTiers.map((tier) => `<span>${integerFormat.format(tier.quantity)} × ${gil(tier.pricePerUnit)}</span>`).join("")}</div>`
    : "";
  elements.dialogContent.innerHTML = `
    <div class="detail-body">
      <p class="eyebrow">${escapeHtml(item.sourceWorldName)} → CACTUAR · ${escapeHtml(item.quality)}</p>
      <button class="watch-button detail-watch ${isWatched(item) ? "active" : ""}" type="button">★ ${isWatched(item) ? "Guardado" : "Guardar"}</button>
      <h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3>
      <p>${escapeHtml(item.categoryName || `Item ${item.itemId}`)}</p>
      <div class="trip-route">
        <div><small>COMPRAR PROMEDIO</small><strong>${gil(item.averagePurchasePrice ?? item.sourcePrice)}</strong><span>${escapeHtml(item.sourceWorldName)}</span></div>
        <b aria-hidden="true">→</b>
        <div><small>VENDER HASTA</small><strong>${gil(item.conservativeSellPrice)}</strong><span>Cactuar</span></div>
      </div>
      ${tiers}
      <div class="detail-stats">
        <div><small>Ganancia / unidad</small><strong>${gil(item.unitProfit)}</strong></div>
        <div><small>Retorno</small><strong>${percentFormat.format(item.roi)}</strong></div>
        <div><small>Cantidad sugerida</small><strong>${integerFormat.format(item.recommendedQuantity)}</strong></div>
        <div><small>Capital requerido</small><strong>${gil(item.estimatedPurchaseCost)}</strong></div>
        <div><small>Ganancia por viaje</small><strong>${gil(item.estimatedTripProfit)}</strong></div>
        <div><small>Ventas / día</small><strong>${velocity(item.dailySaleVelocity)}</strong></div>
      </div>
      <section class="score-panel">
        <div class="score-heading"><div><small>CONFIANZA</small><strong>${confidenceLabel(item.confidenceBand)}</strong></div><b>${item.confidenceScore}<span>/100</span></b></div>
        ${scoreRow("Margen", components.margin, 30)}
        ${scoreRow("Liquidez", components.liquidity, 25)}
        ${scoreRow("Frescura", components.freshness, 20)}
        ${scoreRow("Persistencia", components.persistence, 25)}
        <p>El spread conservador apareció en ${percentFormat.format(item.persistenceRatio)} de ${item.historySamples} snapshots disponibles.</p>
      </section>
      <p class="detail-warning">${stockText}</p>
    </div>`;
  elements.dialogContent.querySelector(".detail-watch").addEventListener("click", () => { toggleWatch(item); showDetail(item); });
  if (!elements.dialog.open) elements.dialog.showModal();
}

function calculateCapitalPlan() {
  if (!state.data) return;
  const capital = Number(elements.capitalInput.value);
  const maxShare = Number(elements.capitalShare.value);
  if (!Number.isFinite(capital) || capital < 10000) {
    elements.capitalResult.innerHTML = "<p>Ingresa al menos 10.000 gil.</p>";
    return;
  }
  const candidates = state.filtered.filter((item) => item.stockVerified && item.purchaseTiers?.length && item.unitProfit > 0);
  const units = [];
  candidates.forEach((item) => {
    let remaining = item.recommendedQuantity;
    const itemBudget = capital * maxShare;
    let itemSpend = 0;
    const netSell = item.conservativeSellPrice * (1 - state.data.meta.feeRate);
    item.purchaseTiers.forEach((tier) => {
      const count = Math.min(remaining, tier.quantity);
      for (let index = 0; index < count; index += 1) {
        if (itemSpend + tier.pricePerUnit > itemBudget) break;
        const profit = netSell - tier.pricePerUnit;
        if (profit > 0) units.push({ item, cost: tier.pricePerUnit, profit, roi: profit / tier.pricePerUnit });
        itemSpend += tier.pricePerUnit;
        remaining -= 1;
      }
    });
  });
  units.sort((a, b) => b.roi - a.roi || b.profit - a.profit);
  let spent = 0, profit = 0;
  const selected = new Map();
  units.forEach((unit) => {
    if (spent + unit.cost > capital) return;
    spent += unit.cost;
    profit += unit.profit;
    const key = opportunityKey(unit.item);
    const selection = selected.get(key) || { item: unit.item, quantity: 0, cost: 0, profit: 0 };
    selection.quantity += 1;
    selection.cost += unit.cost;
    selection.profit += unit.profit;
    selected.set(key, selection);
  });
  if (!selected.size) {
    elements.capitalResult.innerHTML = `<p>No hay unidades con stock verificado dentro de los filtros y el capital actual. Prueba ampliar los filtros o aumentar el monto.</p>`;
    return;
  }
  const selections = [...selected.values()].sort((a, b) => b.profit - a.profit);
  elements.capitalResult.innerHTML = `
    <div class="capital-totals"><div><small>Invertir</small><strong>${gil(spent)}</strong></div><div><small>Reserva</small><strong>${gil(capital - spent)}</strong></div><div><small>Ganancia estimada</small><strong>${gil(profit)}</strong></div><div><small>ROI cesta</small><strong>${percentFormat.format(profit / spent)}</strong></div></div>
    <div class="capital-list">${selections.map((selection) => `<div><span><strong>${escapeHtml(selection.item.name)}${selection.item.quality === "HQ" ? " · HQ" : ""}</strong><small>${escapeHtml(selection.item.sourceWorldName)} · ${selection.quantity} u.</small></span><span><b>${gil(selection.cost)}</b><small>+${gil(selection.profit)}</small></span></div>`).join("")}</div>
    <p class="optimizer-note">Estimación greedy por ROI, con venta estresada, fee, stock observado y un máximo de ${percentFormat.format(maxShare)} por item. No considera impuestos de compra ni cambios posteriores.</p>`;
}

function itemIcon() {
  return '<span class="item-icon gold" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 7h10M10 3l4 4-4 4M20 17H10M14 13l-4 4 4 4"/></svg></span>';
}

function defaultSortDirection(mode) { return ["name", "world", "buy"].includes(mode) ? "asc" : "desc"; }
function setSort(mode, toggle = false) {
  state.sortDirection = toggle && state.sort === mode
    ? (state.sortDirection === "asc" ? "desc" : "asc")
    : defaultSortDirection(mode);
  state.sort = mode;
  elements.sort.value = mode;
  state.page = 1;
  applyFilters();
}
function updateSortHeaders() {
  document.querySelectorAll("th[data-sort]").forEach((header) => {
    if (header.dataset.sort === state.sort) header.setAttribute("aria-sort", state.sortDirection === "asc" ? "ascending" : "descending");
    else header.removeAttribute("aria-sort");
  });
}
function bindSortableHeaders() {
  document.querySelectorAll("th[data-sort] .sort-button").forEach((button) => {
    button.addEventListener("click", () => setSort(button.closest("th").dataset.sort, true));
  });
}

function scoreRow(label, value = 0, maximum) {
  return `<div class="score-row"><span>${escapeHtml(label)}</span><progress max="${maximum}" value="${Math.max(0, Math.min(maximum, value))}">${decimalFormat.format(value)}</progress><strong>${decimalFormat.format(value)}/${maximum}</strong></div>`;
}

function renderPagination(totalPages) {
  elements.pagination.hidden = state.filtered.length === 0;
  elements.pagePrevious.disabled = state.page <= 1;
  elements.pageNext.disabled = state.page >= totalPages;
  elements.pageNumbers.replaceChildren();
  paginationEntries(state.page, totalPages).forEach((entry) => {
    if (entry === "…") {
      const ellipsis = document.createElement("span");
      ellipsis.className = "page-ellipsis";
      ellipsis.textContent = entry;
      elements.pageNumbers.append(ellipsis);
      return;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-number";
    button.textContent = entry;
    button.classList.toggle("active", entry === state.page);
    if (entry === state.page) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => goToPage(entry));
    elements.pageNumbers.append(button);
  });
}

function paginationEntries(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const pages = [...new Set([1, total, current - 1, current, current + 1])].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const entries = [];
  pages.forEach((page, index) => { if (index > 0 && page - pages[index - 1] > 1) entries.push("…"); entries.push(page); });
  return entries;
}

function goToPage(page) { state.page = page; renderRows(); document.querySelector("#explorer-title").scrollIntoView({ behavior: "smooth", block: "start" }); }
function opportunityKey(item) { return `${item.itemId}:${item.quality}:${item.sourceWorldId}`; }
function isWatched(item) { return state.watchlist.has(opportunityKey(item)); }
function toggleWatch(item) {
  const key = opportunityKey(item);
  if (state.watchlist.has(key)) state.watchlist.delete(key); else state.watchlist.add(key);
  localStorage.setItem(OPPORTUNITY_WATCHLIST_KEY, JSON.stringify([...state.watchlist]));
  applyFilters();
}
function loadWatchlist() {
  try { return new Set(JSON.parse(localStorage.getItem(OPPORTUNITY_WATCHLIST_KEY) || "[]")); }
  catch (_error) { return new Set(); }
}
function renderWatchSummary() {
  const watched = state.data.opportunities.filter(isWatched);
  const active = watched.filter((item) => item.stockVerified && item.confidenceBand !== "WATCH");
  elements.watchSummary.innerHTML = `<span>★ ${integerFormat.format(watched.length)} guardados</span><strong>${integerFormat.format(active.length)} listos para revisar</strong><small>La lista queda sólo en este navegador.</small>`;
}

function confidenceLabel(value) { return ({ HIGH: "ALTA", MEDIUM: "MEDIA", WATCH: "OBSERVAR" })[value] || value; }
function normalize(value) { return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim(); }
function numberOrLow(value) { return Number.isFinite(value) ? value : -Infinity; }
function gil(value) { return value === null || value === undefined ? "—" : `${gilFormat.format(value)} gil`; }
function velocity(value) { return value === null || value === undefined ? "Sin datos Cactuar" : `${decimalFormat.format(value)} /d`; }
function relativeTime(value) {
  if (!value) return "sin fecha";
  const deltaMinutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (deltaMinutes < 1) return "ahora";
  if (deltaMinutes < 60) return `hace ${deltaMinutes} min`;
  const hours = Math.round(deltaMinutes / 60);
  return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`;
}
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }

elements.search.addEventListener("input", (event) => { state.search = event.target.value; state.page = 1; applyFilters(); });
elements.confidence.addEventListener("change", (event) => { state.confidence = event.target.value; state.page = 1; applyFilters(); });
elements.world.addEventListener("change", (event) => { state.world = event.target.value; state.page = 1; applyFilters(); });
elements.sort.addEventListener("change", (event) => setSort(event.target.value));
elements.watchOnly.addEventListener("change", (event) => { state.watchOnly = event.target.checked; state.page = 1; applyFilters(); });
elements.capitalForm.addEventListener("submit", (event) => { event.preventDefault(); calculateCapitalPlan(); });
elements.pagePrevious.addEventListener("click", () => goToPage(state.page - 1));
elements.pageNext.addEventListener("click", () => goToPage(state.page + 1));
elements.pageSize.addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; renderRows(); });
document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => { if (event.target === elements.dialog) elements.dialog.close(); });
document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); elements.search.focus(); } });

bindSortableHeaders();
loadOpportunities();
