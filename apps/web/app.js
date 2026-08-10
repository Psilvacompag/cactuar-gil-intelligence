const state = {
  data: null,
  history: null,
  historyPromise: null,
  filtered: [],
  search: "",
  currencyId: null,
  sort: "net",
  freshOnly: true,
  page: 1,
  pageSize: 50,
};

const elements = {
  rows: document.querySelector("#conversion-rows"),
  rowTemplate: document.querySelector("#row-template"),
  search: document.querySelector("#search-input"),
  sort: document.querySelector("#sort-select"),
  fresh: document.querySelector("#fresh-toggle"),
  chips: document.querySelector("#currency-chips"),
  count: document.querySelector("#result-count"),
  empty: document.querySelector("#empty-state"),
  pagination: document.querySelector("#pagination"),
  pagePrevious: document.querySelector("#page-previous"),
  pageNext: document.querySelector("#page-next"),
  pageNumbers: document.querySelector("#page-numbers"),
  pageSize: document.querySelector("#page-size-select"),
  dialog: document.querySelector("#detail-dialog"),
  dialogContent: document.querySelector("#dialog-content"),
  currencyDialog: document.querySelector("#currency-dialog"),
  currencyDirectorySearch: document.querySelector("#currency-directory-search"),
  currencyDirectorySort: document.querySelector("#currency-directory-sort"),
  currencyDirectoryCount: document.querySelector("#currency-directory-count"),
  currencyDirectoryList: document.querySelector("#currency-directory-list"),
};

const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const gilFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
const highlightedCurrencyIds = [20, 21, 22, 28, 48, 47, 26807, 26533, 41784, 41785, 28063];

async function loadDashboard() {
  const apiBaseUrl = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
  const endpoints = apiBaseUrl
    ? [
        { url: `${apiBaseUrl}/v1/dashboard`, source: "cloud" },
        { url: "./data/dashboard.json", source: "static" },
      ]
    : [{ url: "./data/dashboard.json", source: "static" }];
  const errors = [];
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint.url);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      state.data = await response.json();
      state.dataSource = endpoint.source;
      hydrateMeta();
      renderChips();
      applyFilters();
      return;
    } catch (error) {
      errors.push(`${endpoint.source}: ${error.message}`);
    }
  }
  elements.count.textContent = "No pudimos cargar los datos";
  elements.empty.hidden = false;
  elements.empty.querySelector("h3").textContent = "Dashboard sin datos";
  elements.empty.querySelector("p").textContent = `El backend y el respaldo estático no respondieron. (${errors.join("; ")})`;
}

function hydrateMeta() {
  const { meta, summary } = state.data;
  document.title = `Gil Intelligence · ${meta.scope}`;
  document.querySelector("#scope-label").textContent = `${meta.scope} · ${meta.scopeLevel}`;
  document.querySelector("#updated-label").textContent = `Mercado ${relativeTime(meta.marketCollectedAt)}`;
  document.querySelector("#metric-conversions").textContent = integerFormat.format(summary.directConversions);
  document.querySelector("#metric-currencies").textContent = integerFormat.format(summary.currencies);
  document.querySelector("#metric-fresh").textContent = integerFormat.format(summary.fresh);
  document.querySelector("#fresh-window").textContent = `ventana de ${meta.freshnessHours} horas`;
  document.querySelector("#metric-basis").textContent = basisLabel(meta.priceBasis);
  document.querySelector("#metric-fee").textContent = `fee ${(meta.feeRate * 100).toFixed(0)}% incluido`;
  const backendLabel = state.dataSource === "cloud" ? "Backend Google Cloud" : "respaldo estático";
  document.querySelector("#footer-source").textContent = `${meta.source} · ${meta.scope} · ${backendLabel}`;
}

