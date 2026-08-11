const state = {
  data: null,
  history: null,
  historyPromise: null,
  filtered: [],
  search: "",
  currencyId: null,
  sort: "net",
  sortDirection: "desc",
  freshOnly: true,
  page: 1,
  pageSize: 50,
  advice: null,
  budget: 1000,
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
  freshLabel: document.querySelector("#fresh-toggle-label"),
  advisor: document.querySelector("#conversion-advisor"),
  advisorContent: document.querySelector("#advisor-content"),
  advisorBudgetControl: document.querySelector("#advisor-budget-control"),
  advisorBudget: document.querySelector("#advisor-budget"),
  scoreSortOption: document.querySelector("#score-sort-option"),
};

const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
const gilFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
const highlightedCurrencyIds = [20, 21, 22, 28, 48, 47, 26807, 26533, 41784, 41785, 28063];

async function loadDashboard() {
  try {
    state.data = await GilAuth.data("/v1/dashboard");
    state.advice = GilConversionAdvisor.buildIndex(state.data.conversions);
    state.dataSource = "cloud-authenticated";
    hydrateMeta();
    renderChips();
    applyFilters();
  } catch (error) {
    elements.count.textContent = "No pudimos cargar los datos";
    elements.empty.hidden = false;
    elements.empty.querySelector("h3").textContent = "Dashboard sin datos";
    elements.empty.querySelector("p").textContent = error.message;
  }
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
  const selectingSpecificCurrency = currencyId !== null && state.currencyId !== currencyId;
  state.currencyId = currencyId;
  if (selectingSpecificCurrency) {
    state.sort = "score";
    state.sortDirection = "desc";
    elements.sort.value = "score";
  } else if (currencyId === null && state.sort === "score") {
    state.sort = "net";
    state.sortDirection = "desc";
    elements.sort.value = "net";
  }
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
  const selectedHasNoFreshPrice = selected && !selected.freshCount && !selected.valuedCount;
  elements.freshLabel.textContent = selectedHasNoFreshPrice ? "Canjes sin precio" : "Sólo frescos";
  elements.fresh.disabled = Boolean(selectedHasNoFreshPrice);
  elements.scoreSortOption.disabled = state.currencyId === null;
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
    (b.bestNetGil || b.bestExchangeGil || 0) - (a.bestNetGil || a.bestExchangeGil || 0)
      || a.name.localeCompare(b.name, "es");
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
  const internal = currency.internalCount || 0;
  const unpriced = currency.unpricedCount || 0;
  detail.textContent = currency.valuedCount
    ? `Item ${currency.itemId} · ${currency.freshCount}/${currency.valuedCount} frescas${currency.bundleCount ? ` · ${currency.bundleCount} combinadas` : ""}`
    : internal
      ? `Item ${currency.itemId} · ${internal} usos internos`
      : `Item ${currency.itemId} · ${unpriced || currency.conversionCount} canjes sin precio`;
  identity.append(name, detail);
  const stats = document.createElement("span");
  stats.className = "currency-option-stats";
  const best = document.createElement("strong");
  const sales = document.createElement("small");
  best.textContent = currency.bestNetGil !== null && currency.bestNetGil !== undefined
    ? gil(currency.bestNetGil)
    : currency.bestExchangeGil !== null && currency.bestExchangeGil !== undefined
      ? `${gil(currency.bestExchangeGil)} / canje`
      : (internal ? "Uso interno" : "Sin precio");
  sales.textContent = currency.valuedCount
    ? `${velocity(liquidity.get(currency.itemId))} combinadas`
    : "Sin salida en gil";
  stats.append(best, sales);
  const visual = document.createElement("span");
  visual.className = "entity-with-icon";
  visual.append(GilItemIcons.element(currency.iconId, { fallback: "coin", tone: "gold" }), identity);
  button.append(visual, stats);
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
  const selected = state.data.currencies.find((currency) => currency.itemId === state.currencyId);
  const selectedHasNoFreshPrice = selected && !selected.freshCount && !selected.valuedCount;
  state.filtered = state.data.conversions.filter((item) => {
    if (state.currencyId !== null && item.currencyItemId !== state.currencyId) return false;
    if (state.freshOnly && !selectedHasNoFreshPrice && item.status !== "FRESH") return false;
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
  updateSortHeaders();
  renderAdvisor();
  renderRows();
}

function renderAdvisor() {
  const currency = state.data.currencies.find((item) => item.itemId === state.currencyId);
  const advice = state.advice?.currencies.get(state.currencyId);
  elements.advisorBudgetControl.hidden = !currency;
  elements.advisor.classList.toggle("empty", !currency || !advice);
  if (!currency) {
    elements.advisorContent.innerHTML = '<div class="advisor-empty"><strong>Selecciona una moneda</strong><span>Te mostraremos la compra con mejor equilibrio y sus alternativas.</span></div>';
    return;
  }
  if (!advice) {
    elements.advisorContent.innerHTML = `<div class="advisor-empty"><strong>Sin recomendación defendible para ${escapeHtml(currency.name)}</strong><span>No hay una conversión fresca con precio y retorno calculable. Conviene esperar datos antes de gastar.</span></div>`;
    return;
  }

  const selection = GilConversionAdvisor.selectForBudget(advice, state.budget);
  if (!selection) {
    const minimum = Math.min(...advice.ranked.map((candidate) => candidate.item.currencyQuantity));
    elements.advisorContent.innerHTML = `<div class="advisor-empty"><strong>Aún no alcanza para un canje</strong><span>La opción fresca más barata cuesta ${integerFormat.format(minimum)} ${escapeHtml(currency.name)}.</span></div>`;
    return;
  }
  const primary = selection.best;
  const alternatives = [selection.returnLeader, selection.liquidityLeader]
    .filter((candidate, index, list) => candidate && candidate !== primary && list.indexOf(candidate) === index);
  elements.advisorContent.innerHTML = `
    ${advisorCard(primary, selection.unverified ? "Opción tentativa · sin velocidad" : "Mejor equilibrio", true)}
    <div class="advisor-alternatives">
      ${alternatives.map((candidate) => advisorCard(
        candidate,
        candidate === selection.returnLeader ? "Mayor retorno" : "Alternativa líquida",
        false,
      )).join("") || '<p class="advisor-single">La mejor opción también lidera las métricas disponibles.</p>'}
    </div>`;
}

function advisorCard(candidate, label, primary) {
  const item = candidate.item;
  const plan = GilConversionAdvisor.purchasePlan(item, state.budget);
  const noVelocity = item.dailySaleVelocity === null || item.dailySaleVelocity === undefined;
  const batch = plan.pilotUnits > 0 && plan.pilotUnits < plan.units
    ? `Publica primero ${integerFormat.format(plan.pilotUnits)} de ${integerFormat.format(plan.units)} unidades para no saturar.`
    : plan.units > 0
      ? `El lote calculado cabe dentro del ritmo observado.`
      : `Necesitas al menos ${integerFormat.format(item.currencyQuantity)} monedas para este canje.`;
  const reason = noVelocity
    ? `Retorno alto, pero sin velocidad local: prueba una sola unidad antes de comprometer más.`
    : `${gil(item.netGilPerCurrency)} por moneda y ${velocity(item.dailySaleVelocity)} observadas. ${batch}`;
  return `<article class="advisor-card ${primary ? "primary" : ""}">
    <div class="advisor-card-top"><span>${escapeHtml(label)}</span><b>${candidate.score}/100</b></div>
    <div class="advisor-item">${GilItemIcons.markup(item.rewardIconId, { fallback: "item" })}<div><strong>${escapeHtml(item.rewardName)}</strong><small>${integerFormat.format(item.currencyQuantity)} ${escapeHtml(item.currencyName)} por canje</small></div></div>
    <div class="advisor-plan"><div><small>Comprar</small><strong>${integerFormat.format(plan.units)} u.</strong></div><div><small>Gastar</small><strong>${integerFormat.format(plan.spent)}</strong></div><div><small>Gil neto estimado</small><strong>${gil(plan.netGil)}</strong></div></div>
    <p>${escapeHtml(reason)}</p>
    ${plan.remaining ? `<small class="advisor-remainder">Quedan ${integerFormat.format(plan.remaining)} monedas sin usar.</small>` : ""}
  </article>`;
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
  GilIntelligence.hydrateSparklines(elements.rows);
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
  fillEntity(row.querySelector(".currency-entity"), item.currencyName, `Item ${item.currencyItemId}`, "coin", "gold", item.currencyIconId);
  fillEntity(
    row.querySelector(".reward-entity"),
    `${item.rewardName}${item.rewardIsHq ? " · HQ" : ""}`,
    item.shopName,
    "item",
    "",
    item.rewardIconId,
  );
  row.querySelector(".reward-entity").lastElementChild.append(GilIntelligence.qualityElement(item));
  const watchButton = document.createElement("button");
  const watchKey = conversionWatchKey(item);
  watchButton.type = "button";
  watchButton.className = `watch-button ${GilWatchlist.has(watchKey) ? "active" : ""}`;
  watchButton.textContent = "★";
  watchButton.setAttribute("aria-label", `${GilWatchlist.has(watchKey) ? "Quitar" : "Vigilar"} ${item.rewardName}`);
  watchButton.addEventListener("click", (event) => {
    event.stopPropagation();
    GilWatchlist.toggle(watchKey, { module: "conversion", itemId: item.rewardItemId,
      quality: item.rewardIsHq ? "HQ" : "NQ", name: item.rewardName,
      currencyItemId: item.currencyItemId, currencyName: item.currencyName });
    renderRows();
  });
  row.querySelector(".reward-entity").prepend(watchButton);
  const costCell = row.querySelector(".cost-cell");
  costCell.textContent = item.isMultiCost
    ? `${integerFormat.format(item.costComponents.length)} monedas`
    : `${integerFormat.format(item.currencyQuantity)}×`;
  if (item.isMultiCost) costCell.title = costRoute(item);
  row.querySelector(".price-cell").textContent = gil(item.marketUnitPrice);
  row.querySelector(".net-cell").textContent = item.isMultiCost
    ? `${gil(item.netGilPerExchange)} / canje`
    : gil(item.netGilPerCurrency);
  const velocityCell = row.querySelector(".velocity-cell");
  velocityCell.textContent = velocity(item.dailySaleVelocity);
  if (item.status === "NOT_TRADEABLE") {
    velocityCell.textContent = "No aplica";
    velocityCell.classList.add("missing-data");
    velocityCell.title = "La recompensa no se puede vender en el Market Board.";
  } else {
    const spark = document.createElement("div");
    spark.className = "tiny-sparkline";
    spark.dataset.sparkKey = `${item.rewardItemId}:${item.rewardIsHq ? "HQ" : "NQ"}`;
    spark.innerHTML = '<span class="spark-empty">Cargando…</span>';
    velocityCell.append(spark);
  }
  if (item.status !== "NOT_TRADEABLE" && (item.dailySaleVelocity === null || item.dailySaleVelocity === undefined)) {
    velocityCell.classList.add("missing-data");
    velocityCell.title = "Universalis no publicó velocidad diaria para Cactuar. No significa cero ventas.";
  }
  const pill = row.querySelector(".status-pill");
  const decision = decisionMeta(item);
  pill.textContent = decision.label;
  pill.title = decision.detail;
  pill.classList.add(decision.className);
  row.addEventListener("click", () => showDetail(item));
  row.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      showDetail(item);
    }
  });
  return row;
}

