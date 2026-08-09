const state = {
  data: null,
  filtered: [],
  search: "",
  currencyId: null,
  sort: "net",
  freshOnly: true,
  visible: 40,
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
  loadMore: document.querySelector("#load-more"),
  dialog: document.querySelector("#detail-dialog"),
  dialogContent: document.querySelector("#dialog-content"),
};

const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const gilFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });

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
      const response = await fetch(endpoint.url, { cache: "no-store" });
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
  const popular = [...state.data.currencies]
    .sort((a, b) => b.freshCount - a.freshCount || b.conversionCount - a.conversionCount)
    .slice(0, 8);
  const all = document.createElement("button");
  all.className = "chip active";
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
    chip.title = `${currency.conversionCount} conversiones`;
    chip.addEventListener("click", () => selectCurrency(currency.itemId));
    elements.chips.append(chip);
  }
}

function selectCurrency(currencyId) {
  state.currencyId = currencyId;
  state.visible = 40;
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.classList.toggle(
      "active",
      currencyId === null ? !chip.dataset.currencyId : Number(chip.dataset.currencyId) === currencyId,
    );
  });
  applyFilters();
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
  const visibleRows = state.filtered.slice(0, state.visible);
  const fragment = document.createDocumentFragment();
  visibleRows.forEach((item) => fragment.append(createRow(item)));
  elements.rows.append(fragment);
  elements.count.textContent = `${integerFormat.format(state.filtered.length)} conversiones encontradas`;
  elements.empty.hidden = state.filtered.length !== 0;
  elements.loadMore.hidden = state.visible >= state.filtered.length;
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
        <div><small>Venta observada</small><strong>${gil(item.marketUnitPrice)}</strong></div>
        <div><small>Gil neto / moneda</small><strong>${gil(item.netGilPerCurrency)}</strong></div>
        <div><small>Ventas / día</small><strong>${velocity(item.dailySaleVelocity)}</strong></div>
        <div><small>Último upload</small><strong>${formatDate(item.latestUploadAt)}</strong></div>
      </div>
    </div>`;
  elements.dialog.showModal();
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
  state.visible = 40;
  applyFilters();
});
elements.sort.addEventListener("change", (event) => { state.sort = event.target.value; applyFilters(); });
elements.fresh.addEventListener("change", (event) => { state.freshOnly = event.target.checked; applyFilters(); });
elements.loadMore.addEventListener("click", () => { state.visible += 40; renderRows(); });
document.querySelector("#dialog-close").addEventListener("click", () => elements.dialog.close());
elements.dialog.addEventListener("click", (event) => { if (event.target === elements.dialog) elements.dialog.close(); });
document.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    elements.search.focus();
  }
});

loadDashboard();