function renderChips() {
  elements.chips.replaceChildren();
  const liquidity = currencyLiquidity();
  const byId = new Map(state.data.currencies.map((currency) => [currency.itemId, currency]));
  const highlighted = highlightedCurrencyIds.map((itemId) => byId.get(itemId)).filter(Boolean);
  const ranked = [...state.data.currencies].sort((a, b) =>
    (liquidity.get(b.itemId) || 0) - (liquidity.get(a.itemId) || 0)
      || b.freshCount - a.freshCount
      || b.conversionCount - a.conversionCount,
  );
  const highlightedIds = new Set(highlighted.map((currency) => currency.itemId));
  const popular = [...highlighted, ...ranked.filter((currency) => !highlightedIds.has(currency.itemId))]
    .slice(0, 8);
  const all = document.createElement("button");
  all.className = "chip active";
  all.id = "all-currencies-chip";
  all.type = "button";
  all.textContent = "Todas";
  all.addEventListener("click", () => selectCurrency(null));
  elements.chips.append(all);
  for (const currency of popular) {
    const chip = document.createElement("button");
    chip.className = "chip";
    chip.type = "button";
    chip.dataset.currencyId = currency.itemId;
    chip.textContent = currency.name;
    chip.title = `${currency.conversionCount} conversiones · ${velocity(liquidity.get(currency.itemId))} combinadas`;
    chip.addEventListener("click", () => selectCurrency(currency.itemId));
    elements.chips.append(chip);
  }
  const directory = document.createElement("button");
  directory.className = "chip directory-chip";
  directory.id = "currency-directory-button";
  directory.type = "button";
  directory.textContent = `Ver las ${integerFormat.format(state.data.currencies.length)} monedas`;
  directory.addEventListener("click", openCurrencyDirectory);
  elements.chips.append(directory);
}

function currencyLiquidity() {
  const rewardVelocity = new Map();
  for (const item of state.data.conversions) {
    if (item.status !== "FRESH" || item.dailySaleVelocity === null) continue;
    const rewardKey = `${item.currencyItemId}:${item.rewardItemId}:${item.rewardIsHq ? 1 : 0}`;
    rewardVelocity.set(rewardKey, Math.max(rewardVelocity.get(rewardKey) || 0, item.dailySaleVelocity));
  }
  const totals = new Map();
  for (const [key, observedVelocity] of rewardVelocity) {
    const currencyId = Number(key.split(":", 1)[0]);
    totals.set(currencyId, (totals.get(currencyId) || 0) + observedVelocity);
  }
  return totals;
}

function selectCurrency(currencyId) {
  state.currencyId = currencyId;
  state.page = 1;
  updateCurrencyControls();
  applyFilters();
}

function updateCurrencyControls() {
  const all = document.querySelector("#all-currencies-chip");
  const directory = document.querySelector("#currency-directory-button");
  const selectedChip = currencyIdChip(state.currencyId);
  all?.classList.toggle("active", state.currencyId === null);
  document.querySelectorAll(".chip[data-currency-id]").forEach((chip) => {
    chip.classList.toggle("active", Number(chip.dataset.currencyId) === state.currencyId);
  });
  if (!directory) return;
  directory.classList.toggle("active", state.currencyId !== null && !selectedChip);
  const selected = state.data.currencies.find((currency) => currency.itemId === state.currencyId);
  directory.textContent = selected && !selectedChip
    ? `${selected.name} · cambiar`
    : `Ver las ${integerFormat.format(state.data.currencies.length)} monedas`;
}

function currencyIdChip(currencyId) {
  if (currencyId === null) return null;
  return document.querySelector(`.chip[data-currency-id="${currencyId}"]`);
}

function openCurrencyDirectory() {
  elements.currencyDirectorySearch.value = "";
  elements.currencyDirectorySort.value = "name";
  renderCurrencyDirectory();
  elements.currencyDialog.showModal();
  requestAnimationFrame(() => elements.currencyDirectorySearch.focus());
}