function fillEntity(container, name, detail, icon = "item", tone = "", iconId = null) {
  const strong = document.createElement("strong");
  const small = document.createElement("small");
  const copy = document.createElement("span");
  strong.textContent = name;
  strong.title = name;
  small.textContent = detail;
  copy.append(strong, small);
  container.classList.add("entity-with-icon");
  container.append(createItemIcon(icon, tone, iconId), copy);
}

function createItemIcon(kind, tone = "", iconId = null) {
  return GilItemIcons.element(iconId, { fallback: kind, tone });
}

function showDetail(item) {
  const internal = item.status === "NOT_TRADEABLE";
  const status = statusMeta(item.status, item.isMultiCost);
  elements.dialogContent.innerHTML = `
    <div class="detail-body">
      <p class="eyebrow">CONVERSIÓN DIRECTA · ${escapeHtml(state.data.meta.scope)}</p>
      <div class="detail-item-title">${GilItemIcons.markup(item.rewardIconId, { fallback: "item" })}<div><h3>${escapeHtml(item.rewardName)}${item.rewardIsHq ? " · HQ" : ""}</h3><p>${escapeHtml(item.shopName)} · Shop ${item.shopId}</p>${GilIntelligence.qualityMarkup(item)}</div></div>
      <div class="detail-route">
        <strong>${escapeHtml(costRoute(item))}</strong>
        <span>SE CONVIERTE EN</span>
        <strong>${integerFormat.format(item.rewardQuantity)} × ${escapeHtml(item.rewardName)}</strong>
      </div>
      <div class="detail-stats">
        <div><small>Listing mínimo actual</small><strong>${internal ? "No comerciable" : gil(item.marketUnitPrice)}</strong></div>
        <div><small>${item.isMultiCost ? "Gil neto / canje completo" : "Gil neto / moneda"}</small><strong>${internal ? "No aplica" : gil(item.isMultiCost ? item.netGilPerExchange : item.netGilPerCurrency)}</strong></div>
        <div><small>Ventas / día</small><strong>${internal ? "No aplica" : velocity(item.dailySaleVelocity)}</strong></div>
        <div><small>Último upload</small><strong>${formatDate(item.latestUploadAt)}</strong></div>
      </div>
      ${locationMarkup(item)}
      ${internal ? internalUseMarkup(status) : depthMarkup(item.listingDepth)}
      ${internal || item.isMultiCost ? "" : `<section class="history-panel">
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
      </section>`}
    </div>`;
  elements.dialog.showModal();
  GilIntelligence.attachDetailButton(elements.dialogContent, { itemId: item.rewardItemId,
    quality: item.rewardIsHq ? "HQ" : "NQ", name: item.rewardName, iconId: item.rewardIconId,
    modules: ["conversion"], aliases: [item.currencyName] });
  bindLocationPanel(item);
  if (!internal && !item.isMultiCost) renderHistory(item);
}

