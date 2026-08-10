const state = {
  data: null,
  dataSource: "",
  history: null,
  historyPromise: null,
  filtered: [],
  mode: "gathering",
  search: "",
  category: "",
  sort: "velocity",
  sortDirection: "desc",
  freshOnly: true,
  watchOnly: false,
  watchlist: loadWatchlist(),
  page: 1,
  pageSize: 50,
};

const elements = {
  rows: document.querySelector("#market-rows"),
  search: document.querySelector("#search-input"),
  sort: document.querySelector("#sort-select"),
  category: document.querySelector("#category-select"),
  fresh: document.querySelector("#fresh-toggle"),
  watchOnly: document.querySelector("#watchlist-toggle"),
  watchSummary: document.querySelector("#watch-summary"),
  valueLabel: document.querySelector("#value-column-label"),
  gatheringTab: document.querySelector("#gathering-tab"),
  craftingTab: document.querySelector("#crafting-tab"),
  count: document.querySelector("#result-count"),
  empty: document.querySelector("#empty-state"),
  pagination: document.querySelector("#pagination"),
  pagePrevious: document.querySelector("#page-previous"),
  pageNext: document.querySelector("#page-next"),
  pageNumbers: document.querySelector("#page-numbers"),
  pageSize: document.querySelector("#page-size-select"),
  dialog: document.querySelector("#detail-dialog"),
  dialogContent: document.querySelector("#dialog-content"),
};

const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const gilFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("es-CL", { style: "percent", maximumFractionDigits: 0 });
const nameCollator = new Intl.Collator("es", { sensitivity: "base", numeric: true });