function renderCurrencyDirectory() {
  const query = normalize(elements.currencyDirectorySearch.value);
  const liquidity = currencyLiquidity();
  const currencies = state.data.currencies
    .filter((currency) => !query || normalize(`${currency.name} ${currency.itemId}`).includes(query))
    .sort(currencyDirectorySorter(elements.currencyDirectorySort.value, liquidity));
  elements.currencyDirectoryCount.textContent = `${integerFormat.format(currencies.length)} monedas`;
  const fragment = document.createDocumentFragment();
  if (!query) fragment.append(createCurrencyOption(null, liquidity));
  currencies.forEach((currency) => fragment.append(createCurrencyOption(currency, liquidity)));
  elements.currencyDirectoryList.replaceChildren(fragment);
}

function currencyDirectorySorter(mode, liquidity) {
  if (mode === "liquidity") return (a, b) =>
    (liquidity.get(b.itemId) || 0) - (liquidity.get(a.itemId) || 0)
      || a.name.localeCompare(b.name, "es");
  if (mode === "conversions") return (a, b) =>
    b.freshCount - a.freshCount || b.conversionCount - a.conversionCount
      || a.name.localeCompare(b.name, "es");
  if (mode === "return") return (a, b) =>
    (b.bestNetGil || 0) - (a.bestNetGil || 0) || a.name.localeCompare(b.name, "es");
  return (a, b) => a.name.localeCompare(b.name, "es");
}

function createCurrencyOption(currency, liquidity) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "currency-option";
  if (currency === null) {
    button.classList.add("all-option");
    button.classList.toggle("selected", state.currencyId === null);
    button.innerHTML = "<span><strong>Todas las monedas</strong><small>Quitar el filtro actual</small></span>";
    button.addEventListener("click", () => chooseDirectoryCurrency(null));
    return button;
  }
  button.classList.toggle("selected", state.currencyId === currency.itemId);
  const identity = document.createElement("span");
  const name = document.createElement("strong");
  const detail = document.createElement("small");
  name.textContent = currency.name;
  detail.textContent = `Item ${currency.itemId} · ${currency.freshCount}/${currency.conversionCount} frescas`;
  identity.append(name, detail);
  const stats = document.createElement("span");
  stats.className = "currency-option-stats";
  const best = document.createElement("strong");
  const sales = document.createElement("small");
  best.textContent = gil(currency.bestNetGil);
  sales.textContent = `${velocity(liquidity.get(currency.itemId))} combinadas`;
  stats.append(best, sales);
  button.append(identity, stats);
  button.addEventListener("click", () => chooseDirectoryCurrency(currency.itemId));
  return button;
}

function chooseDirectoryCurrency(currencyId) {
  selectCurrency(currencyId);
  elements.currencyDialog.close();
}

function applyFilters() {
  if (!state.data) return;
  const query = normalize(state.search);
  state.filtered = state.data.conversions.filter((item) => {
    if (state.currencyId !== null && item.currencyItemId !== state.currencyId) return false;
    if (state.freshOnly && item.status !== "FRESH") return false;
    if (!query) return true;
    return normalize([
      item.currencyName,
      item.rewardName,
      item.shopName,
      item.currencyItemId,
      item.rewardItemId,
    ].join(" ")).includes(query);
  });
  state.filtered.sort(sorter(state.sort));
  renderRows();
}

function renderRows() {
  elements.rows.replaceChildren();
  const totalPages = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
  state.page = Math.min(state.page, totalPages);
  const firstIndex = (state.page - 1) * state.pageSize;
  const visibleRows = state.filtered.slice(firstIndex, firstIndex + state.pageSize);
  const fragment = document.createDocumentFragment();
  visibleRows.forEach((item) => fragment.append(createRow(item)));
  elements.rows.append(fragment);
  const lastIndex = Math.min(firstIndex + visibleRows.length, state.filtered.length);
  elements.count.textContent = state.filtered.length
    ? `${integerFormat.format(state.filtered.length)} conversiones · ${integerFormat.format(firstIndex + 1)}–${integerFormat.format(lastIndex)}`
    : "0 conversiones encontradas";
  elements.empty.hidden = state.filtered.length !== 0;
  renderPagination(totalPages);
}