function locationMarkup(item, selectedIndex = 0) {
  const locations = Array.isArray(item.locations) ? item.locations : [];
  if (!locations.length) {
    return `<section class="location-panel unavailable">
      <div class="location-heading"><div><small>DÓNDE CANJEAR</small><strong>Ubicación no disponible</strong></div></div>
      <p>Esta tienda no tiene una relación confiable con un NPC y un mapa en los datos del juego. Preferimos indicarlo antes que mostrar una ubicación inventada.</p>
    </section>`;
  }
  const safeIndex = Math.min(Math.max(selectedIndex, 0), locations.length - 1);
  const location = locations[safeIndex];
  const npcName = location.npcName || "NPC sin nombre";
  const placeName = location.placeName || location.regionName || "Zona sin nombre";
  const region = location.regionName && location.regionName !== placeName
    ? ` · ${escapeHtml(location.regionName)}`
    : "";
  const selector = locations.length > 1
    ? `<div class="location-selector" aria-label="Ubicaciones disponibles">${locations.map((entry, index) => `<button type="button" data-location-index="${index}" class="${index === safeIndex ? "selected" : ""}">${escapeHtml(locationOptionLabel(entry, index))}</button>`).join("")}</div>`
    : "";
  const hasMap = Boolean(location.mapAssetId);
  const markerX = Math.min(Math.max(Number(location.markerLeftPercent), 0), 100);
  const markerY = Math.min(Math.max(Number(location.markerTopPercent), 0), 100);
  const map = hasMap
    ? `<div class="xiv-map">
        <img src="${mapAssetUrl(location.mapAssetId)}" alt="Mapa de ${escapeHtml(placeName)}" loading="lazy" />
        <svg class="xiv-map-marker" viewBox="0 0 100 100" role="img" aria-label="Posición del NPC">
          <g transform="translate(${markerX} ${markerY})">
            <circle r="2.2"></circle>
            <path d="M -0.8 -0.8 L 0.8 0.8 M 0.8 -0.8 L -0.8 0.8"></path>
          </g>
        </svg>
        <div class="map-error" hidden>El mapa no pudo cargarse ahora.</div>
      </div>`
    : `<div class="map-error standalone">Mapa no disponible para esta ubicación.</div>`;
  return `<section class="location-panel" data-selected-location="${safeIndex}">
    <div class="location-heading"><div><small>DÓNDE CANJEAR</small><strong>${escapeHtml(npcName)}</strong></div><span>X ${decimalFormat.format(location.mapX)} · Y ${decimalFormat.format(location.mapY)}</span></div>
    ${selector}
    ${map}
    <div class="location-meta"><strong>${escapeHtml(placeName)}${region}</strong><span>NPC ${integerFormat.format(location.npcId)} · mapa ${integerFormat.format(location.mapId)}</span></div>
    <p>La X marca la posición registrada por el cliente de FFXIV. Si el NPC atiende varias tiendas, todas comparten esta ubicación.</p>
  </section>`;
}

