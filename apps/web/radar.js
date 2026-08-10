(function initializePersonalRadar() {
  const state = {
    data: null, entries: [], visible: [], editingKey: null,
    search: "", status: "", module: "", sort: "alert",
  };
  const elements = {
    grid: document.querySelector("#radar-grid"), empty: document.querySelector("#radar-empty"),
    count: document.querySelector("#radar-result-count"), search: document.querySelector("#radar-search"),
    status: document.querySelector("#radar-status"), module: document.querySelector("#radar-module"),
    sort: document.querySelector("#radar-sort"), alerts: document.querySelector("#radar-alert-list"),
    alertCopy: document.querySelector("#radar-alert-copy"), total: document.querySelector("#radar-total"),
    alertCount: document.querySelector("#radar-alerts"), capital: document.querySelector("#radar-capital"),
    history: document.querySelector("#radar-history"), editor: document.querySelector("#radar-editor"),
    form: document.querySelector("#radar-form"), heading: document.querySelector("#radar-editor-heading"),
    close: document.querySelector("#radar-editor-close"), buy: document.querySelector("#radar-buy-target"),
    sell: document.querySelector("#radar-sell-target"), maxCapital: document.querySelector("#radar-max-capital"),
    preferredWorld: document.querySelector("#radar-preferred-world"), worlds: document.querySelector("#radar-worlds"),
    notes: document.querySelector("#radar-notes"), noteCount: document.querySelector("#radar-note-count"),
    alertEnabled: document.querySelector("#radar-alert-enabled"), message: document.querySelector("#radar-form-message"),
    remove: document.querySelector("#radar-remove"), save: document.querySelector("#radar-save"),
  };
  const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
  const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
  const compactFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
  const percentFormat = new Intl.NumberFormat("es-CL", { style: "percent", maximumFractionDigits: 1 });
  const dateFormat = new Intl.DateTimeFormat("es-CL", { day: "2-digit", month: "short", year: "numeric" });
  const collator = new Intl.Collator("es", { sensitivity: "base", numeric: true });
  const MODULES = {
    conversion: { label: "Conversiones", url: "./" }, market: { label: "Mercado", url: "./market.html" },
    opportunity: { label: "Oportunidades", url: "./opportunities.html" },
    projection: { label: "Proyecciones", url: "./projections.html" },
    snipe: { label: "Snipeos", url: "./snipes.html" },
  };
  const STATUSES = {
    SELL: { label: "Salida lista", detail: "El precio de salida alcanzó tu objetivo.", rank: 0 },
    BUY: { label: "Comprar", detail: "El precio de entrada está dentro de tu límite.", rank: 1 },
    COOLING: { label: "Enfriándose", detail: "La demanda o velocidad está perdiendo fuerza.", rank: 2 },
    OUT: { label: "Fuera de precio", detail: "El precio actual supera tu máximo de compra.", rank: 3 },
    WATCH: { label: "Vigilar", detail: "Todavía no se cumple una regla de entrada o salida.", rank: 4 },
    NO_DATA: { label: "Sin datos", detail: "El favorito ya no aparece en el snapshot actual.", rank: 5 },
  };

  async function loadRadar() {
    try {
      await GilWatchlist.reload();
      const [dashboard, market, history, opportunities, signals] = await Promise.all([
        GilAuth.data("/v1/dashboard"), GilAuth.data("/v1/market-items"),
        GilAuth.data("/v1/market-history"), GilAuth.data("/v1/opportunities"),
        GilAuth.data("/v1/signals"),
      ]);
      state.data = buildContext({ dashboard, market, history, opportunities, signals });
      hydrateWorlds(opportunities.opportunities || []);
      rebuild();
      document.querySelector("#updated-label").textContent = market.meta?.marketCollectedAt
        ? `Mercado ${relativeTime(market.meta.marketCollectedAt)}` : "Sin snapshot reciente";
    } catch (error) {
      elements.count.textContent = "No pudimos cargar tu radar";
      elements.empty.hidden = false;
      elements.empty.querySelector("h3").textContent = "Radar no disponible";
      elements.empty.querySelector("p").textContent = error.message;
    }
  }

  function buildContext({ dashboard, market, history, opportunities, signals }) {
    const marketByItem = new Map((market.items || []).map((item) => [`${item.itemId}:${item.quality}`, item]));
    const historyByItem = new Map((history.series || []).map((series) => [`${series.itemId}:${series.quality}`, series]));
    const routesByKey = new Map();
    const routesByItem = new Map();
    (opportunities.opportunities || []).forEach((item) => {
      const suffix = `${item.itemId}:${item.quality}:${item.sourceWorldId}`;
      routesByKey.set(`opportunity:${suffix}`, item);
      routesByKey.set(`snipe:${suffix}`, item);
      const itemKey = `${item.itemId}:${item.quality}`;
      routesByItem.set(itemKey, [...(routesByItem.get(itemKey) || []), item]);
    });
    const conversionsByKey = new Map((dashboard.conversions || []).map((item) => [conversionKey(item), item]));
    const signalsByKey = new Map((signals.signals || []).map((signal) => [signal.key, signal]));
    return { dashboard, market, history, opportunities, signals, marketByItem, historyByItem, routesByKey, routesByItem, conversionsByKey, signalsByKey };
  }

  function rebuild() {
    if (!state.data) return;
    state.entries = GilWatchlist.entries().map(resolveFavorite);
    applyFilters();
    renderSummary();
    renderAlerts();
  }

  function resolveFavorite(favorite) {
    const module = favorite.module || favorite.key.split(":", 1)[0];
    const itemKey = `${favorite.itemId}:${favorite.quality || "NQ"}`;
    const market = state.data.marketByItem.get(itemKey) || null;
    const candidates = state.data.routesByItem.get(itemKey) || [];
    const preferredName = normalize(favorite.preferredWorldName);
    const preferredRoute = preferredName
      ? candidates.find((route) => normalize(route.sourceWorldName) === preferredName) : null;
    const exactRoute = state.data.routesByKey.get(favorite.key) || null;
    const route = preferredRoute || exactRoute
      || (["opportunity", "snipe"].includes(module) ? candidates[0] : null);
    const conversion = state.data.conversionsByKey.get(favorite.key) || null;
    const signal = state.data.signalsByKey.get(favorite.key) || null;
    const currentBuyPrice = positiveNumber(route?.averagePurchasePrice ?? route?.sourcePrice)
      || positiveNumber(market?.minListingPrice) || positiveNumber(conversion?.marketUnitPrice);
    const currentSellPrice = positiveNumber(route?.conservativeSellPrice)
      || positiveNumber(market?.averageSalePrice) || positiveNumber(conversion?.marketUnitPrice);
    const velocity = finite(route?.dailySaleVelocity) ?? finite(market?.dailySaleVelocity)
      ?? finite(conversion?.dailySaleVelocity) ?? finite(signal?.context?.velocity);
    const trend = market?.trend || signal?.context?.trend || {};
    const buyTarget = positiveNumber(favorite.buyTarget ?? favorite.targetPrice);
    const sellTarget = positiveNumber(favorite.sellTarget);
    const maxCapital = positiveNumber(favorite.maxCapital);
    const cooling = trend.signal === "COOLING" || signal?.state === "COOLING" || signal?.state === "STALE";
    let status = "WATCH";
    if (currentBuyPrice === null && currentSellPrice === null) status = "NO_DATA";
    else if (sellTarget && currentSellPrice !== null && currentSellPrice >= sellTarget) status = "SELL";
    else if (cooling) status = "COOLING";
    else if (buyTarget && currentBuyPrice !== null && currentBuyPrice <= buyTarget) status = "BUY";
    else if (buyTarget && currentBuyPrice !== null && currentBuyPrice > buyTarget) status = "OUT";
    const units = maxCapital && currentBuyPrice ? Math.floor(maxCapital / currentBuyPrice) : null;
    const projectedMargin = units && currentSellPrice ? units * (currentSellPrice * .95 - currentBuyPrice) : null;
    const history = mergeHistory(favorite, state.data.historyByItem.get(itemKey), {
      observedAt: state.data.market.meta?.marketCollectedAt,
      currentBuyPrice, currentSellPrice, dailySaleVelocity: velocity,
    });
    return {
      favorite, key: favorite.key, module,
      itemId: favorite.itemId, quality: favorite.quality || "NQ",
      name: favorite.name || market?.name || signal?.title || conversion?.rewardName || `Item ${favorite.itemId}`,
      iconId: favorite.iconId || market?.iconId || route?.iconId || signal?.iconId || conversion?.rewardIconId,
      market, route, conversion, signal, currentBuyPrice, currentSellPrice, velocity, trend,
      buyTarget, sellTarget, maxCapital, units, projectedMargin, history, status,
      sourceWorldName: route?.sourceWorldName || favorite.sourceWorldName || null,
      preferredMismatch: Boolean(preferredName && route && normalize(route.sourceWorldName) !== preferredName),
      alertsEnabled: favorite.alertsEnabled !== false,
    };
  }

  function mergeHistory(favorite, marketSeries, current) {
    const addedAt = new Date(favorite.addedAt || 0).getTime();
    const points = [];
    (marketSeries?.points || []).forEach((point) => {
      if (new Date(point.collectedAt).getTime() + 60000 < addedAt) return;
      points.push({ observedAt: point.collectedAt, currentBuyPrice: point.minListingPrice,
        currentSellPrice: point.averageSalePrice, dailySaleVelocity: point.dailySaleVelocity });
    });
    (favorite.history || []).forEach((point) => points.push(point));
    if (current.observedAt && (current.currentBuyPrice || current.currentSellPrice)) points.push(current);
    const unique = new Map(points.filter((point) => point.observedAt).map((point) => [point.observedAt, point]));
    return [...unique.values()].sort((a, b) => new Date(a.observedAt) - new Date(b.observedAt));
  }

  function applyFilters() {
    const query = normalize(state.search);
    state.visible = state.entries.filter((entry) => {
      if (state.status && entry.status !== state.status) return false;
      if (state.module && entry.module !== state.module) return false;
      return !query || normalize([entry.name, entry.module, entry.favorite.notes,
        entry.favorite.preferredWorldName, entry.sourceWorldName, STATUSES[entry.status].label].join(" ")).includes(query);
    });
    state.visible.sort(sorter(state.sort));
    renderCards();
  }

  function sorter(mode) {
    if (mode === "recent") return (a, b) => new Date(b.favorite.addedAt) - new Date(a.favorite.addedAt);
    if (mode === "capital") return (a, b) => finite(b.maxCapital, -1) - finite(a.maxCapital, -1) || collator.compare(a.name, b.name);
    if (mode === "name") return (a, b) => collator.compare(a.name, b.name);
    return (a, b) => STATUSES[a.status].rank - STATUSES[b.status].rank || collator.compare(a.name, b.name);
  }

  function renderCards() {
    elements.grid.replaceChildren(...state.visible.map(createCard));
    elements.count.textContent = `${integerFormat.format(state.visible.length)} de ${integerFormat.format(state.entries.length)} favoritos`;
    elements.empty.hidden = state.visible.length !== 0;
    if (!state.entries.length) {
      elements.empty.querySelector("h3").textContent = "Tu radar está vacío";
      elements.empty.querySelector("p").textContent = "Usa la estrella de cualquier tabla o señal para agregar tu primer ítem.";
    } else if (!state.visible.length) {
      elements.empty.querySelector("h3").textContent = "No hay coincidencias";
      elements.empty.querySelector("p").textContent = "Prueba otro estado, módulo o término de búsqueda.";
    }
  }

  function createCard(entry) {
    const card = document.createElement("article");
    card.className = `radar-card status-${entry.status.toLowerCase()}`;
    const status = STATUSES[entry.status];
    const history = historyMarkup(entry.history);
    const world = entry.favorite.preferredWorldName || entry.sourceWorldName;
    card.innerHTML = `<div class="radar-card-head">${GilItemIcons.markup(entry.iconId, { fallback: entry.module === "snipe" ? "route" : "signal", tone: entry.module === "snipe" ? "gold" : "" })}<div><small>${escapeHtml(moduleLabel(entry.module))} · ${escapeHtml(entry.quality)}</small><h3>${escapeHtml(entry.name)}</h3>${world ? `<p>${entry.favorite.preferredWorldName ? "World preferido" : "Ruta actual"}: <strong>${escapeHtml(world)}</strong>${entry.preferredMismatch ? " · sin ruta activa" : ""}</p>` : ""}</div><span class="radar-status">${escapeHtml(status.label)}</span></div>
      <p class="radar-status-detail">${escapeHtml(status.detail)}</p>
      <div class="radar-price-grid"><div><small>Entrada actual</small><strong>${gil(entry.currentBuyPrice)}</strong>${entry.buyTarget ? `<span>límite ${gil(entry.buyTarget)}</span>` : "<span>sin límite definido</span>"}</div><div><small>Salida estimada</small><strong>${gil(entry.currentSellPrice)}</strong>${entry.sellTarget ? `<span>objetivo ${gil(entry.sellTarget)}</span>` : "<span>sin objetivo definido</span>"}</div><div><small>Ventas / día</small><strong>${velocity(entry.velocity)}</strong><span>${trendLabel(entry.trend?.signal)}</span></div></div>
      ${history}
      <div class="radar-plan"><div><small>CAPITAL MÁXIMO</small><strong>${entry.maxCapital ? gil(entry.maxCapital) : "Sin asignar"}</strong></div><div><small>TAMAÑO ORIENTATIVO</small><strong>${entry.units !== null ? `${integerFormat.format(entry.units)} u.` : "—"}</strong></div><div><small>MARGEN POTENCIAL</small><strong class="${entry.projectedMargin !== null && entry.projectedMargin < 0 ? "negative" : ""}">${entry.projectedMargin !== null ? gil(entry.projectedMargin) : "—"}</strong></div></div>
      ${entry.favorite.notes ? `<p class="radar-card-note">“${escapeHtml(entry.favorite.notes)}”</p>` : ""}
      <div class="radar-card-actions"><button class="radar-configure" type="button">Configurar</button><a href="${moduleUrl(entry.module)}">Abrir módulo →</a><small>Agregado ${shortDate(entry.favorite.addedAt)}</small></div>`;
    card.querySelector(".radar-configure").addEventListener("click", () => openEditor(entry.key));
    return card;
  }

  function renderSummary() {
    const alerts = activeAlerts();
    const capital = state.entries.reduce((total, entry) => total + (entry.maxCapital || 0), 0);
    elements.total.textContent = integerFormat.format(state.entries.length);
    elements.alertCount.textContent = integerFormat.format(alerts.length);
    elements.capital.textContent = capital ? `${compactFormat.format(capital)} gil` : "—";
    elements.history.textContent = integerFormat.format(state.entries.filter((entry) => entry.history.length > 0).length);
  }

  function activeAlerts() {
    return state.entries.filter((entry) => entry.alertsEnabled && ["BUY", "SELL", "COOLING"].includes(entry.status));
  }

  function renderAlerts() {
    const alerts = activeAlerts();
    elements.alertCopy.textContent = alerts.length
      ? `${alerts.length} regla${alerts.length === 1 ? "" : "s"} requieren atención con el último snapshot.`
      : "Ningún objetivo personal se cumple ahora. El radar seguirá evaluándolos en cada actualización.";
    elements.alerts.replaceChildren(...alerts.slice(0, 6).map((entry) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `radar-alert status-${entry.status.toLowerCase()}`;
      button.innerHTML = `<span>${escapeHtml(STATUSES[entry.status].label)}</span><strong>${escapeHtml(entry.name)}</strong><small>${entry.status === "SELL" ? `${gil(entry.currentSellPrice)} ≥ ${gil(entry.sellTarget)}` : entry.status === "BUY" ? `${gil(entry.currentBuyPrice)} ≤ ${gil(entry.buyTarget)}` : trendLabel(entry.trend?.signal)}</small>`;
      button.addEventListener("click", () => openEditor(entry.key));
      return button;
    }));
    emitOpenPageNotifications(alerts);
  }

  function emitOpenPageNotifications(alerts) {
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const notified = readSessionNotices();
    alerts.forEach((entry) => {
      const id = `${entry.key}:${entry.status}:${Math.round(entry.currentBuyPrice || entry.currentSellPrice || 0)}`;
      if (notified[id]) return;
      new Notification(`Mi radar: ${entry.name}`, { body: `${STATUSES[entry.status].label} · ${STATUSES[entry.status].detail}` });
      notified[id] = true;
    });
    try { sessionStorage.setItem("gil-intelligence.radar-notices", JSON.stringify(notified)); } catch { /* In-page alerts remain available. */ }
  }

  function readSessionNotices() {
    try { return JSON.parse(sessionStorage.getItem("gil-intelligence.radar-notices") || "{}"); }
    catch { return {}; }
  }

  function openEditor(key) {
    const entry = state.entries.find((candidate) => candidate.key === key);
    if (!entry) return;
    state.editingKey = key;
    elements.heading.innerHTML = `${GilItemIcons.markup(entry.iconId, { fallback: "signal" })}<div><p class="eyebrow">REGLAS PERSONALES</p><h2>${escapeHtml(entry.name)}</h2><span>${escapeHtml(moduleLabel(entry.module))} · agregado ${shortDate(entry.favorite.addedAt)}</span></div>`;
    elements.buy.value = entry.buyTarget || "";
    elements.sell.value = entry.sellTarget || "";
    elements.maxCapital.value = entry.maxCapital || "";
    elements.preferredWorld.value = entry.favorite.preferredWorldName || "";
    elements.notes.value = entry.favorite.notes || "";
    elements.noteCount.textContent = elements.notes.value.length;
    elements.alertEnabled.checked = entry.alertsEnabled;
    setFormMessage("");
    elements.editor.showModal();
  }

  async function saveEditor(event) {
    event.preventDefault();
    if (!state.editingKey) return;
    elements.save.disabled = true;
    setFormMessage("");
    const metadata = {
      buyTarget: inputNumber(elements.buy), sellTarget: inputNumber(elements.sell),
      maxCapital: inputNumber(elements.maxCapital), preferredWorldName: elements.preferredWorld.value.trim(),
      notes: elements.notes.value.trim(), alertsEnabled: elements.alertEnabled.checked,
    };
    try {
      await GilWatchlist.update(state.editingKey, metadata);
      rebuild();
      elements.editor.close();
    } catch (error) {
      setFormMessage(error.message || "No pudimos guardar tus reglas.");
    } finally {
      elements.save.disabled = false;
    }
  }

  async function removeEditing() {
    const entry = state.entries.find((candidate) => candidate.key === state.editingKey);
    if (!entry || !window.confirm(`¿Quitar ${entry.name} de Mi radar?`)) return;
    elements.remove.disabled = true;
    try {
      await GilWatchlist.remove(entry.key);
      rebuild();
      elements.editor.close();
    } catch (error) {
      setFormMessage(error.message || "No pudimos quitar el favorito.");
    } finally {
      elements.remove.disabled = false;
    }
  }

  function setFormMessage(message) {
    elements.message.hidden = !message;
    elements.message.textContent = message || "";
  }

  function hydrateWorlds(routes) {
    const names = [...new Set(routes.map((route) => route.sourceWorldName).filter(Boolean))].sort(collator.compare);
    elements.worlds.replaceChildren(...names.map((name) => {
      const option = document.createElement("option"); option.value = name; return option;
    }));
  }

  function historyMarkup(points) {
    const values = points.map((point) => finite(point.currentSellPrice)).filter((value) => value !== null);
    if (!values.length) return '<div class="radar-history"><div><small>HISTORIAL DESDE FAVORITO</small><strong>Esperando próximo refresh</strong></div><p>El primer punto se guardará automáticamente con la siguiente actualización.</p></div>';
    const first = values[0]; const last = values.at(-1); const change = first ? (last - first) / first : null;
    return `<div class="radar-history"><div><small>HISTORIAL DESDE FAVORITO</small><strong>${points.length} punto${points.length === 1 ? "" : "s"} · ${change === null ? "base inicial" : signedPercent(change)}</strong></div>${sparkline(values)}<p>${gil(first)} → ${gil(last)}</p></div>`;
  }

  function sparkline(values) {
    if (values.length < 2) return '<span class="radar-history-single" aria-hidden="true"></span>';
    const width = 260; const height = 54; const minimum = Math.min(...values); const maximum = Math.max(...values); const range = maximum - minimum || 1;
    const points = values.map((value, index) => `${(index / (values.length - 1)) * width},${height - 5 - ((value - minimum) / range) * (height - 10)}`).join(" ");
    return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="Evolución del precio"><polyline points="${points}" /></svg>`;
  }

  function conversionKey(item) {
    return `conversion:${item.currencyItemId}:${item.currencyQuantity}:${item.rewardItemId}:${item.rewardQuantity}:${item.rewardIsHq ? 1 : 0}`;
  }
  function moduleLabel(value) { return MODULES[value]?.label || value || "Favorito"; }
  function moduleUrl(value) { return MODULES[value]?.url || "./signals.html"; }
  function inputNumber(input) { const value = Number(input.value); return input.value && Number.isFinite(value) && value > 0 ? value : null; }
  function positiveNumber(value) { const number = Number(value); return Number.isFinite(number) && number > 0 ? number : null; }
  function finite(value, fallback = null) { const number = Number(value); return value !== null && value !== undefined && Number.isFinite(number) ? number : fallback; }
  function gil(value) { return value !== null && value !== undefined && Number.isFinite(Number(value)) ? `${compactFormat.format(Number(value))} gil` : "—"; }
  function velocity(value) { return Number.isFinite(value) ? `${decimalFormat.format(value)} / día` : "—"; }
  function trendLabel(value) { return ({ DEMAND_UP: "Demanda al alza", PRICE_UP: "Precio al alza", COOLING: "Señal enfriándose", STABLE: "Mercado estable" })[value] || "Sin tendencia suficiente"; }
  function signedPercent(value) { return Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${percentFormat.format(value)}` : "—"; }
  function shortDate(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? "sin fecha" : dateFormat.format(date); }
  function relativeTime(value) { const minutes = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 60000)); if (minutes < 60) return `hace ${Math.max(1, minutes)} min`; const hours = Math.round(minutes / 60); return hours < 24 ? `hace ${hours} h` : `hace ${Math.round(hours / 24)} d`; }
  function normalize(value) { return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim(); }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }

  elements.search.addEventListener("input", (event) => { state.search = event.target.value; applyFilters(); });
  elements.status.addEventListener("change", (event) => { state.status = event.target.value; applyFilters(); });
  elements.module.addEventListener("change", (event) => { state.module = event.target.value; applyFilters(); });
  elements.sort.addEventListener("change", (event) => { state.sort = event.target.value; applyFilters(); });
  elements.close.addEventListener("click", () => elements.editor.close());
  elements.editor.addEventListener("click", (event) => { if (event.target === elements.editor) elements.editor.close(); });
  elements.notes.addEventListener("input", () => { elements.noteCount.textContent = elements.notes.value.length; });
  elements.form.addEventListener("submit", (event) => void saveEditor(event));
  elements.remove.addEventListener("click", () => void removeEditing());
  document.addEventListener("keydown", (event) => { if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") { event.preventDefault(); elements.search.focus(); } });
  loadRadar();
})();