function renderPagination(totalPages) {
  elements.pagination.hidden = state.filtered.length === 0;
  elements.pagePrevious.disabled = state.page <= 1;
  elements.pageNext.disabled = state.page >= totalPages;
  elements.pageNumbers.replaceChildren();
  for (const entry of paginationEntries(state.page, totalPages)) {
    if (entry === "…") {
      const ellipsis = document.createElement("span");
      ellipsis.className = "page-ellipsis";
      ellipsis.textContent = entry;
      elements.pageNumbers.append(ellipsis);
      continue;
    }
    const button = document.createElement("button");
    button.type = "button";
    button.className = "page-number";
    button.textContent = entry;
    button.classList.toggle("active", entry === state.page);
    button.setAttribute("aria-label", `Página ${entry}`);
    if (entry === state.page) button.setAttribute("aria-current", "page");
    button.addEventListener("click", () => goToPage(entry));
    elements.pageNumbers.append(button);
  }
}

function paginationEntries(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, index) => index + 1);
  const pages = new Set([1, total, current - 1, current, current + 1]);
  const sorted = [...pages].filter((page) => page >= 1 && page <= total).sort((a, b) => a - b);
  const result = [];
  sorted.forEach((page, index) => {
    if (index > 0 && page - sorted[index - 1] > 1) result.push("…");
    result.push(page);
  });
  return result;
}

function goToPage(page) {
  state.page = page;
  renderRows();
  document.querySelector("#explorer-title").scrollIntoView({ behavior: "smooth", block: "start" });
}

function createRow(item) {
  const row = elements.rowTemplate.content.firstElementChild.cloneNode(true);
  fillEntity(row.querySelector(".currency-entity"), item.currencyName, `Item ${item.currencyItemId}`);
  fillEntity(
    row.querySelector(".reward-entity"),
    `${item.rewardName}${item.rewardIsHq ? " · HQ" : ""}`,
    item.shopName,
  );
  row.querySelector(".cost-cell").textContent = `${integerFormat.format(item.currencyQuantity)}×`;
  row.querySelector(".price-cell").textContent = gil(item.marketUnitPrice);
  row.querySelector(".net-cell").textContent = gil(item.netGilPerCurrency);
  row.querySelector(".velocity-cell").textContent = velocity(item.dailySaleVelocity);
  const pill = row.querySelector(".status-pill");
  pill.textContent = item.status === "FRESH" ? "FRESCO" : "ANTIGUO";
  pill.classList.add(item.status.toLowerCase());
  row.addEventListener("click", () => showDetail(item));
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      showDetail(item);
    }
  });
  return row;
}

function fillEntity(container, name, detail) {
  const strong = document.createElement("strong");
  const small = document.createElement("small");
  strong.textContent = name;
  strong.title = name;
  small.textContent = detail;
  container.append(strong, small);
}

function showDetail(item) {
  elements.dialogContent.innerHTML = `
    <div class="detail-body">
      <p class="eyebrow">CONVERSIÓN DIRECTA · ${escapeHtml(state.data.meta.scope)}</p>
      <h3>${escapeHtml(item.rewardName)}${item.rewardIsHq ? " · HQ" : ""}</h3>
      <p>${escapeHtml(item.shopName)} · Shop ${item.shopId}</p>
      <div class="detail-route">
        <strong>${integerFormat.format(item.currencyQuantity)} × ${escapeHtml(item.currencyName)}</strong>
        <span>SE CONVIERTE EN</span>
        <strong>${integerFormat.format(item.rewardQuantity)} × ${escapeHtml(item.rewardName)}</strong>
      </div>
      <div class="detail-stats">
        <div><small>Listing mínimo actual</small><strong>${gil(item.marketUnitPrice)}</strong></div>
        <div><small>Gil neto / moneda</small><strong>${gil(item.netGilPerCurrency)}</strong></div>
        <div><small>Ventas / día</small><strong>${velocity(item.dailySaleVelocity)}</strong></div>
        <div><small>Último upload</small><strong>${formatDate(item.latestUploadAt)}</strong></div>
      </div>
      <section class="history-panel">
        <div class="history-heading">
          <div>
            <small>HISTORIAL</small>
            <strong>Gil neto por moneda</strong>
          </div>
          <span id="history-range">Cargando…</span>
        </div>
        <div id="history-chart" class="history-chart" data-history-key="${conversionKey(item)}">
          <p>Cargando historial…</p>
        </div>
      </section>
    </div>`;
  elements.dialog.showModal();
  renderHistory(item);
}