function locationOptionLabel(location, index) {
  const place = location.placeName || location.regionName;
  if (place && location.npcName) return `${place} · ${location.npcName}`;
  return place || location.npcName || `Ubicación ${index + 1}`;
}

function mapAssetUrl(assetId) {
  const safePath = String(assetId).split("/").map(encodeURIComponent).join("/");
  return `https://v2.xivapi.com/api/asset/map/${safePath}`;
}

function bindLocationPanel(item) {
  const panel = elements.dialogContent.querySelector(".location-panel:not(.unavailable)");
  if (!panel) return;
  panel.querySelectorAll("[data-location-index]").forEach((button) => {
    button.addEventListener("click", () => {
      panel.outerHTML = locationMarkup(item, Number(button.dataset.locationIndex));
      bindLocationPanel(item);
    });
  });
  const image = panel.querySelector(".xiv-map img");
  image?.addEventListener("error", () => {
    image.hidden = true;
    panel.querySelector(".xiv-map-marker")?.setAttribute("hidden", "");
    const error = panel.querySelector(".map-error");
    if (error) error.hidden = false;
  });
}

function statusMeta(value, isMultiCost = false) {
  const status = ({
    FRESH: { label: "FRESCO", className: "fresh", detail: "Precio dentro de la ventana de frescura." },
    STALE: { label: "ANTIGUO", className: "stale", detail: "El último precio está fuera de la ventana de frescura." },
    NO_MARKET_DATA: { label: "SIN PRECIO", className: "no-market-data", detail: "La recompensa es comerciable, pero no hay precio observable en Cactuar." },
    NOT_TRADEABLE: { label: "USO INTERNO", className: "not-tradeable", detail: "La recompensa no se puede vender en el Market Board." },
  })[value] || { label: String(value || "DESCONOCIDO"), className: "stale", detail: "Estado no reconocido." };
  return isMultiCost
    ? { ...status, label: `COMBINADO · ${status.label}`, detail: `Requiere varias monedas a la vez. ${status.detail}` }
    : status;
}

