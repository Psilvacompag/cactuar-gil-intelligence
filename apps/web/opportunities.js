const state = {
  data: null,
  filtered: [],
  search: "",
  confidence: "recommended",
  world: "",
  sort: "confidence",
  page: 1,
  pageSize: 25,
};

const elements = {
  rows: document.querySelector("#opportunity-rows"),
  search: document.querySelector("#search-input"),
  confidence: document.querySelector("#confidence-select"),
  world: document.querySelector("#world-select"),
  sort: document.querySelector("#sort-select"),
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
      const response = await fetch(endpoint.url, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (payload.kind !== "market-opportunities" || !Array.isArray(payload.opportunities)) {
        throw new Error("formato inesperado");
      }
      state.data = payload;
      state.dataSource = endpoint.source;
      hydrateMeta();
      renderWorldOptions();
      applyFilters();
      return;
    } catch (error) {
      errors.push(`${endpoint.source}: ${error.message}`);
    }
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
  document.querySelector("#metric-medium").textContent = integerFormat.format(summary.mediumConfidence);
  document.querySelector("#metric-stress").textContent = percentFormat.format(meta.priceStress);
  document.querySelector("#metric-fee").textContent = `más fee de ${percentFormat.format(meta.feeRate)}`;
  document.querySelector("#footer-source").textContent = `${meta.source} · ${meta.scope} · ${state.dataSource}`;
}

function renderWorldOptions() {
  const worlds = [...new Set(state.data.opportunities.map((item) => item.sourceWorldName))]
    .sort(nameCollator.compare);
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
    if (!query) return true;
    return normalize([
      item.name,
      item.itemId,
      item.categoryName,
      item.sourceWorldName,
      item.quality,
    ].join(" ")).includes(query);
  });
  state.filtered.sort(sorter(state.sort));
  renderRows();
}