async function loadMarket() {
  const errors = [];
  for (const endpoint of dataEndpoints("market-items")) {
    try {
      const response = await fetch(endpoint.url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (payload.kind !== "market-items" || !Array.isArray(payload.items)) throw new Error("formato inesperado");
      state.data = payload;
      state.dataSource = endpoint.source;
      hydrateMeta();
      renderCategoryOptions();
      applyFilters();
      return;
    } catch (error) {
      errors.push(`${endpoint.source}: ${error.message}`);
    }
  }
  elements.count.textContent = "No pudimos cargar los datos";
  elements.empty.hidden = false;
  elements.empty.querySelector("h3").textContent = "Mercado sin datos";
  elements.empty.querySelector("p").textContent = errors.join(" · ");
  elements.pagination.hidden = true;
}

function dataEndpoints(kind) {
  const apiBaseUrl = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
  const filename = kind === "market-history" ? "market-history.json" : "market-items.json";
  return apiBaseUrl
    ? [
        { url: `${apiBaseUrl}/v1/${kind}`, source: "Backend Google Cloud" },
        { url: `./data/${filename}`, source: "respaldo estático" },
      ]
    : [{ url: `./data/${filename}`, source: "respaldo estático" }];
}

function hydrateMeta() {
  const { meta, summary } = state.data;
  document.querySelector("#scope-label").textContent = meta.scope;
  document.querySelector("#updated-label").textContent = `Mercado ${relativeTime(meta.marketCollectedAt)}`;
  document.querySelector("#metric-gathering").textContent = integerFormat.format(summary.gatheringItems);
  document.querySelector("#metric-crafting").textContent = integerFormat.format(summary.craftingItems);
  document.querySelector("#metric-fresh").textContent = integerFormat.format(summary.freshRows);
  document.querySelector("#metric-profitable").textContent = integerFormat.format(summary.profitableCrafts ?? 0);
  document.querySelector("#fresh-window").textContent = `uploads de Cactuar en ${meta.freshnessHours} h`;
  document.querySelector("#footer-source").textContent = `${meta.source} · ${meta.scope} · ${state.dataSource}`;
}

function modeItems() {
  return state.data.items.filter((item) => state.mode === "gathering" ? item.gatherable : item.craftable);
}

function renderCategoryOptions() {
  const options = [...new Set(modeItems().map(categoryName).filter(Boolean))].sort(nameCollator.compare);
  elements.category.replaceChildren();
  const all = document.createElement("option");
  all.value = "";
  all.textContent = `Todas (${options.length})`;
  elements.category.append(all);
  options.forEach((name) => {
    const option = document.createElement("option");
    option.value = name;
    option.textContent = name;
    elements.category.append(option);
  });
  elements.category.value = state.category;
}

function applyFilters() {
  if (!state.data) return;
  const query = normalize(state.search);
  state.filtered = modeItems().filter((item) => {
    if (state.freshOnly && item.status !== "FRESH") return false;
    if (state.watchOnly && !isWatched(item)) return false;
    if (state.category && categoryName(item) !== state.category) return false;
    if (!query) return true;
    return normalize([
      item.name, item.itemId, item.craftTypeName, gatheringLabel(item.gatheringType),
      item.searchCategoryName, item.uiCategoryName, item.quality, trendLabel(item.trend?.signal),
    ].join(" ")).includes(query);
  });
  state.filtered.sort(sorter(state.sort));
  updateSortHeaders();
  renderRows();
  renderWatchSummary();
}

function sorter(sort) {
  let compare;
  if (sort === "revenue") compare = (a, b) => numberOrLow(a.estimatedDailyRevenue) - numberOrLow(b.estimatedDailyRevenue);
  else if (sort === "profit") compare = (a, b) => numberOrLow(craftProfit(a)) - numberOrLow(craftProfit(b));
  else if (sort === "momentum") compare = (a, b) => numberOrLow(a.trend?.velocityChangeRatio) - numberOrLow(b.trend?.velocityChangeRatio);
  else if (sort === "price") compare = (a, b) => numberOrLow(a.averageSalePrice) - numberOrLow(b.averageSalePrice);
  else if (sort === "name") compare = (a, b) => nameCollator.compare(a.name, b.name);
  else if (sort === "category") compare = (a, b) => nameCollator.compare(categoryName(a), categoryName(b));
  else if (sort === "origin") compare = (a, b) => nameCollator.compare(originLabel(a), originLabel(b));
  else compare = (a, b) => numberOrLow(a.dailySaleVelocity) - numberOrLow(b.dailySaleVelocity);
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
  const noun = state.mode === "gathering" ? "items recolectables" : "items crafteables";
  elements.count.textContent = state.filtered.length
    ? `${integerFormat.format(state.filtered.length)} ${noun} · ${integerFormat.format(firstIndex + 1)}–${integerFormat.format(lastIndex)}`
    : `0 ${noun}`;
  elements.empty.hidden = state.filtered.length !== 0;
  elements.valueLabel.dataset.sort = state.mode === "crafting" ? "profit" : "revenue";
  elements.valueLabel.querySelector(".sort-label").textContent = state.mode === "crafting" ? "Ganancia / día" : "Gil / día";
  updateSortHeaders();
  renderPagination(totalPages);
}

function createRow(item) {
  const row = document.createElement("tr");
  row.tabIndex = 0;
  const value = state.mode === "crafting" ? craftProfit(item) : item.estimatedDailyRevenue;
  const trend = item.trend?.signal || "NEW";
  row.innerHTML = `
    <td data-label="Item"><div class="entity entity-watch"><button class="watch-button ${isWatched(item) ? "active" : ""}" type="button" aria-label="${isWatched(item) ? "Quitar" : "Guardar"} ${escapeHtml(item.name)}">★</button>${itemIcon(item.iconId, state.mode === "gathering" ? "leaf" : "craft")}<span><strong>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</strong><small>Item ${item.itemId}</small></span></div></td>
    <td data-label="Origen / oficio"><div class="entity"><strong>${escapeHtml(originLabel(item))}</strong><small>${state.mode === "gathering" ? "Gathering" : "Crafting"}</small></div></td>
    <td data-label="Categoría">${escapeHtml(categoryName(item) || "Sin categoría")}</td>
    <td data-label="Precio medio" class="numeric">${gil(item.averageSalePrice)}</td>
    <td data-label="Ventas / día" class="numeric velocity-cell ${item.dailySaleVelocity === null || item.dailySaleVelocity === undefined ? "missing-data" : ""}" title="${item.dailySaleVelocity === null || item.dailySaleVelocity === undefined ? "Universalis no publicó velocidad diaria para Cactuar. No significa cero ventas." : ""}">${velocity(item.dailySaleVelocity)}</td>
    <td data-label="${state.mode === "crafting" ? "Ganancia / día" : "Gil / día"}" class="numeric net-cell">${gil(value)}</td>
    <td data-label="Tendencia"><span class="trend-pill ${trend.toLowerCase()}">${trendLabel(trend)}</span></td>
  `;
  row.querySelector(".watch-button").addEventListener("click", (event) => {
    event.stopPropagation();
    toggleWatch(item);
  });
  row.addEventListener("click", () => showDetail(item));
  row.addEventListener("keydown", (event) => {
    if ((event.key === "Enter" || event.key === " ") && event.target === row) {
      event.preventDefault();
      showDetail(item);
    }
  });
  return row;
}

async function showDetail(item) {
  state.detailKey = itemKey(item);
  elements.dialogContent.innerHTML = detailMarkup(item, null, true);
  bindDetailWatch(item);
  if (!elements.dialog.open) elements.dialog.showModal();
  try {
    const history = await loadHistory();
    const series = history?.series?.find((entry) => entry.key === itemKey(item));
    if (elements.dialog.open && state.detailKey === itemKey(item)) elements.dialogContent.innerHTML = detailMarkup(item, series, false);
  } catch (_error) {
    if (elements.dialog.open && state.detailKey === itemKey(item)) elements.dialogContent.innerHTML = detailMarkup(item, null, false);
  }
  bindDetailWatch(item);
}

function bindDetailWatch(item) {
  const button = elements.dialogContent.querySelector(".detail-watch");
  if (button) button.addEventListener("click", () => {
    toggleWatch(item);
    showDetail(item);
  });
}

function detailMarkup(item, history, loading) {
  const productionSources = [
    item.gatherable ? gatheringLabel(item.gatheringType) : null,
    item.craftable ? item.craftTypeName || "Crafting" : null,
  ].filter(Boolean);
  return `
    <div class="detail-body">
      <p class="eyebrow">ITEM ${item.itemId} · ${escapeHtml(item.quality)}</p>
      <button class="watch-button detail-watch ${isWatched(item) ? "active" : ""}" type="button">★ ${isWatched(item) ? "Guardado" : "Guardar"}</button>
      <div class="detail-item-title">${GilItemIcons.markup(item.iconId, { fallback: state.mode === "gathering" ? "leaf" : "craft" })}<div><h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3><p>${escapeHtml(categoryName(item) || "Sin categoría")}</p></div></div>
      <div class="detail-route"><span>SE OBTIENE POR</span><strong>${escapeHtml(productionSources.join(" · "))}</strong></div>
      <div class="detail-stats">
        <div><small>Listing mínimo</small><strong>${gil(item.minListingPrice)}</strong></div>
        <div><small>Precio medio vendido</small><strong>${gil(item.averageSalePrice)}</strong></div>
        <div><small>Ventas / día</small><strong>${velocity(item.dailySaleVelocity)}</strong></div>
        <div><small>Gil / día estimado</small><strong>${gil(item.estimatedDailyRevenue)}</strong></div>
        <div><small>Mediana de listings</small><strong>${gil(item.medianListingPrice)}</strong></div>
        <div><small>Último upload en Cactuar</small><strong>${formatDate(item.latestUploadAt)}</strong></div>
      </div>
      ${recipeMarkup(item.recipe)}
      ${historyMarkup(history, loading)}
    </div>`;
}

function recipeMarkup(recipe) {
  if (!recipe) return "";
  const resultLabel = recipe.resultQuantity > 1 ? `${recipe.resultQuantity} unidades por craft` : "1 unidad por craft";
  return `
    <section class="recipe-panel">
      <div class="history-heading"><div><small>RECETA MÁS BARATA COMPLETA</small><strong>${escapeHtml(recipe.craftTypeName)} · ${resultLabel}</strong></div><span class="confidence-pill ${recipe.confidence.toLowerCase()}">${craftConfidenceLabel(recipe.confidence)}</span></div>
      <div class="detail-stats recipe-financials">
        <div><small>Costo materiales</small><strong>${gil(recipe.estimatedMaterialCost)}</strong></div>
        <div><small>Venta conservadora</small><strong>${gil(recipe.conservativeSalePrice)}</strong></div>
        <div><small>Ganancia / craft</small><strong class="${recipe.profitPerCraft > 0 ? "positive" : "negative"}">${gil(recipe.profitPerCraft)}</strong></div>
        <div><small>ROI del craft</small><strong>${ratio(recipe.roi)}</strong></div>
      </div>
      <div class="ingredient-list">
        ${recipe.ingredients.map((ingredient) => `
          <div><span><strong>${escapeHtml(ingredient.name)}</strong><small>${ingredient.gatherable ? "Recolectable" : "Comprar / fabricar"} · ${integerFormat.format(ingredient.quantity)} u.</small></span><b>${gil(ingredient.subtotal)}</b></div>
        `).join("")}
      </div>
    </section>`;
}

function historyMarkup(series, loading) {
  if (loading) return `<section class="history-panel"><div class="history-heading"><div><small>HISTORIAL</small><strong>Cargando evolución…</strong></div></div><div class="history-chart"><p>Consultando snapshots guardados.</p></div></section>`;
  if (!series || series.points.length < 2) return `<section class="history-panel"><div class="history-heading"><div><small>HISTORIAL</small><strong>Aún no hay suficientes puntos</strong></div></div><div class="history-chart"><p>Se necesitan al menos dos recolecciones para dibujar una tendencia.</p></div></section>`;
  const points = series.points.filter((point) => Number.isFinite(point.averageSalePrice));
  return `
    <section class="history-panel">
      <div class="history-heading"><div><small>PRECIO MEDIO</small><strong>${trendLabel(series.trend.signal)}</strong></div><span>${points.length} snapshots · ${change(series.trend.priceChangeRatio)}</span></div>
      <div class="history-chart">${sparkline(points)}</div>
      <div class="history-stats"><span>Demanda ${change(series.trend.velocityChangeRatio)}</span><span>Estabilidad ${stabilityLabel(series.trend.stability)}</span></div>
    </section>`;
}

async function loadHistory() {
  if (state.history) return state.history;
  if (state.historyPromise) return state.historyPromise;
  state.historyPromise = (async () => {
    const errors = [];
    for (const endpoint of dataEndpoints("market-history")) {
      try {
        const response = await fetch(endpoint.url);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        if (payload.kind !== "market-history" || !Array.isArray(payload.series)) throw new Error("formato inesperado");
        state.history = payload;
        return payload;
      } catch (error) { errors.push(error.message); }
    }
    throw new Error(errors.join(" · "));
  })();
  return state.historyPromise;
}

function sparkline(points) {
  if (points.length < 2) return "<p>Sin puntos suficientes.</p>";
  const width = 560, height = 180, pad = 24;
  const values = points.map((point) => point.averageSalePrice);
  const min = Math.min(...values), max = Math.max(...values), span = Math.max(1, max - min);
  const coordinates = values.map((value, index) => ({
    x: pad + index * (width - pad * 2) / Math.max(1, values.length - 1),
    y: height - pad - (value - min) * (height - pad * 2) / span,
    value,
  }));
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Precio entre ${gil(min)} y ${gil(max)}">
    <line class="history-grid" x1="${pad}" y1="${pad}" x2="${width - pad}" y2="${pad}" />
    <line class="history-grid" x1="${pad}" y1="${height - pad}" x2="${width - pad}" y2="${height - pad}" />
    <polyline class="history-line" points="${coordinates.map((point) => `${point.x},${point.y}`).join(" ")}" />
    ${coordinates.map((point) => `<circle class="history-dot" cx="${point.x}" cy="${point.y}" r="4"><title>${gil(point.value)}</title></circle>`).join("")}
    <text class="history-label" x="${pad}" y="16">${escapeHtml(gil(max))}</text>
    <text class="history-label" x="${pad}" y="${height - 5}">${escapeHtml(gil(min))}</text>
  </svg>`;
}

function setMode(mode) {
  state.mode = mode;
  state.category = "";
  state.page = 1;
  const gathering = mode === "gathering";
  elements.gatheringTab.classList.toggle("active", gathering);
  elements.gatheringTab.setAttribute("aria-selected", String(gathering));
  elements.craftingTab.classList.toggle("active", !gathering);
  elements.craftingTab.setAttribute("aria-selected", String(!gathering));
  renderCategoryOptions();
  applyFilters();
}

function itemIcon(iconId, kind) { return GilItemIcons.markup(iconId, { fallback: kind }); }

function defaultSortDirection(mode) { return ["name", "category", "origin"].includes(mode) ? "asc" : "desc"; }
function setSort(mode, toggle = false) {
  state.sortDirection = toggle && state.sort === mode
    ? (state.sortDirection === "asc" ? "desc" : "asc")
    : defaultSortDirection(mode);
  state.sort = mode;
  if ([...elements.sort.options].some((option) => option.value === mode)) elements.sort.value = mode;
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
  pages.forEach((page, index) => {
    if (index > 0 && page - pages[index - 1] > 1) entries.push("…");
    entries.push(page);
  });
  return entries;
}

function goToPage(page) {
  state.page = page;
  renderRows();
  document.querySelector("#explorer-title").scrollIntoView({ behavior: "smooth", block: "start" });
}

function itemKey(item) { return `market:${item.itemId}:${item.quality}`; }
function craftProfit(item) { return item.recipe?.confidence === "LOW" ? null : item.recipe?.estimatedDailyProfit; }
function isWatched(item) { return state.watchlist.has(itemKey(item)); }
function toggleWatch(item) {
  const key = itemKey(item);
  GilWatchlist.toggle(key, { module: "market", itemId: item.itemId, quality: item.quality, name: item.name });
  state.watchlist = GilWatchlist.keys();
  applyFilters();
}
function loadWatchlist() {
  return GilWatchlist.keys();
}
function renderWatchSummary() {
  const watched = state.data.items.filter(isWatched);
  const alerts = watched.filter((item) => item.trend?.signal === "DEMAND_UP" || (item.recipe?.profitPerCraft > 0 && item.recipe?.confidence !== "LOW"));
  elements.watchSummary.innerHTML = `<span>★ ${integerFormat.format(watched.length)} guardados</span><strong>${integerFormat.format(alerts.length)} con señal activa</strong><small>Compartidos con el Centro de señales.</small>`;
}

function categoryName(item) { return item.searchCategoryName || item.uiCategoryName || ""; }
function originLabel(item) { return state.mode === "gathering" ? gatheringLabel(item.gatheringType) : item.craftTypeName || "Crafting"; }
function gatheringLabel(value) { return value === "FISHING" ? "Fishing" : value === "MINER_BOTANIST" ? "Miner / Botanist" : "Gathering"; }
function trendLabel(value) { return ({ DEMAND_UP: "Demanda ↑", COOLING: "Enfriándose", PRICE_UP: "Precio ↑", STABLE: "Estable", NEW: "Nuevo" })[value] || "Sin tendencia"; }
function stabilityLabel(value) { return ({ HIGH: "alta", MEDIUM: "media", LOW: "baja", UNKNOWN: "por medir" })[value] || value; }
function craftConfidenceLabel(value) { return ({ HIGH: "ALTA", MEDIUM: "MEDIA", LOW: "BAJA" })[value] || value; }
function normalize(value) { return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim(); }
function numberOrLow(value) { return Number.isFinite(value) ? value : -Infinity; }
function gil(value) { return value === null || value === undefined ? "—" : `${gilFormat.format(value)} gil`; }
function velocity(value) { return value === null || value === undefined ? "Sin datos Cactuar" : `${decimalFormat.format(value)} /d`; }
function ratio(value) { return value === null || value === undefined ? "—" : percentFormat.format(value); }
function change(value) { return value === null || value === undefined ? "sin comparación" : `${value >= 0 ? "+" : ""}${percentFormat.format(value)}`; }
function relativeTime(value) {
  if (!value) return "sin fecha";
  const deltaMinutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (deltaMinutes < 1) return "ahora";
  if (deltaMinutes < 60) return `hace ${deltaMinutes} min`;
  const hours = Math.round(deltaMinutes / 60);
  return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`;
}
function formatDate(value) { return !value ? "Sin dato" : new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }

elements.gatheringTab.addEventListener("click", () => setMode("gathering"));
elements.craftingTab.addEventListener("click", () => setMode("crafting"));
elements.search.addEventListener("input", (event) => { state.search = event.target.value; state.page = 1; applyFilters(); });
elements.sort.addEventListener("change", (event) => setSort(event.target.value));
elements.category.addEventListener("change", (event) => { state.category = event.target.value; state.page = 1; applyFilters(); });
elements.fresh.addEventListener("change", (event) => { state.freshOnly = event.target.checked; state.page = 1; applyFilters(); });
elements.watchOnly.addEventListener("change", (event) => { state.watchOnly = event.target.checked; state.page = 1; applyFilters(); });
elements.pagePrevious.addEventListener("click", () => goToPage(state.page - 1));
elements.pageNext.addEventListener("click", () => goToPage(state.page + 1));
elements.pageSize.addEventListener("change", (event) => { state.pageSize = Number(event.target.value); state.page = 1; renderRows(); });
document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => { if (event.target === elements.dialog) elements.dialog.close(); });
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); elements.search.focus(); }
});

bindSortableHeaders();
loadMarket();