function decisionMeta(item) {
  const candidate = state.advice?.rows.get(GilConversionAdvisor.conversionKey(item));
  if (!candidate?.role) return statusMeta(item.status, item.isMultiCost);
  return ({
    BEST: { label: `MEJOR · ${candidate.score}`, className: "decision-best", detail: "Mejor equilibrio relativo entre retorno, liquidez y calidad de datos para esta moneda." },
    RETURN: { label: "MÁS GIL", className: "decision-return", detail: "Mayor gil por moneda, aunque puede vender más lento que la recomendación principal." },
    LIQUID: { label: "SALIDA RÁPIDA", className: "decision-liquid", detail: "Alternativa con velocidad alta y un retorno mínimo razonable frente a las demás conversiones de esta moneda." },
    SPECULATIVE: { label: "RIESGO", className: "decision-risk", detail: "Retorno aparente alto, pero sin velocidad local para validar la salida." },
  })[candidate.role];
}

function costRoute(item) {
  const components = item.costComponents?.length
    ? item.costComponents
    : [{ quantity: item.currencyQuantity, name: item.currencyName }];
  return components.map((component) => `${integerFormat.format(component.quantity)} × ${component.name}`).join(" + ");
}

function internalUseMarkup(status) {
  return `<section class="depth-panel unverified"><div class="depth-heading"><span class="item-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M12 3v18M5 8h14M5 16h14"/></svg></span><div><small>CATÁLOGO DE CANJE</small><strong>${escapeHtml(status.label)}</strong></div></div><p>${escapeHtml(status.detail)} Se muestra para que conozcas en qué gastar la moneda, pero no se calcula rentabilidad, profundidad ni velocidad de venta.</p></section>`;
}