async function loadHistory() {
  if (state.history) return state.history;
  if (state.historyPromise) return state.historyPromise;
  const apiBaseUrl = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
  if (!apiBaseUrl) throw new Error("El historial requiere el backend cloud");
  state.historyPromise = fetch(`${apiBaseUrl}/v1/history`)
    .then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    })
    .then((payload) => {
      state.history = new Map(payload.series.map((series) => [series.key, series]));
      return state.history;
    })
    .finally(() => { state.historyPromise = null; });
  return state.historyPromise;
}

async function renderHistory(item) {
  const key = conversionKey(item);
  try {
    const history = await loadHistory();
    const container = document.querySelector("#history-chart");
    if (!container || container.dataset.historyKey !== key) return;
    const series = history.get(key);
    const points = (series?.points || []).filter((point) => point.netGilPerCurrency !== null);
    if (points.length < 2) {
      container.innerHTML = "<p>Se necesitan al menos dos snapshots para mostrar la tendencia.</p>";
      document.querySelector("#history-range").textContent = `${points.length} punto`;
      return;
    }
    drawHistoryChart(container, points);
    document.querySelector("#history-range").textContent = `${points.length} snapshots`;
  } catch (error) {
    const container = document.querySelector("#history-chart");
    if (!container || container.dataset.historyKey !== key) return;
    container.innerHTML = `<p>Historial no disponible. (${escapeHtml(error.message)})</p>`;
    document.querySelector("#history-range").textContent = "Sin datos";
  }
}

function drawHistoryChart(container, points) {
  const width = 520;
  const height = 180;
  const padding = { top: 18, right: 18, bottom: 32, left: 56 };
  const values = points.map((point) => point.netGilPerCurrency);
  let minimum = Math.min(...values);
  let maximum = Math.max(...values);
  if (minimum === maximum) {
    minimum = Math.max(0, minimum * 0.95);
    maximum *= 1.05;
  }
  const x = (index) => padding.left + (index / (points.length - 1)) * (width - padding.left - padding.right);
  const y = (value) => padding.top + ((maximum - value) / (maximum - minimum)) * (height - padding.top - padding.bottom);
  const namespace = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(namespace, "svg");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `Historial de gil neto por moneda, ${points.length} snapshots`);

  const gridTop = document.createElementNS(namespace, "line");
  gridTop.setAttribute("x1", padding.left);
  gridTop.setAttribute("x2", width - padding.right);
  gridTop.setAttribute("y1", y(maximum));
  gridTop.setAttribute("y2", y(maximum));
  gridTop.setAttribute("class", "history-grid");
  const gridBottom = gridTop.cloneNode();
  gridBottom.setAttribute("y1", y(minimum));
  gridBottom.setAttribute("y2", y(minimum));

  const line = document.createElementNS(namespace, "polyline");
  line.setAttribute("points", points.map((point, index) => `${x(index)},${y(point.netGilPerCurrency)}`).join(" "));
  line.setAttribute("class", "history-line");
  svg.append(gridTop, gridBottom, line);

  points.forEach((point, index) => {
    const dot = document.createElementNS(namespace, "circle");
    dot.setAttribute("cx", x(index));
    dot.setAttribute("cy", y(point.netGilPerCurrency));
    dot.setAttribute("r", index === points.length - 1 ? "4" : "2.5");
    dot.setAttribute("class", "history-dot");
    const title = document.createElementNS(namespace, "title");
    title.textContent = `${formatDate(point.marketCollectedAt)}: ${gil(point.netGilPerCurrency)}`;
    dot.append(title);
    svg.append(dot);
  });

  const labels = [
    { x: 4, y: y(maximum) + 4, text: gil(maximum) },
    { x: 4, y: y(minimum) + 4, text: gil(minimum) },
    { x: padding.left, y: height - 8, text: shortDate(points[0].marketCollectedAt), anchor: "start" },
    { x: width - padding.right, y: height - 8, text: shortDate(points.at(-1).marketCollectedAt), anchor: "end" },
  ];
  labels.forEach((label) => {
    const text = document.createElementNS(namespace, "text");
    text.setAttribute("x", label.x);
    text.setAttribute("y", label.y);
    text.setAttribute("text-anchor", label.anchor || "start");
    text.setAttribute("class", "history-label");
    text.textContent = label.text;
    svg.append(text);
  });
  container.replaceChildren(svg);
}