function sorter(sort) {
  const descending = (field) => (a, b) =>
    numberOrLow(b[field]) - numberOrLow(a[field]) || b.confidenceScore - a.confidenceScore;
  if (sort === "trip") return descending("estimatedTripProfit");
  if (sort === "profit") return descending("unitProfit");
  if (sort === "velocity") return descending("dailySaleVelocity");
  if (sort === "roi") return descending("roi");
  return (a, b) =>
    b.confidenceScore - a.confidenceScore
      || b.estimatedTripProfit - a.estimatedTripProfit
      || nameCollator.compare(a.name, b.name);
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
    <td data-label="Item"><div class="entity"><strong>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</strong><small>${escapeHtml(item.categoryName || `Item ${item.itemId}`)}</small></div></td>
    <td data-label="Comprar en"><div class="entity source-world"><strong>${escapeHtml(item.sourceWorldName)}</strong><small>Aether · World ${item.sourceWorldId}</small></div></td>
    <td data-label="Compra" class="numeric">${gil(item.sourcePrice)}</td>
    <td data-label="Venta conservadora" class="numeric">${gil(item.conservativeSellPrice)}</td>
    <td data-label="Ganancia / u." class="numeric net-cell">${gil(item.unitProfit)}</td>
    <td data-label="ROI" class="numeric">${percentFormat.format(item.roi)}</td>
    <td data-label="Ventas / día" class="numeric">${velocity(item.dailySaleVelocity)}</td>
    <td data-label="Confianza"><span class="confidence-pill ${item.confidenceBand.toLowerCase()}">${confidenceLabel(item.confidenceBand)} · ${item.confidenceScore}</span></td>
  `;
  row.addEventListener("click", () => showDetail(item));
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      showDetail(item);
    }
  });
  return row;
}

function showDetail(item) {
  const components = item.scoreComponents || {};
  elements.dialogContent.innerHTML = `
    <div class="detail-body">
      <p class="eyebrow">${escapeHtml(item.sourceWorldName)} → CACTUAR · ${escapeHtml(item.quality)}</p>
      <h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3>
      <p>${escapeHtml(item.categoryName || `Item ${item.itemId}`)}</p>
      <div class="trip-route">
        <div><small>COMPRAR</small><strong>${gil(item.sourcePrice)}</strong><span>${escapeHtml(item.sourceWorldName)}</span></div>
        <b aria-hidden="true">→</b>
        <div><small>VENDER HASTA</small><strong>${gil(item.conservativeSellPrice)}</strong><span>Cactuar</span></div>
      </div>
      <div class="detail-stats">
        <div><small>Ganancia / unidad</small><strong>${gil(item.unitProfit)}</strong></div>
        <div><small>Retorno</small><strong>${percentFormat.format(item.roi)}</strong></div>
        <div><small>Cantidad sugerida</small><strong>${integerFormat.format(item.recommendedQuantity)}</strong></div>
        <div><small>Ganancia por viaje</small><strong>${gil(item.estimatedTripProfit)}</strong></div>
        <div><small>Ventas / día</small><strong>${velocity(item.dailySaleVelocity)}</strong></div>
        <div><small>Edad máxima del dato</small><strong>${decimalFormat.format(item.dataAgeHours)} h</strong></div>
      </div>
      <section class="score-panel">
        <div class="score-heading">
          <div><small>CONFIANZA</small><strong>${confidenceLabel(item.confidenceBand)}</strong></div>
          <b>${item.confidenceScore}<span>/100</span></b>
        </div>
        ${scoreRow("Margen", components.margin, 30)}
        ${scoreRow("Liquidez", components.liquidity, 25)}
        ${scoreRow("Frescura", components.freshness, 20)}
        ${scoreRow("Persistencia", components.persistence, 25)}
        <p>El spread conservador apareció en ${percentFormat.format(item.persistenceRatio)} de ${item.historySamples} snapshots disponibles.</p>
      </section>
      <p class="detail-warning"><strong>Antes de viajar:</strong> revisa stock, cantidad y precio actual. El endpoint agregado no muestra cuántas unidades quedan en ese listing.</p>
    </div>
  `;
  elements.dialog.showModal();
}

function scoreRow(label, value = 0, maximum) {
  return `
    <div class="score-row">
      <span>${escapeHtml(label)}</span>
      <progress max="${maximum}" value="${Math.max(0, Math.min(maximum, value))}">${decimalFormat.format(value)}</progress>
      <strong>${decimalFormat.format(value)}/${maximum}</strong>
    </div>
  `;
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
  const pages = [...new Set([1, total, current - 1, current, current + 1])]
    .filter((page) => page >= 1 && page <= total)
    .sort((a, b) => a - b);
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

function confidenceLabel(value) {
  return { HIGH: "ALTA", MEDIUM: "MEDIA", WATCH: "OBSERVAR" }[value] || value;
}

function normalize(value) {
  return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

function numberOrLow(value) {
  return Number.isFinite(value) ? value : -Infinity;
}

function gil(value) {
  if (value === null || value === undefined) return "—";
  return `${gilFormat.format(value)} gil`;
}

function velocity(value) {
  if (value === null || value === undefined) return "—";
  return `${decimalFormat.format(value)} /d`;
}

function relativeTime(value) {
  if (!value) return "sin fecha";
  const deltaMinutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000));
  if (deltaMinutes < 1) return "ahora";
  if (deltaMinutes < 60) return `hace ${deltaMinutes} min`;
  const hours = Math.round(deltaMinutes / 60);
  return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`;
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
elements.confidence.addEventListener("change", (event) => {
  state.confidence = event.target.value;
  state.page = 1;
  applyFilters();
});
elements.world.addEventListener("change", (event) => {
  state.world = event.target.value;
  state.page = 1;
  applyFilters();
});
elements.sort.addEventListener("change", (event) => {
  state.sort = event.target.value;
  state.page = 1;
  applyFilters();
});
elements.pagePrevious.addEventListener("click", () => goToPage(state.page - 1));
elements.pageNext.addEventListener("click", () => goToPage(state.page + 1));
elements.pageSize.addEventListener("change", (event) => {
  state.pageSize = Number(event.target.value);
  state.page = 1;
  renderRows();
});
document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => {
  if (event.target === elements.dialog) elements.dialog.close();
});
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.search.focus();
  }
});

loadOpportunities();