function depthMarkup(depth) {
  if (!depth) {
    return `<section class="depth-panel unverified"><div class="depth-heading"><span class="item-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 18h16M6 14h12M8 10h8M10 6h4"/></svg></span><div><small>PROFUNDIDAD</small><strong>Aún no verificada</strong></div></div><p>Esta conversión no entró en la muestra detallada. El listing mínimo sigue siendo válido, pero confirma cantidades y competidores en el juego.</p></section>`;
  }
  const pressureLabel = ({ HIGH: "Competencia alta", MEDIUM: "Competencia media", LOW: "Competencia baja", UNKNOWN: "Sin velocidad mundial" })[depth.pressure] || depth.pressure;
  const supply = depth.nearFloorSupplyDays === null || depth.nearFloorSupplyDays === undefined
    ? "No calculable sin ventas/día de Cactuar"
    : `${decimalFormat.format(depth.nearFloorSupplyDays)} días de ventas`;
  return `<section class="depth-panel ${String(depth.pressure).toLowerCase()}">
    <div class="depth-heading"><span class="item-icon" aria-hidden="true"><svg viewBox="0 0 24 24"><path d="M4 18h16M6 14h12M8 10h8M10 6h4"/></svg></span><div><small>PROFUNDIDAD · 20 LISTINGS</small><strong>${escapeHtml(pressureLabel)}</strong></div><b>${integerFormat.format(depth.nearFloorUnits)} u.</b></div>
    <div class="depth-stats"><div><small>Unidades hasta +10%</small><strong>${integerFormat.format(depth.nearFloorUnits)}</strong></div><div><small>Cobertura al ritmo actual</small><strong>${escapeHtml(supply)}</strong></div><div><small>Precio medio primeras ${integerFormat.format(depth.weightedUnitCount)} u.</small><strong>${gil(depth.weightedPriceForUnits)}</strong></div><div><small>Total observado</small><strong>${integerFormat.format(depth.unitsObserved)} u.</strong></div></div>
    <div class="depth-tiers">${depth.tiers.map((tier) => `<span>${integerFormat.format(tier.quantity)} × ${gil(tier.pricePerUnit)}</span>`).join("")}</div>
    <p>Mide oferta competidora cerca del piso. Mucha oferta frente a las ventas diarias aumenta el riesgo de undercut; no garantiza compradores.</p>
  </section>`;
}

async function loadHistory() {
  if (state.history) return state.history;
  if (state.historyPromise) return state.historyPromise;
  state.historyPromise = GilAuth.data("/v1/history")
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

function conversionWatchKey(item) { return `conversion:${conversionKey(item)}`; }

function shortDate(value) {
  return new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "short" }).format(new Date(value));
}

function sorter(mode) {
  let compare;
  if (mode === "score") compare = (a, b) => adviceScore(a) - adviceScore(b);
  else if (mode === "velocity") compare = (a, b) => numericValue(a.dailySaleVelocity) - numericValue(b.dailySaleVelocity);
  else if (mode === "price") compare = (a, b) => numericValue(a.marketUnitPrice) - numericValue(b.marketUnitPrice);
  else if (mode === "cost") compare = (a, b) => numericValue(a.currencyQuantity) - numericValue(b.currencyQuantity);
  else if (mode === "currency") compare = (a, b) => a.currencyName.localeCompare(b.currencyName, "es");
  else if (mode === "reward") compare = (a, b) => a.rewardName.localeCompare(b.rewardName, "es");
  else compare = (a, b) => numericValue(a.netGilPerCurrency) - numericValue(b.netGilPerCurrency);
  return state.sortDirection === "asc"
    ? (a, b) => compare(a, b) || a.rewardName.localeCompare(b.rewardName, "es")
    : (a, b) => -compare(a, b) || a.rewardName.localeCompare(b.rewardName, "es");
}

function adviceScore(item) {
  return state.advice?.rows.get(GilConversionAdvisor.conversionKey(item))?.score ?? -Infinity;
}

function numericValue(value) { return Number.isFinite(value) ? value : -Infinity; }
function defaultSortDirection(mode) { return ["currency", "reward", "cost"].includes(mode) ? "asc" : "desc"; }
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

function normalize(value) {
  return String(value || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
}

function gil(value) {
  if (value === null || value === undefined) return "—";
  return `${gilFormat.format(value)} gil`;
}

function velocity(value) {
  if (value === null || value === undefined) return "Sin datos Cactuar";
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
elements.sort.addEventListener("change", (event) => setSort(event.target.value));
elements.fresh.addEventListener("change", (event) => { state.freshOnly = event.target.checked; state.page = 1; applyFilters(); });
elements.pagePrevious.addEventListener("click", () => goToPage(state.page - 1));
elements.pageNext.addEventListener("click", () => goToPage(state.page + 1));
elements.pageSize.addEventListener("change", (event) => {
  state.pageSize = Number(event.target.value);
  state.page = 1;
  renderRows();
});
elements.advisorBudget.addEventListener("input", (event) => {
  const value = Math.max(1, Math.floor(Number(event.target.value) || 1));
  state.budget = value;
  renderAdvisor();
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

bindSortableHeaders();
GilWatchlist.subscribe(() => {
  if (state.data) renderRows();
});
loadDashboard();