function conversionKey(item) {
  return [item.currencyItemId, item.currencyQuantity, item.rewardItemId, item.rewardQuantity, item.rewardIsHq ? 1 : 0].join(":");
}

function shortDate(value) {
  return new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "short" }).format(new Date(value));
}

function sorter(mode) {
  if (mode === "velocity") return (a, b) => (b.dailySaleVelocity || 0) - (a.dailySaleVelocity || 0);
  if (mode === "price") return (a, b) => (b.marketUnitPrice || 0) - (a.marketUnitPrice || 0);
  if (mode === "currency") return (a, b) => a.currencyName.localeCompare(b.currencyName, "es");
  return (a, b) => (b.netGilPerCurrency || 0) - (a.netGilPerCurrency || 0);
}

function normalize(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

function gil(value) {
  if (value === null || value === undefined) return "—";
  return `${gilFormat.format(value)} gil`;
}

function velocity(value) {
  if (value === null || value === undefined) return "—";
  return `${decimalFormat.format(value)} /d`;
}

function basisLabel(value) {
  return { MIN_LISTING: "Listing mínimo", MEDIAN_LISTING: "Mediana", RECENT_AVG_SALE: "Venta reciente" }[value] || value;
}

function relativeTime(value) {
  if (!value) return "sin fecha";
  const deltaMinutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (deltaMinutes < 1) return "ahora";
  if (deltaMinutes < 60) return `hace ${deltaMinutes} min`;
  const hours = Math.round(deltaMinutes / 60);
  if (hours < 24) return `hace ${hours} h`;
  return `hace ${Math.round(hours / 24)} d`;
}

function formatDate(value) {
  if (!value) return "Sin dato";
  return new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

elements.search.addEventListener("input", (event) => {
  state.search = event.target.value;
  state.page = 1;
  applyFilters();
});
elements.sort.addEventListener("change", (event) => { state.sort = event.target.value; state.page = 1; applyFilters(); });
elements.fresh.addEventListener("change", (event) => { state.freshOnly = event.target.checked; state.page = 1; applyFilters(); });
elements.pagePrevious.addEventListener("click", () => goToPage(state.page - 1));
elements.pageNext.addEventListener("click", () => goToPage(state.page + 1));
elements.pageSize.addEventListener("change", (event) => {
  state.pageSize = Number(event.target.value);
  state.page = 1;
  renderRows();
});
document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => { if (event.target === elements.dialog) elements.dialog.close(); });
document.querySelector("#currency-dialog-close").addEventListener("click", () => elements.currencyDialog.close());
elements.currencyDialog.addEventListener("click", (event) => {
  if (event.target === elements.currencyDialog) elements.currencyDialog.close();
});
elements.currencyDirectorySearch.addEventListener("input", renderCurrencyDirectory);
elements.currencyDirectorySort.addEventListener("change", renderCurrencyDirectory);
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.search.focus();
  }
});

loadDashboard();
