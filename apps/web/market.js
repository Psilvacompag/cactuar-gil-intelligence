const state = {
  data: null,
  filtered: [],
  mode: "gathering",
  search: "",
  category: "",
  sort: "velocity",
  freshOnly: true,
  page: 1,
  pageSize: 50,
};

const elements = {
  rows: document.querySelector("#market-rows"),
  search: document.querySelector("#search-input"),
  sort: document.querySelector("#sort-select"),
  category: document.querySelector("#category-select"),
  fresh: document.querySelector("#fresh-toggle"),
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
const nameCollator = new Intl.Collator("es", { sensitivity: "base", numeric: true });

async function loadMarket() {
  const apiBaseUrl = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
  const endpoints = apiBaseUrl
    ? [
        { url: `${apiBaseUrl}/v1/market-items`, source: "Backend Google Cloud" },
        { url: "./data/market-items.json", source: "respaldo estático" },
      ]
    : [{ url: "./data/market-items.json", source: "respaldo estático" }];
  const errors = [];
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint.url, { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (payload.kind !== "market-items" || !Array.isArray(payload.items)) {
        throw new Error("formato inesperado");
      }
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

function hydrateMeta() {
  const { meta, summary } = state.data;
  document.querySelector("#scope-label").textContent = meta.scope;
  document.querySelector("#updated-label").textContent = `Mercado ${relativeTime(meta.marketCollectedAt)}`;
  document.querySelector("#metric-gathering").textContent = integerFormat.format(summary.gatheringItems);
  document.querySelector("#metric-crafting").textContent = integerFormat.format(summary.craftingItems);
  document.querySelector("#metric-fresh").textContent = integerFormat.format(summary.freshRows);
  document.querySelector("#fresh-window").textContent = `uploads de Cactuar en ${meta.freshnessHours} h`;
  document.querySelector("#footer-source").textContent = `${meta.source} · ${meta.scope} · ${state.dataSource}`;
}

function modeItems() {
  return state.data.items.filter((item) =>
    state.mode === "gathering" ? item.gatherable : item.craftable,
  );
}

function renderCategoryOptions() {
  const categories = new Set(
    modeItems().map(categoryName).filter(Boolean),
  );
  const options = [...categories].sort(nameCollator.compare);
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
    if (state.category && categoryName(item) !== state.category) return false;
    if (!query) return true;
    return normalize([
      item.name,
      item.itemId,
      item.craftTypeName,
      gatheringLabel(item.gatheringType),
      item.searchCategoryName,
      item.uiCategoryName,
      item.quality,
    ].join(" ")).includes(query);
  });
  state.filtered.sort(sorter(state.sort));
  renderRows();
}

function sorter(sort) {
  const descending = (field) => (a, b) =>
    numberOrLow(b[field]) - numberOrLow(a[field]) || nameCollator.compare(a.name, b.name);
  if (sort === "revenue") return descending("estimatedDailyRevenue");
  if (sort === "price") return descending("averageSalePrice");
  if (sort === "name") return (a, b) => nameCollator.compare(a.name, b.name);
  return descending("dailySaleVelocity");
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
  renderPagination(totalPages);
}

function createRow(item) {
  const row = document.createElement("tr");
  row.tabIndex = 0;
  row.innerHTML = `
    <td data-label="Item"><div class="entity"><strong>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</strong><small>Item ${item.itemId}</small></div></td>
    <td data-label="Origen / oficio"><div class="entity"><strong>${escapeHtml(originLabel(item))}</strong><small>${state.mode === "gathering" ? "Gathering" : "Crafting"}</small></div></td>
    <td data-label="Categoría">${escapeHtml(categoryName(item) || "Sin categoría")}</td>
    <td data-label="Precio medio" class="numeric">${gil(item.averageSalePrice)}</td>
    <td data-label="Ventas / día" class="numeric">${velocity(item.dailySaleVelocity)}</td>
    <td data-label="Gil / día" class="numeric net-cell">${gil(item.estimatedDailyRevenue)}</td>
    <td data-label="Estado"><span class="status-pill ${item.status.toLowerCase()}">${item.status === "FRESH" ? "FRESCO" : "ANTIGUO"}</span></td>
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
  const productionSources = [
    item.gatherable ? gatheringLabel(item.gatheringType) : null,
    item.craftable ? item.craftTypeName || "Crafting" : null,
  ].filter(Boolean);
  elements.dialogContent.innerHTML = `
    <div class="detail-body">
      <p class="eyebrow">ITEM ${item.itemId} · ${escapeHtml(item.quality)}</p>
      <h3>${escapeHtml(item.name)}${item.quality === "HQ" ? " · HQ" : ""}</h3>
      <p>${escapeHtml(categoryName(item) || "Sin categoría")}</p>
      <div class="detail-route">
        <span>SE OBTIENE POR</span>
        <strong>${escapeHtml(productionSources.join(" · "))}</strong>
      </div>
      <div class="detail-stats">
        <div><small>Listing mínimo</small><strong>${gil(item.minListingPrice)}</strong></div>
        <div><small>Precio medio vendido</small><strong>${gil(item.averageSalePrice)}</strong></div>
        <div><small>Ventas / día</small><strong>${velocity(item.dailySaleVelocity)}</strong></div>
        <div><small>Gil / día estimado</small><strong>${gil(item.estimatedDailyRevenue)}</strong></div>
        <div><small>Mediana de listings</small><strong>${gil(item.medianListingPrice)}</strong></div>
        <div><small>Último upload en Cactuar</small><strong>${formatDate(item.latestUploadAt)}</strong></div>
      </div>
    </div>
  `;
  elements.dialog.showModal();
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

function categoryName(item) {
  return item.searchCategoryName || item.uiCategoryName || "";
}

function originLabel(item) {
  return state.mode === "gathering"
    ? gatheringLabel(item.gatheringType)
    : item.craftTypeName || "Crafting";
}

function gatheringLabel(value) {
  if (value === "FISHING") return "Fishing";
  if (value === "MINER_BOTANIST") return "Miner / Botanist";
  return "Gathering";
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

function formatDate(value) {
  if (!value) return "Sin dato";
  return new Intl.DateTimeFormat("es-CL", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;",
  })[character]);
}

elements.gatheringTab.addEventListener("click", () => setMode("gathering"));
elements.craftingTab.addEventListener("click", () => setMode("crafting"));
elements.search.addEventListener("input", (event) => {
  state.search = event.target.value;
  state.page = 1;
  applyFilters();
});
elements.sort.addEventListener("change", (event) => {
  state.sort = event.target.value;
  state.page = 1;
  applyFilters();
});
elements.category.addEventListener("change", (event) => {
  state.category = event.target.value;
  state.page = 1;
  applyFilters();
});
elements.fresh.addEventListener("change", (event) => {
  state.freshOnly = event.target.checked;
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

loadMarket();
