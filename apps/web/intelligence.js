(function initializeIntelligenceLayer() {
  const documentCache = new Map();
  let indexPromise = null;
  let historyIndexPromise = null;
  const integerFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 0 });
  const decimalFormat = new Intl.NumberFormat("es-CL", { maximumFractionDigits: 1 });
  const compactFormat = new Intl.NumberFormat("es-CL", { notation: "compact", maximumFractionDigits: 2 });
  const percentFormat = new Intl.NumberFormat("es-CL", { style: "percent", maximumFractionDigits: 1 });
  const moduleLabels = {
    conversion: "Conversión", market: "Mercado", opportunity: "Oportunidad",
    projection: "Proyección", snipe: "Snipeo",
  };

  function endpoints(kind) {
    const api = window.GIL_INTELLIGENCE_CONFIG?.apiBaseUrl?.replace(/\/$/, "");
    const files = { dashboard: "dashboard", "market-items": "market-items", "market-history": "market-history", opportunities: "opportunities", signals: "signals" };
    return api ? [`${api}/v1/${kind}`, `./data/${files[kind]}.json`] : [`./data/${files[kind]}.json`];
  }

  async function fetchDocument(kind) {
    if (documentCache.has(kind)) return documentCache.get(kind);
    const promise = (async () => {
      let lastError;
      for (const endpoint of endpoints(kind)) {
        try {
          const response = await fetch(endpoint);
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return await response.json();
        } catch (error) { lastError = error; }
      }
      throw lastError || new Error(`${kind} no disponible`);
    })();
    documentCache.set(kind, promise);
    try { return await promise; }
    catch (error) { documentCache.delete(kind); throw error; }
  }

  function normalize(value) {
    return String(value ?? "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().trim();
  }

  function finite(value) { return value === null || value === undefined || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null; }
  function gil(value) { const number = finite(value); return number === null ? "Sin datos" : `${compactFormat.format(number)} gil`; }
  function velocity(value) { const number = finite(value); return number === null ? "Sin datos Cactuar" : `${decimalFormat.format(number)} / día`; }
  function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }

  function quality(input = {}) {
    const trend = input.trend || input.context?.trend || {};
    const velocityValue = finite(input.dailySaleVelocity ?? input.velocity ?? input.context?.velocity);
    const samples = finite(input.historySamples ?? trend.historyPoints ?? input.outcome?.observations) || 0;
    const age = finite(input.dataAgeHours ?? input.stockDataAgeHours);
    const status = String(input.status || "").toUpperCase();
    if (status === "NOT_TRADEABLE") {
      return { key: "internal", label: "No comerciable", detail: "La recompensa existe como canje, pero no se puede vender en Market Board." };
    }
    if (status === "NO_MARKET_DATA") {
      return { key: "unpriced", label: "Sin precio", detail: "La recompensa es comerciable, pero Cactuar no tiene un precio observable ahora." };
    }
    if (status === "STALE" || (age !== null && age > 24)) {
      return { key: "stale", label: "Datos antiguos", detail: "La última observación quedó fuera de la ventana de frescura." };
    }
    if (velocityValue === null) {
      return { key: "no-velocity", label: "Sin velocidad", detail: "Universalis no publicó ventas/día para Cactuar; no significa cero ventas." };
    }
    if (trend.stability === "LOW" || finite(trend.priceVolatility) >= 0.2) {
      return { key: "volatile", label: "Mercado volátil", detail: "El precio cambió demasiado entre los snapshots disponibles." };
    }
    if (samples < 3 || (finite(input.confidenceScore) !== null && finite(input.confidenceScore) < 65)) {
      return { key: "limited", label: "Muestra limitada", detail: "Hay mercado observable, pero todavía faltan snapshots para llamarlo estable." };
    }
    return { key: "solid", label: "Datos sólidos", detail: "Datos frescos, velocidad local y al menos tres observaciones comparables." };
  }

  function qualityMarkup(input) {
    const result = quality(input);
    return `<span class="quality-pill ${result.key}" title="${escapeHtml(result.detail)}"><i></i>${escapeHtml(result.label)}</span>`;
  }

  function qualityElement(input) {
    const wrapper = document.createElement("span");
    wrapper.innerHTML = qualityMarkup(input);
    return wrapper.firstElementChild;
  }

  function sparkline(points, options = {}) {
    const values = (points || []).map((point) => finite(point.averageSalePrice ?? point.value)).filter((value) => value !== null);
    if (values.length < 2) return '<span class="spark-empty">Aún sin tendencia</span>';
    const width = options.width || 96;
    const height = options.height || 30;
    const pad = 3;
    const min = Math.min(...values);
    const max = Math.max(...values);
    const spread = max - min || 1;
    const coordinates = values.map((value, index) => ({
      x: pad + (index * (width - pad * 2)) / Math.max(1, values.length - 1),
      y: pad + ((max - value) / spread) * (height - pad * 2),
    }));
    const direction = values.at(-1) > values[0] ? "up" : values.at(-1) < values[0] ? "down" : "flat";
    return `<svg class="mini-spark ${direction}" viewBox="0 0 ${width} ${height}" role="img" aria-label="Tendencia de ${values.length} snapshots"><polyline points="${coordinates.map((point) => `${point.x.toFixed(1)},${point.y.toFixed(1)}`).join(" ")}"/><circle cx="${coordinates.at(-1).x.toFixed(1)}" cy="${coordinates.at(-1).y.toFixed(1)}" r="2.5"/></svg>`;
  }

  async function historyIndex() {
    if (historyIndexPromise) return historyIndexPromise;
    historyIndexPromise = fetchDocument("market-history").then((payload) => new Map((payload.series || []).map((series) => [series.key, series])));
    return historyIndexPromise;
  }

  async function hydrateSparklines(root = document) {
    const targets = [...root.querySelectorAll("[data-spark-key]:not([data-spark-ready])")];
    if (!targets.length) return;
    targets.forEach((target) => { target.dataset.sparkReady = "loading"; });
    try {
      const histories = await historyIndex();
      targets.forEach((target) => {
        if (!target.isConnected) return;
        const series = histories.get(target.dataset.sparkKey);
        target.innerHTML = sparkline(series?.points || []);
        target.dataset.sparkReady = "true";
        if (series?.trend?.signal) target.title = `${trendLabel(series.trend.signal)} · ${series.points.length} snapshots`;
      });
    } catch (_error) {
      targets.forEach((target) => { if (target.isConnected) target.innerHTML = '<span class="spark-empty">Sin historial</span>'; });
    }
  }

  function trendLabel(value) {
    return ({ DEMAND_UP: "Demanda al alza", PRICE_UP: "Precio al alza", PRICE_DOWN: "Precio a la baja", STABLE: "Estable", NEW: "Nueva serie" })[value] || "Tendencia disponible";
  }

  function upsert(map, raw) {
    const itemId = Number(raw.itemId);
    if (!Number.isSafeInteger(itemId) || itemId <= 0) return;
    const qualityValue = raw.quality === "HQ" ? "HQ" : "NQ";
    const key = `${itemId}:${qualityValue}`;
    const current = map.get(key) || { itemId, quality: qualityValue, modules: new Set(), aliases: new Set() };
    Object.entries(raw).forEach(([field, value]) => {
      if (value !== null && value !== undefined && value !== "" && !["modules", "aliases"].includes(field)) current[field] = value;
    });
    (raw.modules || []).forEach((module) => current.modules.add(module));
    (raw.aliases || []).filter(Boolean).forEach((alias) => current.aliases.add(alias));
    map.set(key, current);
  }

  async function buildIndex() {
    if (indexPromise) return indexPromise;
    indexPromise = (async () => {
      const [market, dashboard, opportunities, signals] = await Promise.all([
        fetchDocument("market-items"), fetchDocument("dashboard"), fetchDocument("opportunities"), fetchDocument("signals"),
      ]);
      const map = new Map();
      (market.items || []).forEach((item) => upsert(map, { ...item, modules: ["market"] }));
      (dashboard.conversions || []).forEach((item) => {
        upsert(map, { itemId: item.rewardItemId, quality: item.rewardIsHq ? "HQ" : "NQ", name: item.rewardName, iconId: item.rewardIconId, status: item.status, dailySaleVelocity: item.dailySaleVelocity, modules: ["conversion"], aliases: [item.currencyName] });
        upsert(map, { itemId: item.currencyItemId, quality: "NQ", name: item.currencyName, iconId: item.currencyIconId, modules: ["conversion"], aliases: [item.rewardName] });
      });
      (opportunities.opportunities || []).forEach((item) => upsert(map, { ...item, modules: ["opportunity", "snipe"] }));
      (signals.signals || []).forEach((signal) => upsert(map, { itemId: signal.itemId, quality: signal.quality, name: signal.title, iconId: signal.iconId, context: signal.context, outcome: signal.outcome, modules: [signal.module], aliases: [signal.subtitle] }));
      return { entries: [...map.values()].sort((a, b) => String(a.name).localeCompare(String(b.name), "es", { sensitivity: "base" })), market, dashboard, opportunities, signals };
    })();
    return indexPromise;
  }

  function searchScore(entry, query) {
    const name = normalize(entry.name);
    const id = String(entry.itemId);
    const haystack = normalize([entry.name, ...entry.aliases, id, [...entry.modules].map((module) => moduleLabels[module]).join(" ")].join(" "));
    if (id === query) return 1000;
    if (name === query) return 900;
    if (name.startsWith(query)) return 700 - name.length / 100;
    if (name.includes(query)) return 500 - name.indexOf(query);
    if (haystack.includes(query)) return 250 - haystack.indexOf(query) / 100;
    return -1;
  }

  function moduleLinks(modules) {
    const urls = { conversion: "./", market: "./market.html", opportunity: "./opportunities.html", projection: "./projections.html", snipe: "./snipes.html" };
    return [...modules].filter((module) => urls[module]).map((module) => `<a href="${urls[module]}">${escapeHtml(moduleLabels[module])}</a>`).join("");
  }

  function actionPlan({ entry, market, opportunities, signals, conversions }) {
    const route = [...opportunities].sort((a, b) => (b.confidenceScore || 0) - (a.confidenceScore || 0))[0];
    if (route) {
      const buy = route.averagePurchasePrice ?? route.sourcePrice;
      const breakEven = buy / 0.95;
      return {
        eyebrow: "PLAN DE COMPRA REGIONAL",
        action: `Comprar hasta ${integerFormat.format(route.recommendedQuantity)} unidades en ${route.sourceWorldName} a un promedio máximo de ${gil(buy)}.`,
        exit: `Publicar gradualmente en Cactuar hasta ${gil(route.conservativeSellPrice)}; beneficio estimado ${gil(route.estimatedTripProfit)}.`,
        invalidation: `No comprar si el promedio supera ${gil(buy)} o si la salida conservadora cae bajo el equilibrio de ${gil(breakEven)}.`,
      };
    }
    const craft = market.find((item) => finite(item.recipe?.profitPerCraft) > 0);
    if (craft) {
      const amount = Math.max(1, Math.min(99, Math.floor((finite(craft.dailySaleVelocity) || 4) * 0.25)));
      const breakEven = craft.recipe.estimatedMaterialCost / Math.max(1, craft.recipe.resultQuantity || 1) / 0.95;
      return {
        eyebrow: "PLAN DE CRAFTING",
        action: `Fabricar un lote inicial de ${integerFormat.format(amount)} unidades; costo completo ${gil(craft.recipe.estimatedMaterialCost)} por craft.`,
        exit: `Usar una salida conservadora de ${gil(craft.recipe.conservativeSalePrice)} y reponer sólo después de vender.`,
        invalidation: `Detener el craft si el precio cae bajo ${gil(breakEven)} o desaparece la velocidad local.`,
      };
    }
    const conversion = conversions.filter((item) => finite(item.netGilPerCurrency) !== null)
      .sort((a, b) => b.netGilPerCurrency - a.netGilPerCurrency)[0];
    if (conversion) {
      const batchAmount = finite(conversion.dailySaleVelocity) === null ? null : Math.max(1, Math.ceil(conversion.dailySaleVelocity * 0.2));
      const batch = batchAmount === null ? "una unidad piloto" : `${integerFormat.format(batchAmount)} ${batchAmount === 1 ? "unidad" : "unidades"}`;
      return {
        eyebrow: "PLAN DE CONVERSIÓN",
        action: `Convertir primero ${batch} de ${conversion.rewardName}; retorno actual ${gil(conversion.netGilPerCurrency)} por moneda.`,
        exit: `Listar cerca del mínimo observado de ${gil(conversion.marketUnitPrice)} y dividir cantidades grandes.`,
        invalidation: "Pausar si el listing mínimo baja 15% o la profundidad visible absorbe menos que el lote.",
      };
    }
    const bundle = conversions.find((item) => item.isMultiCost && finite(item.netGilPerExchange) !== null);
    if (bundle) {
      const costs = (bundle.costComponents || []).map((item) => `${integerFormat.format(item.quantity)} ${item.name}`).join(" + ");
      return {
        eyebrow: "PLAN DE CANJE COMBINADO",
        action: `Reunir ${costs} para un canje completo de ${bundle.rewardName}. Valor neto actual del resultado: ${gil(bundle.netGilPerExchange)}.`,
        exit: `Listar cerca de ${gil(bundle.marketUnitPrice)} y validar que ambas monedas tengan un uso alternativo menor.`,
        invalidation: "No atribuir todo el retorno a una sola moneda: el canje requiere todos los componentes indicados.",
      };
    }
    if (conversions.some((item) => item.status === "NOT_TRADEABLE")) {
      return {
        eyebrow: "USO INTERNO",
        action: "Este canje sirve para progresión, colección o equipamiento personal; no produce una salida vendible en Market Board.",
        exit: "Compara el costo con tu necesidad dentro del juego, no con una rentabilidad en gil.",
        invalidation: "No gastes la moneda si estás ahorrando para otra recompensa interna prioritaria.",
      };
    }
    const projection = signals.find((signal) => signal.module === "projection");
    if (projection) {
      const current = finite(projection.metricValue);
      return {
        eyebrow: "PLAN DE ACUMULACIÓN",
        action: `Acumular por tramos, sin pagar más que la referencia actual de ${gil(current)}.`,
        exit: "Revisar en las ventanas 0–72 h, leveling y pre-Savage; vender en fuerza, no después del pico.",
        invalidation: "Invalidar si la demanda cae entre snapshots o la tesis histórica deja de coincidir con el rol actual.",
      };
    }
    const row = market[0];
    if (row?.gatherable) {
      const amount = Math.max(1, Math.min(999, Math.floor((finite(row.dailySaleVelocity) || 4) * 0.25)));
      return {
        eyebrow: "PLAN DE RECOLECCIÓN",
        action: `Recolectar un lote de prueba de ${integerFormat.format(amount)} unidades y medir cuánto tarda en venderse.`,
        exit: `Partir la venta cerca de ${gil(row.averageSalePrice)} sin inundar el Market Board.`,
        invalidation: "Cambiar de nodo si desaparece la velocidad de Cactuar o el precio cae 20%.",
      };
    }
    return {
      eyebrow: "SIN ACCIÓN TODAVÍA",
      action: "Este ítem aparece en el catálogo, pero todavía no tiene una entrada defendible.",
      exit: "Espera precio, velocidad o una señal verificable antes de comprometer gil.",
      invalidation: "No comprar sólo porque exista un listing aislado.",
    };
  }

  function detailStats(entry, marketRows, signals) {
    const row = marketRows.find((item) => item.quality === entry.quality) || marketRows[0];
    const bestSignal = [...signals].sort((a, b) => b.score - a.score)[0];
    return [
      ["Precio medio", gil(row?.averageSalePrice)], ["Listing mínimo", gil(row?.minListingPrice)],
      ["Ventas / día", velocity(row?.dailySaleVelocity)], ["Ingreso diario", gil(row?.estimatedDailyRevenue)],
      ["Mejor señal", bestSignal ? `${bestSignal.score}/100` : "Sin señal"], ["Calidad", quality(row || entry).label],
    ];
  }

  async function openItem(entry) {
    const dialog = document.querySelector("#intelligence-dialog");
    const content = dialog.querySelector(".intelligence-content");
    content.innerHTML = '<div class="intelligence-loading"><span></span><p>Uniendo mercado, historial y señales…</p></div>';
    if (!dialog.open) dialog.showModal();
    try {
      const bundle = await buildIndex();
      const marketRows = (bundle.market.items || []).filter((item) => item.itemId === entry.itemId);
      const opportunities = (bundle.opportunities.opportunities || []).filter((item) => item.itemId === entry.itemId && item.quality === entry.quality);
      const signals = (bundle.signals.signals || []).filter((signal) => signal.itemId === entry.itemId && signal.quality === entry.quality);
      const conversions = (bundle.dashboard.conversions || []).filter((item) => item.rewardItemId === entry.itemId || item.currencyItemId === entry.itemId);
      const history = await historyIndex();
      const series = history.get(`${entry.itemId}:${entry.quality}`);
      const plan = actionPlan({ entry, market: marketRows, opportunities, signals, conversions });
      const qualityInput = marketRows.find((item) => item.quality === entry.quality) || opportunities[0] || signals[0] || entry;
      const stats = detailStats(entry, marketRows, signals);
      const routes = opportunities.slice(0, 3).map((route) => `<div><span><strong>${escapeHtml(route.sourceWorldName)}</strong><small>${integerFormat.format(route.recommendedQuantity)} u. · compra ${gil(route.averagePurchasePrice ?? route.sourcePrice)}</small></span><b>+${gil(route.estimatedTripProfit)}</b></div>`).join("");
      const signalRows = signals.slice(0, 6).map((signal) => `<a href="${escapeHtml(signal.url)}"><span>${escapeHtml(moduleLabels[signal.module] || signal.module)} · ${escapeHtml(signal.state)}</span><strong>${signal.score}/100</strong><small>${escapeHtml(signal.reason)}</small></a>`).join("");
      const conversionRows = conversions.slice(0, 4).map((item) => {
        const costs = item.isMultiCost
          ? (item.costComponents || []).map((cost) => `${integerFormat.format(cost.quantity)} ${cost.name}`).join(" + ")
          : `${integerFormat.format(item.currencyQuantity)} ${item.currencyName}`;
        const value = item.isMultiCost ? `${gil(item.netGilPerExchange)} / canje` : gil(item.netGilPerCurrency);
        return `<div><span><strong>${escapeHtml(costs)} → ${escapeHtml(item.rewardName)}</strong><small>${item.isMultiCost ? "Canje combinado" : "Conversión directa"} · ${velocity(item.dailySaleVelocity)}</small></span><b>${escapeHtml(value)}</b></div>`;
      }).join("");
      content.innerHTML = `<div class="intelligence-body">
        <p class="eyebrow">FICHA UNIVERSAL · ITEM ${entry.itemId}</p>
        <div class="intelligence-title">${GilItemIcons.markup(entry.iconId, { fallback: "item", tone: opportunities.length ? "gold" : "" })}<div><h2>${escapeHtml(entry.name)}${entry.quality === "HQ" ? " · HQ" : ""}</h2><div class="intelligence-tags">${qualityMarkup(qualityInput)}${moduleLinks(entry.modules)}</div></div></div>
        <div class="intelligence-stats">${stats.map(([label, value]) => `<div><small>${escapeHtml(label)}</small><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>
        <section class="action-plan"><small>${escapeHtml(plan.eyebrow)}</small><h3>${escapeHtml(plan.action)}</h3><div><p><b>Salida</b>${escapeHtml(plan.exit)}</p><p><b>Invalidación</b>${escapeHtml(plan.invalidation)}</p></div></section>
        <section class="universal-history"><div class="universal-heading"><div><small>EVOLUCIÓN EN CACTUAR</small><strong>${series ? trendLabel(series.trend?.signal) : "Aún sin serie"}</strong></div><span>${series?.points?.length || 0} snapshots</span></div><div class="universal-chart">${largeSparkline(series?.points || [])}</div></section>
        ${routes ? `<section class="universal-section"><div class="universal-heading"><div><small>MEJORES RUTAS</small><strong>Compra regional → Cactuar</strong></div></div><div class="universal-list">${routes}</div></section>` : ""}
        ${conversionRows ? `<section class="universal-section"><div class="universal-heading"><div><small>CONVERSIONES</small><strong>Cómo obtenerlo o utilizarlo</strong></div></div><div class="universal-list">${conversionRows}</div></section>` : ""}
        ${signalRows ? `<section class="universal-section"><div class="universal-heading"><div><small>SEÑALES ACTIVAS</small><strong>Por qué aparece</strong></div></div><div class="universal-signals">${signalRows}</div></section>` : ""}
        <p class="intelligence-footnote">Reglas deterministas · sin ML. Confirma precio, HQ, cantidad y retainer dentro del juego antes de comprar.</p>
      </div>`;
    } catch (error) {
      content.innerHTML = `<div class="intelligence-error"><h2>No pudimos construir la ficha</h2><p>${escapeHtml(error.message)}</p></div>`;
    }
  }

  function largeSparkline(points) {
    const values = (points || []).map((point) => finite(point.averageSalePrice)).filter((value) => value !== null);
    if (values.length < 2) return "<p>Aún se necesitan dos snapshots para mostrar una tendencia.</p>";
    const chart = sparkline(points, { width: 620, height: 150 });
    const first = values[0]; const last = values.at(-1); const change = first ? (last - first) / first : 0;
    return `${chart}<div class="universal-chart-meta"><span>Inicio ${gil(first)}</span><strong>${change >= 0 ? "+" : ""}${percentFormat.format(change)}</strong><span>Actual ${gil(last)}</span></div>`;
  }

  function createUi() {
    const topbarMeta = document.querySelector(".topbar-meta");
    if (topbarMeta) {
      const trigger = document.createElement("button");
      trigger.type = "button";
      trigger.className = "global-search-trigger";
      trigger.innerHTML = '<span>⌕</span><b>Buscar</b><kbd>Ctrl K</kbd>';
      trigger.setAttribute("aria-label", "Buscar cualquier ítem");
      topbarMeta.prepend(trigger);
      trigger.addEventListener("click", openSearch);
    }
    document.body.insertAdjacentHTML("beforeend", `
      <dialog id="global-search-dialog" class="global-search-dialog">
        <div class="global-search-shell"><div class="global-search-input"><span>⌕</span><input type="search" placeholder="Busca cualquier ítem, moneda o señal…" autocomplete="off" /><kbd>Esc</kbd></div><p class="global-search-status">Escribe al menos dos caracteres.</p><div class="global-search-results"></div></div>
      </dialog>
      <dialog id="intelligence-dialog" class="intelligence-dialog"><button class="dialog-close intelligence-close" type="button" aria-label="Cerrar">×</button><div class="intelligence-content"></div></dialog>`);
    const searchDialog = document.querySelector("#global-search-dialog");
    const intelligenceDialog = document.querySelector("#intelligence-dialog");
    searchDialog.addEventListener("click", (event) => { if (event.target === searchDialog) searchDialog.close(); });
    intelligenceDialog.addEventListener("click", (event) => { if (event.target === intelligenceDialog) intelligenceDialog.close(); });
    intelligenceDialog.querySelector(".intelligence-close").addEventListener("click", () => intelligenceDialog.close());
    searchDialog.querySelector("input").addEventListener("input", (event) => renderSearch(event.target.value));
  }

  async function openSearch() {
    const dialog = document.querySelector("#global-search-dialog");
    const input = dialog.querySelector("input");
    if (!dialog.open) dialog.showModal();
    input.focus();
    if (input.value.trim().length >= 2) renderSearch(input.value);
  }

  function attachDetailButton(container, rawEntry) {
    if (!container || container.querySelector(".universal-detail-button")) return;
    const entry = { ...rawEntry,
      modules: rawEntry.modules instanceof Set ? rawEntry.modules : new Set(rawEntry.modules || []),
      aliases: rawEntry.aliases instanceof Set ? rawEntry.aliases : new Set(rawEntry.aliases || []),
    };
    const button = document.createElement("button");
    button.type = "button";
    button.className = "universal-detail-button";
    button.textContent = "Ver ficha universal";
    button.addEventListener("click", () => {
      const parentDialog = container.closest("dialog");
      if (parentDialog?.open) parentDialog.close();
      openItem(entry);
    });
    container.querySelector(".detail-body")?.append(button);
  }

  async function renderSearch(value) {
    const dialog = document.querySelector("#global-search-dialog");
    const results = dialog.querySelector(".global-search-results");
    const status = dialog.querySelector(".global-search-status");
    const query = normalize(value);
    if (query.length < 2) { status.textContent = "Escribe al menos dos caracteres."; results.replaceChildren(); return; }
    status.textContent = "Buscando en todas las vistas…";
    try {
      const bundle = await buildIndex();
      if (normalize(dialog.querySelector("input").value) !== query) return;
      const matches = bundle.entries.map((entry) => ({ entry, score: searchScore(entry, query) })).filter((match) => match.score >= 0).sort((a, b) => b.score - a.score).slice(0, 40);
      status.textContent = matches.length ? `${integerFormat.format(matches.length)} resultados principales` : "No encontramos ese ítem.";
      results.innerHTML = matches.map(({ entry }) => `<button type="button" data-key="${entry.itemId}:${entry.quality}">${GilItemIcons.markup(entry.iconId, { fallback: "item" })}<span><strong>${escapeHtml(entry.name)}${entry.quality === "HQ" ? " · HQ" : ""}</strong><small>Item ${entry.itemId} · ${[...entry.modules].map((module) => moduleLabels[module]).filter(Boolean).join(" · ")}</small></span>${qualityMarkup(entry)}</button>`).join("");
      results.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
        const entry = bundle.entries.find((candidate) => `${candidate.itemId}:${candidate.quality}` === button.dataset.key);
        dialog.close(); if (entry) openItem(entry);
      }));
    } catch (error) { status.textContent = `Búsqueda no disponible: ${error.message}`; }
  }

  document.addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
      event.preventDefault(); event.stopImmediatePropagation(); openSearch();
    }
  }, true);
  createUi();
  window.GilIntelligence = { attachDetailButton, fetchDocument, hydrateSparklines, openItem, quality, qualityElement, qualityMarkup, sparkline };
})();
